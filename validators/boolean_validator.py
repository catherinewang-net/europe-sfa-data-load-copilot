"""Boolean field validation."""

from __future__ import annotations

from typing import Any

from validators.common import build_issue, is_blank, normalize_text

BOOLEAN_INPUT_MAP = {
    "yes": "TRUE",
    "no": "FALSE",
    "y": "TRUE",
    "n": "FALSE",
    "1": "TRUE",
    "0": "FALSE",
    "true": "TRUE",
    "false": "FALSE",
}


def validate_boolean_fields(df, boolean_fields: list[str]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    for field in boolean_fields:
        if field not in df.columns:
            continue
        for idx, raw_value in df[field].items():
            if is_blank(raw_value):
                continue
            text = normalize_text(raw_value)
            row_number = idx + 2
            normalized = text.upper()
            if normalized in {"TRUE", "FALSE"}:
                continue

            mapped = BOOLEAN_INPUT_MAP.get(text.lower())
            if mapped:
                issues.append(build_issue(
                    issue_id=f"boolean:{field}:{row_number}",
                    category="booleans",
                    field=field,
                    row=row_number,
                    original_value=text,
                    proposed_value=mapped,
                    reason=f"Convert `{text}` to Salesforce boolean `{mapped}`.",
                    safe=False,
                    requires_confirmation=True,
                    confidence=0.95,
                ))
                continue

            issues.append(build_issue(
                issue_id=f"boolean:invalid:{field}:{row_number}",
                category="booleans",
                field=field,
                row=row_number,
                original_value=text,
                proposed_value=text,
                reason="Boolean field must be TRUE or FALSE.",
                safe=False,
                blocking=True,
            ))

    return issues


def resolve_boolean_fields(columns: list[str], object_fields: dict[str, Any] | None = None) -> list[str]:
    fields: list[str] = []
    for column in columns:
        metadata = object_fields.get(column) if object_fields else None
        if metadata and getattr(metadata, "field_type", "").lower() in {"boolean", "checkbox"}:
            fields.append(column)
    return fields
