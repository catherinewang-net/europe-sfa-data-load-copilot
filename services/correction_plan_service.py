"""Build approvable correction plans without mutating uploaded data."""

from __future__ import annotations

from typing import Any

import pandas as pd

from core.config import CORRECTION_CATEGORIES, REQUIREDNESS
from core.reference_templates import load_reference_headers
from engines.template_comparison import compare_to_reference
from services.header_matching_service import analyze_header_matching, enrich_template_comparison
from services.template_service import TemplateContext, resolve_template
from validators.template_validator import validate_template


def detect_file_style(uploaded_headers: list[str], template: str) -> dict[str, Any]:
    """Identify whether the upload looks like DIT, Workbench, mixed, or unknown."""
    dit_pct = 0.0
    workbench_pct = 0.0

    try:
        dit_headers, _ = load_reference_headers("Data Import Tool", template)
        dit_pct = validate_template(uploaded_headers, dit_headers)["match_percentage"]
    except (FileNotFoundError, ValueError):
        pass

    try:
        wb_headers, _ = load_reference_headers("Workbench", template)
        workbench_pct = validate_template(uploaded_headers, wb_headers)["match_percentage"]
    except (FileNotFoundError, ValueError):
        pass

    if dit_pct >= 50 and workbench_pct >= 50:
        style = "Mixed"
    elif dit_pct >= workbench_pct + 10:
        style = "Data Import Tool"
    elif workbench_pct >= dit_pct + 10:
        style = "Workbench"
    elif dit_pct >= 50:
        style = "Data Import Tool"
    elif workbench_pct >= 50:
        style = "Workbench"
    else:
        style = "Unknown"

    return {
        "style": style,
        "dit_match_percentage": dit_pct,
        "workbench_match_percentage": workbench_pct,
    }


