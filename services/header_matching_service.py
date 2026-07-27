"""Header normalization and intelligent matching for template comparison."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from core.config import PROJECT_ROOT, REQUIREDNESS
from services.template_service import TemplateContext

FUZZY_MATCH_THRESHOLD = 0.88
MATCH_TYPES = ("exact", "metadata", "normalized", "alias", "fuzzy")
MATCH_PRIORITY = {name: index for index, name in enumerate(MATCH_TYPES, start=1)}


@dataclass(frozen=True)
class HeaderMatchCandidate:
    uploaded_header: str
    target_header: str
    match_type: str
    confidence: float
    auto_eligible: bool


def normalize_header_for_matching(header: str) -> str:
    """
    Normalize a header for comparison only.

    The normalized value must never be used as a CSV column name.
    """
    if not header:
        return ""

    text = header.strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"__c$", "", text)
    text = re.sub(r"[*]", "", text)
    text = re.sub(r"[\s_\-]+", "", text)
    text = re.sub(r"[^\w]", "", text)
    return text


def load_header_aliases() -> dict[str, str]:
    """Load fallback header aliases from rules/header_aliases.json."""
    path = PROJECT_ROOT / "rules" / "header_aliases.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items()}


def analyze_header_matching(
    uploaded_headers: list[str],
    expected_headers: list[str],
    upload_method: str,
    template_context: TemplateContext | None,
    load_operation: str | None = None,
    valid_object_fields: set[str] | None = None,
) -> dict[str, Any]:
    """Match uploaded headers to target template headers using prioritized rules."""
    csv_to_api, api_to_csv = _mapping_tables(template_context)
    aliases = load_header_aliases()
    valid_fields = valid_object_fields or set()

    candidates = _collect_candidates(
        uploaded_headers,
        expected_headers,
        csv_to_api,
        api_to_csv,
        aliases,
        upload_method,
        valid_fields,
    )

    proposed_renames, exact_matches, manual_mappings, used_uploaded, used_target = _assign_matches(
        candidates,
        expected_headers,
        uploaded_headers,
    )

    unmatched_uploaded = [
        header for header in uploaded_headers
        if header not in used_uploaded
    ]
    unmatched_target = [
        header for header in expected_headers
        if header not in used_target
    ]

    required_targets, optional_targets, generated_fields, conditional_fields = _classify_unmatched_targets(
        unmatched_target,
        template_context,
        load_operation,
        csv_to_api,
    )

    effective_matching = list(exact_matches)
    effective_matching.extend(rename["target_column"] for rename in proposed_renames)

    if expected_headers:
        match_percentage = round((len(effective_matching) / len(expected_headers)) * 100, 1)
    else:
        match_percentage = 100.0

    return {
        "exact_matches": exact_matches,
        "proposed_renames": proposed_renames,
        "manual_mapping_required": manual_mappings,
        "unmatched_uploaded": unmatched_uploaded,
        "unmatched_target_required": required_targets,
        "unmatched_target_optional": optional_targets,
        "generated_fields": generated_fields,
        "conditional_fields": conditional_fields,
        "effective_matching_headers": effective_matching,
        "match_percentage": match_percentage,
    }


def enrich_template_comparison(
    comparison: dict[str, Any],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    """Merge header analysis into a raw template comparison result."""
    enriched = dict(comparison)
    enriched["matching_headers"] = analysis["effective_matching_headers"]
    enriched["missing_columns"] = analysis["unmatched_target_required"]
    enriched["extra_columns"] = analysis["unmatched_uploaded"]
    enriched["optional_missing_columns"] = analysis["unmatched_target_optional"]
    enriched["proposed_renames"] = analysis["proposed_renames"]
    enriched["manual_mapping_required"] = analysis["manual_mapping_required"]
    enriched["generated_fields"] = analysis["generated_fields"]
    enriched["conditional_fields"] = analysis["conditional_fields"]
    enriched["match_percentage"] = analysis["match_percentage"]
    enriched["header_analysis"] = analysis

    enriched["template_match"] = (
        not enriched["missing_columns"]
        and not enriched["extra_columns"]
        and not comparison.get("duplicate_columns")
        and not comparison.get("order_differences")
        and not analysis["proposed_renames"]
        and not analysis["manual_mapping_required"]
    )
    return enriched


def _mapping_tables(
    context: TemplateContext | None,
) -> tuple[dict[str, str], dict[str, str]]:
    csv_to_api: dict[str, str] = {}
    api_to_csv: dict[str, str] = {}

    if context and context.template_definition:
        csv_to_api.update(context.template_definition.csv_label_to_api)
        api_to_csv.update(context.template_definition.api_to_csv_label)

    if context and context.fallback_config:
        for label, cfg in context.fallback_config.get("column_mappings", {}).items():
            api_name = cfg.get("suggested_api_field")
            if api_name:
                csv_to_api.setdefault(label, api_name)
                api_to_csv.setdefault(api_name, label)

    return csv_to_api, api_to_csv


def _collect_candidates(
    uploaded_headers: list[str],
    expected_headers: list[str],
    csv_to_api: dict[str, str],
    api_to_csv: dict[str, str],
    aliases: dict[str, str],
    upload_method: str,
    valid_fields: set[str],
) -> list[HeaderMatchCandidate]:
    candidates: list[HeaderMatchCandidate] = []

    for target in expected_headers:
        if upload_method == "Workbench" and valid_fields and target not in valid_fields:
            continue

        for uploaded in uploaded_headers:
            candidate = _evaluate_pair(
                uploaded,
                target,
                csv_to_api,
                api_to_csv,
                aliases,
            )
            if candidate:
                candidates.append(candidate)

    candidates.sort(
        key=lambda item: (MATCH_PRIORITY[item.match_type], -item.confidence, item.uploaded_header)
    )
    return candidates


def _evaluate_pair(
    uploaded: str,
    target: str,
    csv_to_api: dict[str, str],
    api_to_csv: dict[str, str],
    aliases: dict[str, str],
) -> HeaderMatchCandidate | None:
    if uploaded == target:
        return HeaderMatchCandidate(uploaded, target, "exact", 1.0, True)

    metadata_target = csv_to_api.get(uploaded)
    if metadata_target == target:
        return HeaderMatchCandidate(uploaded, target, "metadata", 1.0, True)

    metadata_source = api_to_csv.get(target)
    if metadata_source == uploaded:
        return HeaderMatchCandidate(uploaded, target, "metadata", 1.0, True)

    uploaded_norm = normalize_header_for_matching(uploaded)
    target_norm = normalize_header_for_matching(target)
    if uploaded_norm and uploaded_norm == target_norm:
        return HeaderMatchCandidate(uploaded, target, "normalized", 0.98, True)

    alias_target = aliases.get(uploaded)
    if alias_target == target:
        return HeaderMatchCandidate(uploaded, target, "alias", 0.95, True)

    for alias_source, alias_api in aliases.items():
        if alias_api != target:
            continue
        if normalize_header_for_matching(alias_source) == uploaded_norm:
            return HeaderMatchCandidate(uploaded, target, "alias", 0.94, True)

    if uploaded_norm and target_norm:
        ratio = SequenceMatcher(None, uploaded_norm, target_norm).ratio()
        if ratio >= FUZZY_MATCH_THRESHOLD:
            return HeaderMatchCandidate(uploaded, target, "fuzzy", ratio, True)

    return None


def _assign_matches(
    candidates: list[HeaderMatchCandidate],
    expected_headers: list[str],
    uploaded_headers: list[str],
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]], set[str], set[str]]:
    proposed_renames: list[dict[str, Any]] = []
    exact_matches: list[str] = []
    manual_mappings: list[dict[str, Any]] = []
    used_uploaded: set[str] = set()
    used_target: set[str] = set()

    by_target: dict[str, list[HeaderMatchCandidate]] = {target: [] for target in expected_headers}
    by_uploaded: dict[str, list[HeaderMatchCandidate]] = {header: [] for header in uploaded_headers}
    for candidate in candidates:
        by_target.setdefault(candidate.target_header, []).append(candidate)
        by_uploaded.setdefault(candidate.uploaded_header, []).append(candidate)

    for target in expected_headers:
        target_candidates = [
            candidate for candidate in by_target.get(target, [])
            if candidate.uploaded_header not in used_uploaded
        ]
        if not target_candidates:
            continue

        best_priority = MATCH_PRIORITY[target_candidates[0].match_type]
        top_candidates = [
            candidate for candidate in target_candidates
            if MATCH_PRIORITY[candidate.match_type] == best_priority
        ]

        uploaded_candidates = [
            candidate for candidate in top_candidates
            if len([
                alt for alt in by_uploaded.get(candidate.uploaded_header, [])
                if alt.target_header not in used_target
                and MATCH_PRIORITY[alt.match_type] == MATCH_PRIORITY[candidate.match_type]
            ]) == 1
        ]

        if len(top_candidates) == 1 and len(uploaded_candidates) == 1:
            candidate = top_candidates[0]
            if candidate.match_type == "exact":
                exact_matches.append(target)
            else:
                proposed_renames.append(_rename_dict(candidate))
            used_uploaded.add(candidate.uploaded_header)
            used_target.add(candidate.target_header)
            continue

        if len(top_candidates) > 1 or len(uploaded_candidates) != 1:
            manual_mappings.append({
                "uploaded_header": top_candidates[0].uploaded_header if len({c.uploaded_header for c in top_candidates}) == 1 else None,
                "target_header": target,
                "possible_targets": [target],
                "possible_sources": sorted({candidate.uploaded_header for candidate in top_candidates}),
                "description": _manual_mapping_description(target, top_candidates),
            })

    return proposed_renames, exact_matches, manual_mappings, used_uploaded, used_target


def _rename_dict(candidate: HeaderMatchCandidate) -> dict[str, Any]:
    return {
        "source_column": candidate.uploaded_header,
        "target_column": candidate.target_header,
        "match_type": candidate.match_type,
        "confidence": round(candidate.confidence, 3),
        "description": (
            f"Rename `{candidate.uploaded_header}` → `{candidate.target_header}` "
            f"({candidate.match_type} match)"
        ),
    }


def _manual_mapping_description(
    target: str,
    candidates: list[HeaderMatchCandidate],
) -> str:
    sources = sorted({candidate.uploaded_header for candidate in candidates})
    if len(sources) == 1:
        return (
            f"Uploaded header `{sources[0]}` matches multiple possible target fields for `{target}`."
        )
    return (
        f"Multiple uploaded headers may map to `{target}`: {', '.join(f'`{s}`' for s in sources)}"
    )


def _classify_unmatched_targets(
    unmatched_target: list[str],
    context: TemplateContext | None,
    load_operation: str | None,
    csv_to_api: dict[str, str],
) -> tuple[list[str], list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    required: list[str] = []
    optional: list[str] = []
    generated: list[dict[str, Any]] = []
    conditional: list[dict[str, Any]] = []

    required_api = _required_api_fields(context, load_operation, csv_to_api)

    for target in unmatched_target:
        if target == "Id":
            if load_operation == "Update":
                conditional.append({
                    "field": "Id",
                    "requiredness": REQUIREDNESS["UPDATE"],
                    "description": "Id is required only for Update.",
                })
            continue

        if target == "Type" and context and context.is_account_template:
            generated.append({
                "field": "Type",
                "value": context.required_type_value or "Customer",
                "requiredness": REQUIREDNESS["COPILOT"],
                "description": f"Type = {context.required_type_value or 'Customer'}",
            })
            continue

        if target in required_api:
            required.append(target)
        else:
            optional.append(target)

    return required, optional, generated, conditional


def _required_api_fields(
    context: TemplateContext | None,
    load_operation: str | None,
    csv_to_api: dict[str, str],
) -> set[str]:
    required: set[str] = {"Name"}
    if load_operation == "Update":
        required.add("Id")

    if context and context.template_definition:
        for label in context.template_definition.required_csv_labels:
            api_name = csv_to_api.get(label)
            if api_name:
                required.add(api_name)
    elif context and context.fallback_config:
        for label, cfg in context.fallback_config.get("column_mappings", {}).items():
            if label.startswith("*") and cfg.get("suggested_api_field"):
                required.add(cfg["suggested_api_field"])

    return required
