"""Detect completely blank and whitespace-only rows."""

from __future__ import annotations

from typing import Any

from validators.common import build_issue, is_blank, is_whitespace_only


def is_row_blank(row) -> bool:
    for value in row:
        if is_blank(value):
            continue
        if is_whitespace_only(value):
            continue
        return False
    return True


def validate_blank_rows(df) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    for idx, row in df.iterrows():
        if not is_row_blank(row):
            continue
        row_number = idx + 2
        issues.append(build_issue(
            issue_id=f"blank_row:{row_number}",
            category="blank_rows",
            field=None,
            row=row_number,
            original_value="(entire row blank)",
            proposed_value="(row removed)",
            reason="Completely blank row will be removed.",
            safe=True,
            confidence=1.0,
        ))

    return issues
