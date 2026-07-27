"""Identifier and External ID validation (scientific notation, decimal suffix).

Leading-zero correction is handled only by EAN and Federation ID validators.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.config import PROJECT_ROOT
from validators.common import (
    DECIMAL_SUFFIX_RE,
    PHONE_FIELD_MARKERS,
    SCIENTIFIC_NOTATION_RE,
    build_issue,
    field_matches_markers,
    is_blank,
    normalize_text,
)

RULES_PATH = PROJECT_ROOT / "rules" / "formatting_rules.json"

POSTAL_FIELD_MARKERS = (
    "postal",
    "post code",
    "zip",
    "postalcode",
    "billingpostalcode",
    "shippingpostalcode",
    "mailingpostalcode",
)

IDENTIFIER_RESOLUTION_EXCLUDED_MARKERS = POSTAL_FIELD_MARKERS + PHONE_FIELD_MARKERS + (
    "sku",
    "material id",
    "product id",
    "route id",
)


def load_identifier_rules() -> dict[str, Any]:
    if not RULES_PATH.exists():
        return {"leading_zero_fields": []}
    with open(RULES_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def validate_identifiers(
    df,
    identifier_fields: list[str],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    for field in identifier_fields:
        if field not in df.columns:
            continue
        for idx, raw_value in df[field].items():
            if is_blank(raw_value):
                continue
            text = normalize_text(raw_value)
            row_number = idx + 2

            if SCIENTIFIC_NOTATION_RE.match(text):
                issues.append(build_issue(
                    issue_id=f"identifier:sci:{field}:{row_number}",
                    category="identifiers",
                    field=field,
                    row=row_number,
                    original_value=text,
                    proposed_value=text,
                    reason="Identifier contains scientific notation and must remain text.",
                    safe=False,
                    blocking=True,
                    confidence=1.0,
                ))
                continue

            if DECIMAL_SUFFIX_RE.match(text):
                corrected = text.split(".", 1)[0]
                issues.append(build_issue(
                    issue_id=f"identifier:decimal:{field}:{row_number}",
                    category="identifiers",
                    field=field,
                    row=row_number,
                    original_value=text,
                    proposed_value=corrected,
                    reason="Remove accidental decimal suffix from identifier value.",
                    safe=True,
                    confidence=0.95,
                ))

    return issues


def resolve_identifier_fields(
    columns: list[str],
    mapped_api_fields: dict[str, str],
    object_fields: dict[str, Any] | None = None,
) -> list[str]:
    fields: list[str] = []
    for column in columns:
        api_name = mapped_api_fields.get(column, column)
        if _is_excluded_from_identifier_resolution(column, api_name):
            continue
        metadata = object_fields.get(api_name) if object_fields else None
        if metadata and getattr(metadata, "field_type", "").lower() in {"double", "int", "currency", "percent"}:
            continue
        if field_matches_markers(column, ("external", "gln", "ean", "federation", "user id", "cust_id")):
            fields.append(column)
        elif api_name.endswith("__c") and any(
            marker in api_name.lower() for marker in ("id", "code", "gln", "ean")
        ):
            fields.append(column)
        elif api_name in {"FederationIdentifier", "FederationId"}:
            fields.append(column)
    return list(dict.fromkeys(fields))


def _is_excluded_from_identifier_resolution(column: str, api_name: str) -> bool:
    return (
        field_matches_markers(column, IDENTIFIER_RESOLUTION_EXCLUDED_MARKERS)
        or field_matches_markers(api_name, IDENTIFIER_RESOLUTION_EXCLUDED_MARKERS)
    )
