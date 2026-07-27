"""Numeric and decimal format validation."""

from __future__ import annotations

import re
from typing import Any

from validators.common import (
    IDENTIFIER_FIELD_MARKERS,
    PHONE_FIELD_MARKERS,
    build_issue,
    field_matches_markers,
    is_blank,
    normalize_text,
)

EUROPEAN_DECIMAL_RE = re.compile(r"^\d{1,3}(?:\.\d{3})*,\d+$")
COMMA_DECIMAL_RE = re.compile(r"^\d+,\d+$")
US_THOUSANDS_DECIMAL_RE = re.compile(r"^\d{1,3}(?:,\d{3})+\.\d+$")
THOUSANDS_ONLY_RE = re.compile(r"^\d{1,3}(?:,\d{3})+$")


def validate_numeric_fields(
    df,
    numeric_fields: list[str],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    for field in numeric_fields:
        if field not in df.columns:
            continue
        for idx, raw_value in df[field].items():
            if is_blank(raw_value):
                continue
            text = normalize_text(raw_value)
            row_number = idx + 2

            converted = _propose_numeric_conversion(text)
            if converted is not None and converted != text:
                issues.append(build_issue(
                    issue_id=f"numeric:convert:{field}:{row_number}",
                    category="numeric",
                    field=field,
                    row=row_number,
                    original_value=text,
                    proposed_value=converted,
                    reason="Convert numeric value to Salesforce dot-decimal format without thousands separators.",
                    safe=False,
                    requires_confirmation=True,
                    confidence=0.95,
                ))
                continue

            if EUROPEAN_DECIMAL_RE.match(text) or COMMA_DECIMAL_RE.match(text):
                issues.append(build_issue(
                    issue_id=f"numeric:decimal:{field}:{row_number}",
                    category="numeric",
                    field=field,
                    row=row_number,
                    original_value=text,
                    proposed_value=text,
                    reason="Numeric field uses a non-Salesforce decimal format (dot decimal, no thousands separators).",
                    safe=False,
                    blocking=True,
                ))
                continue

            if "," in text and re.search(r"\d,\d{3}", text):
                issues.append(build_issue(
                    issue_id=f"numeric:thousands:{field}:{row_number}",
                    category="numeric",
                    field=field,
                    row=row_number,
                    original_value=text,
                    proposed_value=text,
                    reason="Numeric field contains thousands separators.",
                    safe=False,
                    blocking=True,
                ))

    return issues


def resolve_numeric_fields(columns: list[str], object_fields: dict[str, Any] | None = None) -> list[str]:
    numeric_types = {"double", "currency", "percent", "int"}
    fields: list[str] = []
    for column in columns:
        api_name = column
        metadata = object_fields.get(api_name) if object_fields else None
        if metadata and getattr(metadata, "field_type", "").lower() in numeric_types:
            if _is_excluded_numeric_column(column, api_name):
                continue
            fields.append(column)
    return fields


def _propose_numeric_conversion(text: str) -> str | None:
    if EUROPEAN_DECIMAL_RE.match(text):
        return text.replace(".", "").replace(",", ".")
    if COMMA_DECIMAL_RE.match(text):
        return text.replace(",", ".")
    if US_THOUSANDS_DECIMAL_RE.match(text):
        return text.replace(",", "")
    if THOUSANDS_ONLY_RE.match(text):
        return text.replace(",", "")
    return None


def _is_excluded_numeric_column(column: str, api_name: str) -> bool:
    markers = IDENTIFIER_FIELD_MARKERS + PHONE_FIELD_MARKERS + ("postal", "post code", "zip", "ean", "sku")
    return field_matches_markers(column, markers) or field_matches_markers(api_name, markers)
