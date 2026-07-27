"""Rank Salesforce API field candidates for uploaded Workbench column headers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from adapters.sfdx_metadata.models import FieldDefinition
from services.header_matching_service import load_header_aliases
from services.template_service import TemplateContext

CONFIDENCE_HIGH = "High"
CONFIDENCE_MEDIUM = "Medium"
CONFIDENCE_LOW = "Low"

MATCH_REASONS = {
    "exact_api": "Exact API field name match",
    "template_config": "Confirmed Template_Config mapping",
    "normalized_unique": "Exact normalized label match",
    "label_metadata": "Salesforce field label match",
    "alias": "Known header alias",
    "token_similarity": "Strong token similarity",
    "fuzzy": "Fuzzy similarity match",
}

TOKEN_SIMILARITY_THRESHOLD = 0.72
FUZZY_THRESHOLD = 0.86


@dataclass(frozen=True)
class FieldMatchCandidate:
    api_field: str
    field_label: str
    field_type: str
    match_type: str
    confidence: str
    reason: str
    score: float


def normalize_header_for_matching(header: str) -> str:
    """Normalize a header for comparison only — never use as output column name."""
    if not header:
        return ""

    text = header.strip()
    text = re.sub(r"^\*", "", text)
    text = re.sub(r"__c$|__r$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    text = text.lower()
    text = re.sub(r"[\s_\-]+", " ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = _singularize_tokens(text)
    text = text.replace(" ", "")
    return text


def tokenize_header(header: str) -> set[str]:
    """Split a header into comparison tokens."""
    text = header.strip()
    text = re.sub(r"^\*", "", text)
    text = re.sub(r"__c$|__r$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    text = text.lower()
    text = re.sub(r"[\s_\-]+", " ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    tokens = [token for token in text.split() if token]
    singularized = [_singularize_word(token) for token in tokens]
    return {token for token in singularized if token}


def rank_field_candidates(
    uploaded_header: str,
    object_fields: dict[str, FieldDefinition],
    template_context: TemplateContext | None = None,
    aliases: dict[str, str] | None = None,
) -> list[FieldMatchCandidate]:
    """Return ranked API-field candidates for one uploaded header."""
    aliases = aliases if aliases is not None else load_header_aliases()
    csv_to_api = _template_csv_to_api(template_context)
    candidates: list[FieldMatchCandidate] = []

    for api_name, field_def in object_fields.items():
        candidate = _evaluate_candidate(
            uploaded_header,
            api_name,
            field_def,
            csv_to_api,
            aliases,
        )
        if candidate:
            candidates.append(candidate)

    candidates = _dedupe_candidates(candidates)
    candidates.extend(_related_identifier_candidates(uploaded_header, object_fields, candidates))
    candidates.sort(key=lambda item: (-item.score, item.api_field))
    return _dedupe_candidates(candidates)


def select_best_candidate(
    candidates: list[FieldMatchCandidate],
    uploaded_header: str | None = None,
) -> tuple[FieldMatchCandidate | None, bool]:
    """
    Pick a suggested candidate when unambiguous.

    Returns (candidate, is_ambiguous).
    """
    if not candidates:
        return None, False

    if uploaded_header and _has_customer_id_ambiguity(uploaded_header, candidates):
        return None, True

    if _has_generic_token_ambiguity(candidates):
        return None, True

    top = candidates[0]
    tied = [
        candidate for candidate in candidates
        if candidate.score >= top.score - 0.01 and candidate.confidence == top.confidence
    ]
    if len(tied) > 1 and top.confidence != CONFIDENCE_HIGH:
        return None, True
    if len(tied) > 1 and top.match_type not in {"exact_api", "template_config", "normalized_unique", "label_metadata"}:
        return None, True
    return top, False


def _has_generic_token_ambiguity(candidates: list[FieldMatchCandidate]) -> bool:
    """Detect generic headers such as Status or Customer ID with multiple related fields."""
    status_like = [
        candidate for candidate in candidates
        if candidate.score >= 0.45 and "status" in candidate.api_field.lower()
    ]
    high_label_matches = [
        candidate for candidate in candidates
        if candidate.match_type == "label_metadata" and candidate.score >= 0.95
    ]
    if len(status_like) >= 2 and len(high_label_matches) <= 1:
        return True

    id_like = [
        candidate for candidate in candidates
        if candidate.score >= 0.45 and (
            candidate.api_field.endswith("_Id__c")
            or candidate.api_field.endswith("Id__c")
            or "id" in candidate.api_field.lower()
        )
    ]
    if len(id_like) >= 2:
        return True
    return False


def _has_customer_id_ambiguity(
    uploaded_header: str,
    candidates: list[FieldMatchCandidate],
) -> bool:
    uploaded_tokens = tokenize_header(uploaded_header)
    if not ({"customer", "id"} <= uploaded_tokens or uploaded_header.strip().lower() == "customer id"):
        return False
    id_related = [
        candidate for candidate in candidates
        if candidate.score >= 0.4 and (
            "id" in candidate.api_field.lower()
            or "id" in candidate.field_label.lower()
        )
    ]
    return len(id_related) >= 2


def _evaluate_candidate(
    uploaded_header: str,
    api_name: str,
    field_def: FieldDefinition,
    csv_to_api: dict[str, str],
    aliases: dict[str, str],
) -> FieldMatchCandidate | None:
    if uploaded_header == api_name:
        return _candidate(
            api_name,
            field_def,
            "exact_api",
            CONFIDENCE_HIGH,
            MATCH_REASONS["exact_api"],
            1.0,
        )

    template_target = csv_to_api.get(uploaded_header)
    if template_target == api_name:
        return _candidate(
            api_name,
            field_def,
            "template_config",
            CONFIDENCE_HIGH,
            MATCH_REASONS["template_config"],
            0.99,
        )

    uploaded_norm = normalize_header_for_matching(uploaded_header)
    api_norm = normalize_header_for_matching(api_name)
    label_norm = normalize_header_for_matching(field_def.label)

    if uploaded_norm and uploaded_norm == api_norm:
        return _candidate(
            api_name,
            field_def,
            "normalized_unique",
            CONFIDENCE_HIGH,
            MATCH_REASONS["normalized_unique"],
            0.98,
        )

    if uploaded_norm and uploaded_norm == label_norm:
        return _candidate(
            api_name,
            field_def,
            "label_metadata",
            CONFIDENCE_HIGH,
            MATCH_REASONS["label_metadata"],
            0.97,
        )

    alias_target = aliases.get(uploaded_header)
    if alias_target == api_name:
        return _candidate(
            api_name,
            field_def,
            "alias",
            CONFIDENCE_MEDIUM,
            MATCH_REASONS["alias"],
            0.94,
        )

    for alias_source, alias_api in aliases.items():
        if alias_api != api_name:
            continue
        if normalize_header_for_matching(alias_source) == uploaded_norm:
            return _candidate(
                api_name,
                field_def,
                "alias",
                CONFIDENCE_MEDIUM,
                MATCH_REASONS["alias"],
                0.93,
            )

    uploaded_tokens = tokenize_header(uploaded_header)
    label_tokens = tokenize_header(field_def.label)
    if uploaded_tokens and uploaded_tokens.issubset(label_tokens):
        subset_score = len(uploaded_tokens) / max(len(label_tokens), 1)
        if subset_score >= 0.45:
            return _candidate(
                api_name,
                field_def,
                "token_similarity",
                CONFIDENCE_LOW,
                MATCH_REASONS["token_similarity"],
                subset_score,
            )

    token_score = _token_similarity(uploaded_header, api_name, field_def.label)
    if token_score >= TOKEN_SIMILARITY_THRESHOLD:
        confidence = CONFIDENCE_MEDIUM if token_score >= 0.85 else CONFIDENCE_LOW
        return _candidate(
            api_name,
            field_def,
            "token_similarity",
            confidence,
            MATCH_REASONS["token_similarity"],
            token_score,
        )

    if uploaded_norm and api_norm:
        ratio = SequenceMatcher(None, uploaded_norm, api_norm).ratio()
        if ratio >= FUZZY_THRESHOLD:
            return _candidate(
                api_name,
                field_def,
                "fuzzy",
                CONFIDENCE_LOW,
                MATCH_REASONS["fuzzy"],
                ratio,
            )

    if uploaded_norm and label_norm:
        ratio = SequenceMatcher(None, uploaded_norm, label_norm).ratio()
        if ratio >= FUZZY_THRESHOLD:
            return _candidate(
                api_name,
                field_def,
                "fuzzy",
                CONFIDENCE_LOW,
                MATCH_REASONS["fuzzy"],
                ratio * 0.95,
            )

    return None


def _candidate(
    api_name: str,
    field_def: FieldDefinition,
    match_type: str,
    confidence: str,
    reason: str,
    score: float,
) -> FieldMatchCandidate:
    return FieldMatchCandidate(
        api_field=api_name,
        field_label=field_def.label,
        field_type=field_def.field_type,
        match_type=match_type,
        confidence=confidence,
        reason=reason,
        score=score,
    )


def _token_similarity(uploaded_header: str, api_name: str, field_label: str) -> float:
    uploaded_tokens = tokenize_header(uploaded_header)
    if not uploaded_tokens:
        return 0.0

    api_tokens = tokenize_header(api_name)
    label_tokens = tokenize_header(field_label)
    best = 0.0
    for target_tokens in (api_tokens, label_tokens):
        if not target_tokens:
            continue
        overlap = len(uploaded_tokens & target_tokens)
        if not overlap:
            continue
        union = len(uploaded_tokens | target_tokens)
        if union:
            best = max(best, overlap / union)
        if uploaded_tokens.issubset(target_tokens):
            best = max(best, overlap / max(len(target_tokens), 1))
    return best


def _template_csv_to_api(context: TemplateContext | None) -> dict[str, str]:
    if context and context.template_definition:
        return dict(context.template_definition.csv_label_to_api)
    if context and context.fallback_config:
        mappings = context.fallback_config.get("column_mappings", {})
        return {
            label: cfg["suggested_api_field"]
            for label, cfg in mappings.items()
            if cfg.get("suggested_api_field")
        }
    return {}


def _related_identifier_candidates(
    uploaded_header: str,
    object_fields: dict[str, FieldDefinition],
    existing: list[FieldMatchCandidate],
) -> list[FieldMatchCandidate]:
    uploaded_tokens = tokenize_header(uploaded_header)
    if not (
        {"customer", "id"} <= uploaded_tokens
        or normalize_header_for_matching(uploaded_header) in {"customerid", "custid"}
    ):
        return []

    existing_names = {candidate.api_field for candidate in existing}
    related: list[FieldMatchCandidate] = []
    for api_name, field_def in object_fields.items():
        if api_name in existing_names:
            continue
        if "id" not in api_name.lower() and "id" not in field_def.label.lower():
            continue
        related.append(_candidate(
            api_name,
            field_def,
            "token_similarity",
            CONFIDENCE_LOW,
            "Possible identifier field match",
            0.42,
        ))
    return related


def _dedupe_candidates(candidates: list[FieldMatchCandidate]) -> list[FieldMatchCandidate]:
    seen: set[str] = set()
    deduped: list[FieldMatchCandidate] = []
    for candidate in candidates:
        if candidate.api_field in seen:
            continue
        seen.add(candidate.api_field)
        deduped.append(candidate)
    return deduped


def _singularize_tokens(text: str) -> str:
    return " ".join(_singularize_word(token) for token in text.split())


def _singularize_word(word: str) -> str:
    if len(word) <= 3:
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word
