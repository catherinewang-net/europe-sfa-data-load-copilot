"""Phone number validation and safe formatting fixes."""

from __future__ import annotations

import re
from typing import Any

from validators.common import (
    DECIMAL_SUFFIX_RE,
    PHONE_FIELD_MARKERS,
    SCIENTIFIC_NOTATION_RE,
    build_issue,
    field_matches_markers,
    is_blank,
    normalize_text,
)


def validate_phones(df, phone_fields: list[str]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    for field in phone_fields:
        if field not in df.columns:
            continue
        for idx, raw_value in df[field].items():
            if is_blank(raw_value):
                continue
            text = normalize_text(raw_value)
            row_number = idx + 2

            if SCIENTIFIC_NOTATION_RE.match(text):
                issues.append(build_issue(
                    issue_id=f"phone:sci:{field}:{row_number}",
                    category="phones",
                    field=field,
                    row=row_number,
                    original_value=text,
                    proposed_value=text,
                    reason="Phone number contains scientific notation.",
                    safe=False,
                    blocking=True,
                ))
                continue

            if DECIMAL_SUFFIX_RE.match(text):
                corrected = text.split(".", 1)[0]
                issues.append(build_issue(
                    issue_id=f"phone:decimal:{field}:{row_number}",
                    category="phones",
                    field=field,
                    row=row_number,
                    original_value=text,
                    proposed_value=corrected,
                    reason="Remove accidental decimal suffix from phone number.",
                    safe=True,
                    confidence=0.95,
                ))
                continue

            if text != raw_value:
                issues.append(build_issue(
                    issue_id=f"phone:trim:{field}:{row_number}",
                    category="phones",
                    field=field,
                    row=row_number,
                    original_value=raw_value,
                    proposed_value=text,
                    reason="Trim leading/trailing whitespace from phone number.",
                    safe=True,
                    confidence=1.0,
                ))
                continue

            if re.search(r"[A-Za-z]", text):
                issues.append(build_issue(
                    issue_id=f"phone:alpha:{field}:{row_number}",
                    category="phones",
                    field=field,
                    row=row_number,
                    original_value=text,
                    proposed_value=text,
                    reason="Phone number contains letters.",
                    safe=False,
                    blocking=True,
                ))
                continue

            normalized_spaces = re.sub(r"\s{2,}", " ", text)
            if normalized_spaces != text:
                issues.append(build_issue(
                    issue_id=f"phone:spaces:{field}:{row_number}",
                    category="phones",
                    field=field,
                    row=row_number,
                    original_value=text,
                    proposed_value=normalized_spaces,
                    reason="Normalize repeated spaces in phone number.",
                    safe=True,
                    confidence=0.9,
                ))

    return issues


def resolve_phone_fields(
    columns: list[str],
    mapped_api_fields: dict[str, str] | None = None,
    object_fields: dict[str, Any] | None = None,
) -> list[str]:
    fields: list[str] = []
    for column in columns:
        api_name = (mapped_api_fields or {}).get(column, column)
        metadata = object_fields.get(api_name) if object_fields else None
        if metadata and getattr(metadata, "field_type", "").lower() == "phone":
            fields.append(column)
            continue
        if field_matches_markers(column, PHONE_FIELD_MARKERS):
            fields.append(column)
    return list(dict.fromkeys(fields))