def build_correction_plan(
    original_df: pd.DataFrame,
    uploaded_headers: list[str],
    upload_method: str,
    template: str,
    load_operation: str | None = None,
    comparison_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a structured correction plan for the selected target upload tool."""
    context = resolve_template(template)
    file_style = detect_file_style(uploaded_headers, template)

    if comparison_result is None:
        comparison_result = compare_to_reference(
            uploaded_headers,
            upload_method,
            template,
            load_operation,
        )

    comparison = comparison_result["comparison"]
    analysis = comparison.get("header_analysis")
    if analysis is None:
        expected_headers, _ = _target_headers(upload_method, template, comparison_result)
        analysis = analyze_header_matching(
            uploaded_headers,
            expected_headers,
            upload_method,
            context,
            load_operation,
        )
        comparison = enrich_template_comparison(comparison, analysis)
        comparison_result = {**comparison_result, "comparison": comparison}

    target_headers, _ = _target_headers(upload_method, template, comparison_result)
    changes: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def add_change(change: dict[str, Any]) -> None:
        if change["change_id"] in seen_ids:
            return
        seen_ids.add(change["change_id"])
        changes.append(change)

    for rename in comparison.get("proposed_renames", []):
        if upload_method == "Workbench" and rename["target_column"] == "Id" and load_operation != "Update":
            continue
        add_change(_rename_change_from_match(rename, upload_method))

    for manual in comparison.get("manual_mapping_required", []):
        add_change(_manual_mapping_change(manual))

    for generated in comparison.get("generated_fields", []):
        add_change(_generated_value_change(
            generated["field"],
            generated["value"],
            REQUIREDNESS["COPILOT"],
        ))

    for optional_target in comparison.get("optional_missing_columns", []):
        add_change(_empty_optional_change(optional_target))

    for required_target in comparison.get("missing_columns", []):
        add_change(_required_missing_change(
            required_target,
            f"Required field '{required_target}' has no matching source column in the upload.",
            REQUIREDNESS["BUSINESS"],
        ))

    for extra in comparison.get("extra_columns", []):
        add_change(_exclude_change(extra))

    if comparison.get("order_differences") and target_headers:
        projected_headers = _project_headers_after_changes(
            uploaded_headers,
            changes,
            target_headers,
        )
        ordered = [header for header in target_headers if header in projected_headers]
        for header in projected_headers:
            if header not in ordered:
                ordered.append(header)
        add_change(_reorder_change(ordered, target_headers))

    manual_review = [
        change for change in changes
        if change["category"] in {"required_data_missing", "manual_mapping_required"}
    ]
    safe_changes = [change for change in changes if change.get("safe")]
    confirmation_changes = [
        change for change in changes
        if change.get("requires_confirmation") and not change.get("safe")
    ]

    summary = _build_summary(changes, manual_review)

    return {
        "upload_method": upload_method,
        "template": template,
        "load_operation": load_operation,
        "file_style": file_style,
        "comparison_result": comparison_result,
        "target_headers": target_headers,
        "changes": changes,
        "safe_changes": safe_changes,
        "confirmation_changes": confirmation_changes,
        "manual_review": manual_review,
        "proposed_renames": comparison.get("proposed_renames", []),
        "conditional_fields": comparison.get("conditional_fields", []),
        "generated_fields": comparison.get("generated_fields", []),
        "summary": summary,
        "has_fixable_changes": bool(safe_changes or confirmation_changes),
        "has_blocking_manual_review": bool(manual_review),
        "corrections_applied": False,
        "corrections_declined": False,
    }


def get_fixable_change_ids(plan: dict[str, Any]) -> set[str]:
    return {
        change["change_id"]
        for change in plan.get("changes", [])
        if change.get("safe") or change.get("requires_confirmation")
    }


def get_safe_change_ids(plan: dict[str, Any]) -> set[str]:
    return {change["change_id"] for change in plan.get("safe_changes", [])}


def get_header_rename_change_ids(plan: dict[str, Any]) -> set[str]:
    return {
        change["change_id"]
        for change in plan.get("changes", [])
        if change.get("category") == "rename"
    }


def get_reorder_change_ids(plan: dict[str, Any]) -> set[str]:
    return {
        change["change_id"]
        for change in plan.get("changes", [])
        if change.get("category") == "reorder_columns"
    }


def summarize_plan(plan: dict[str, Any]) -> dict[str, int]:
    return dict(plan.get("summary", {}))


def _target_headers(
    upload_method: str,
    template: str,
    comparison_result: dict[str, Any],
) -> tuple[list[str], list[str]]:
    try:
        headers, _ = load_reference_headers(upload_method, template)
        return headers, headers
    except (FileNotFoundError, ValueError):
        comparison = comparison_result["comparison"]
        matching = comparison.get("matching_headers", [])
        missing = comparison.get("missing_columns", [])
        optional = comparison.get("optional_missing_columns", [])
        renames = [item["target_column"] for item in comparison.get("proposed_renames", [])]
        return matching + missing + optional + renames, matching + missing + optional + renames


def _rename_change_from_match(rename: dict[str, Any], upload_method: str) -> dict[str, Any]:
    target_label = "API field" if upload_method == "Workbench" else "DIT header"
    return {
        "change_id": f"rename:{rename['source_column']}->{rename['target_column']}",
        "category": "rename",
        "title": CORRECTION_CATEGORIES["rename"],
        "description": rename.get(
            "description",
            f"Rename `{rename['source_column']}` → `{rename['target_column']}`",
        ),
        "source_column": rename["source_column"],
        "target_column": rename["target_column"],
        "match_type": rename.get("match_type"),
        "confidence": rename.get("confidence"),
        "safe": False,
        "requires_confirmation": True,
        "blocking": False,
        "requiredness": REQUIREDNESS["BUSINESS"],
        "target_label": target_label,
    }


def _manual_mapping_change(manual: dict[str, Any]) -> dict[str, Any]:
    target = manual.get("target_header") or "unknown"
    return {
        "change_id": f"manual:{target}",
        "category": "manual_mapping_required",
        "title": CORRECTION_CATEGORIES["manual_mapping_required"],
        "description": manual.get("description", "Manual mapping required."),
        "target_column": target,
        "possible_targets": manual.get("possible_targets", []),
        "possible_sources": manual.get("possible_sources", []),
        "safe": False,
        "requires_confirmation": False,
        "blocking": True,
        "requiredness": REQUIREDNESS["BUSINESS"],
    }


def _generated_value_change(
    target_column: str,
    generated_value: str,
    requiredness: str,
) -> dict[str, Any]:
    return {
        "change_id": f"generated:{target_column}",
        "category": "add_generated_value",
        "title": CORRECTION_CATEGORIES["add_generated_value"],
        "description": f"Add `{target_column}` with value `{generated_value}`",
        "target_column": target_column,
        "generated_value": generated_value,
        "safe": False,
        "requires_confirmation": True,
        "blocking": False,
        "requiredness": requiredness,
    }


def _empty_optional_change(
    target_column: str,
    target_label: str = "optional column",
) -> dict[str, Any]:
    return {
        "change_id": f"empty:{target_column}",
        "category": "add_empty_optional_column",
        "title": CORRECTION_CATEGORIES["add_empty_optional_column"],
        "description": f"Add empty {target_label} `{target_column}`",
        "target_column": target_column,
        "generated_value": "",
        "safe": False,
        "requires_confirmation": True,
        "blocking": False,
        "requiredness": REQUIREDNESS["OPTIONAL"],
    }


def _exclude_change(source_column: str) -> dict[str, Any]:
    return {
        "change_id": f"exclude:{source_column}",
        "category": "exclude_extra_column",
        "title": CORRECTION_CATEGORIES["exclude_extra_column"],
        "description": f"Exclude unsupported column `{source_column}`",
        "source_column": source_column,
        "safe": False,
        "requires_confirmation": True,
        "blocking": False,
        "requiredness": REQUIREDNESS["OPTIONAL"],
    }


def _reorder_change(
    projected_headers: list[str],
    target_headers: list[str],
) -> dict[str, Any]:
    ordered = [header for header in target_headers if header in projected_headers]
    for header in projected_headers:
        if header not in ordered:
            ordered.append(header)
    return {
        "change_id": "reorder:columns",
        "category": "reorder_columns",
        "title": CORRECTION_CATEGORIES["reorder_columns"],
        "description": f"Reorder {len(ordered)} columns into the target template order",
        "column_order": ordered,
        "safe": True,
        "requires_confirmation": False,
        "blocking": False,
        "requiredness": REQUIREDNESS["OPTIONAL"],
    }


def _required_missing_change(
    target_column: str,
    description: str,
    requiredness: str,
) -> dict[str, Any]:
    return {
        "change_id": f"missing:{target_column}",
        "category": "required_data_missing",
        "title": CORRECTION_CATEGORIES["required_data_missing"],
        "description": description,
        "target_column": target_column,
        "safe": False,
        "requires_confirmation": False,
        "blocking": True,
        "requiredness": requiredness,
    }


def _project_headers_after_changes(
    uploaded_headers: list[str],
    changes: list[dict[str, Any]],
    target_headers: list[str],
) -> list[str]:
    headers = list(uploaded_headers)
    for change in changes:
        category = change["category"]
        if category == "rename":
            headers = [
                change["target_column"] if header == change["source_column"] else header
                for header in headers
            ]
        elif category == "exclude_extra_column":
            headers = [header for header in headers if header != change["source_column"]]
        elif category == "add_generated_value":
            if change["target_column"] not in headers:
                headers.append(change["target_column"])
        elif category == "add_empty_optional_column":
            if change["target_column"] not in headers:
                headers.append(change["target_column"])

    ordered = [header for header in target_headers if header in headers]
    for header in headers:
        if header not in ordered:
            ordered.append(header)
    return ordered


def _build_summary(
    changes: list[dict[str, Any]],
    manual_review: list[dict[str, Any]],
) -> dict[str, int]:
    summary = {
        "rename": 0,
        "reorder_columns": 0,
        "add_generated_value": 0,
        "convert_dates": 0,
        "add_empty_optional_column": 0,
        "exclude_extra_column": 0,
        "remove_blank_rows": 0,
        "manual_review": len(manual_review),
    }
    for change in changes:
        category = change["category"]
        if category in summary:
            summary[category] += 1
    return summary
