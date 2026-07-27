"""Duplicate External ID and unique-key validation."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from validators.common import build_issue, is_blank, normalize_text


def validate_duplicate_keys(
    df,
    key_fields: list[str],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    for field in key_fields:
        if field not in df.columns:
            continue
        value_rows: dict[str, list[int]] = defaultdict(list)
        for idx, raw_value in df[field].items():
            if is_blank(raw_value):
                continue
            value_rows[normalize_text(raw_value)].append(idx + 2)

        for value, rows in value_rows.items():
            if len(rows) <= 1:
                continue
            issues.append(build_issue(
                issue_id=f"duplicate:{field}:{value}",
                category="duplicates",
                field=field,
                row=rows[0],
                original_value=value,
                proposed_value=value,
                reason=f"Duplicate value `{value}` appears on rows {', '.join(map(str, rows))}.",
                safe=False,
                blocking=True,
                confidence=1.0,
            ))

    return issues


def resolve_external_id_fields(
    columns: list[str],
    mapped_api_fields: dict[str, str],
    object_fields: dict[str, Any] | None = None,
) -> list[str]:
    fields: list[str] = []
    for column in columns:
        api_name = mapped_api_fields.get(column, column)
        metadata = object_fields.get(api_name) if object_fields else None
        if metadata and getattr(metadata, "is_external_id_field", False):
            fields.append(column)
            continue
        if metadata and getattr(metadata, "field_type", "").lower() == "externalid":
            fields.append(column)
            continue
        normalized = column.lstrip("*").lower()
        if "external id" in normalized or normalized.endswith("_id__c"):
            fields.append(column)
    return list(dict.fromkeys(fields))
