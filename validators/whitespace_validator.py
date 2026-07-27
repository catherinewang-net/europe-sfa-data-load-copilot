"""General whitespace cleanup for retained text fields."""

from __future__ import annotations

from typing import Any

from validators.common import (
    IDENTIFIER_FIELD_MARKERS,
    PHONE_FIELD_MARKERS,
    ADDRESS_FIELD_MARKERS,
    build_issue,
    clean_text_whitespace,
    field_matches_markers,
    is_blank,
    is_whitespace_only,
    text_needs_whitespace_cleanup,
)

SKIP_METADATA_TYPES = {
    "double",
    "currency",
    "percent",
    "int",
    "date",
    "datetime",
    "boolean",
    "picklist",
    "multipicklist",
}


def validate_whitespace(
    df,
    whitespace_fields: list[str],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    for field in whitespace_fields:
        if field not in df.columns:
            continue
        for idx, raw_value in df[field].items():
            row_number = idx + 2

            if is_whitespace_only(raw_value):
                issues.append(build_issue(
                    issue_id=f"whitespace:blank-cell:{field}:{row_number}",
                    category="whitespace",
                    field=field,
                    row=row_number,
                    original_value=str(raw_value),
                    proposed_value="",
                    reason="Whitespace-only cell will be cleared.",
                    safe=True,
                    confidence=1.0,
                ))
                continue

            if is_blank(raw_value):
                continue

            if not text_needs_whitespace_cleanup(raw_value):
                continue

            original = str(raw_value)
            corrected = clean_text_whitespace(raw_value)
            issues.append(build_issue(
                issue_id=f"whitespace:cleanup:{field}:{row_number}",
                category="whitespace",
                field=field,
                row=row_number,
                original_value=original,
                proposed_value=corrected,
                reason="Normalize leading/trailing spaces, tabs, repeated spaces, and line breaks.",
                safe=True,
                confidence=1.0,
            ))

    return issues


def resolve_whitespace_fields(
    columns: list[str],
    mapped_api_fields: dict[str, str],
    object_fields: dict[str, Any] | None,
    *,
    phone_fields: list[str] | None = None,
    address_fields: list[str] | None = None,
    numeric_fields: list[str] | None = None,
    date_fields: list[str] | None = None,
    boolean_fields: list[str] | None = None,
) -> list[str]:
    """Resolve general text columns excluding specialized validator scopes."""
    phone_fields = set(phone_fields or [])
    address_fields = set(address_fields or [])
    numeric_fields = set(numeric_fields or [])
    date_fields = set(date_fields or [])
    boolean_fields = set(boolean_fields or [])

    resolved: list[str] = []
    for column in columns:
        if column in phone_fields or column in address_fields:
            continue
        if column in numeric_fields or column in date_fields or column in boolean_fields:
            continue

        api_name = mapped_api_fields.get(column, column)
        metadata = object_fields.get(api_name) if object_fields else None
        if metadata:
            field_type = getattr(metadata, "field_type", "").lower()
            if field_type in SKIP_METADATA_TYPES:
                continue

        if field_matches_markers(column, PHONE_FIELD_MARKERS):
            continue
        if field_matches_markers(column, ADDRESS_FIELD_MARKERS):
            continue
        if field_matches_markers(api_name, PHONE_FIELD_MARKERS):
            continue
        if field_matches_markers(api_name, ADDRESS_FIELD_MARKERS):
            continue
        if field_matches_markers(column, IDENTIFIER_FIELD_MARKERS):
            continue
        if field_matches_markers(api_name, IDENTIFIER_FIELD_MARKERS):
            continue

        resolved.append(column)

    return list(dict.fromkeys(resolved))
