"""CSV export helpers for tool-ready and review downloads."""

from __future__ import annotations

from typing import Any

import pandas as pd

from services.constants import PICKLIST_STATUS_BLANK_REQUIRED

ISSUE_STATUS_COLUMN = "__Copilot_Status"
ISSUE_DETAIL_COLUMN = "__Copilot_Issue"

_PICKLIST_INVALID_STATUSES = {
    "Invalid Picklist Value",
    "Multipicklist Value Invalid",
    PICKLIST_STATUS_BLANK_REQUIRED,
    "Needs User Action",
}


def build_tool_ready_filename(base_name: str, upload_method: str | None = None) -> str:
    """Return tool-ready CSV filename for upload when all blocking issues are resolved."""
    del upload_method  # retained for call-site compatibility; filename no longer varies by tool
    return f"{base_name}_tool_ready.csv"


def build_review_filename(base_name: str) -> str:
    """Return review CSV filename with approved corrections (may still have unresolved issues)."""
    return f"{base_name}_review.csv"


def build_review_issue_examples(
    preparation_result: dict[str, Any] | None,
    validation_result: dict[str, Any] | None,
) -> list[str]:
    """Return human-readable blocking issue examples for the review download UI."""
    examples: list[str] = []
    prep = preparation_result or {}
    validation = validation_result or {}

    date_unresolved = prep.get("date_unresolved", [])
    if date_unresolved:
        count = len(date_unresolved)
        noun = "value" if count == 1 else "values"
        examples.append(f"- {count} unresolved date {noun}")

    picklist = validation.get("picklist_validation") or {}
    invalid_count = picklist.get("invalid_count", 0)
    if not invalid_count:
        invalid_count = sum(
            1
            for issue in picklist.get("issues", [])
            if issue.get("status") in _PICKLIST_INVALID_STATUSES
            and issue.get("status") != PICKLIST_STATUS_BLANK_REQUIRED
        )
    if invalid_count:
        noun = "value" if invalid_count == 1 else "values"
        examples.append(f"- {invalid_count} invalid picklist {noun}")

    blank_required = sum(
        1
        for issue in picklist.get("issues", [])
        if issue.get("status") == PICKLIST_STATUS_BLANK_REQUIRED
    )
    load_action = validation.get("load_action_validation") or {}
    blank_required += sum(
        1
        for issue in load_action.get("issues", [])
        if issue.get("severity") == "error"
        and issue.get("status") == PICKLIST_STATUS_BLANK_REQUIRED
    )
    if blank_required:
        noun = "field" if blank_required == 1 else "fields"
        examples.append(f"- {blank_required} required {noun} missing")

    manual_review = prep.get("manual_review", [])
    if manual_review and not examples:
        noun = "item" if len(manual_review) == 1 else "items"
        examples.append(f"- {len(manual_review)} manual review {noun}")

    return examples


def _collect_row_issues(
    preparation_result: dict[str, Any] | None,
    validation_result: dict[str, Any] | None,
) -> dict[int, list[str]]:
    row_issues: dict[int, list[str]] = {}

    def add(row: Any, message: str) -> None:
        if row is None or not message:
            return
        row_issues.setdefault(int(row), []).append(message)

    prep = preparation_result or {}
    for item in prep.get("date_unresolved", []):
        field = item.get("field") or item.get("column") or "date field"
        add(item.get("row"), f"Unresolved date in {field}")

    for item in prep.get("manual_review", []):
        add(
            item.get("row"),
            item.get("reason") or item.get("description") or "Manual review required",
        )

    validation = validation_result or {}
    picklist = validation.get("picklist_validation") or {}
    for item in picklist.get("issues", []):
        status = item.get("status", "Issue")
        field = item.get("field") or item.get("column") or "field"
        add(item.get("row"), f"{status}: {field}")

    load_action = validation.get("load_action_validation") or {}
    for item in load_action.get("issues", []):
        if item.get("severity") != "error":
            continue
        add(item.get("row"), item.get("message") or "Required field missing")

    return row_issues


def build_review_dataframe(
    corrected_df: pd.DataFrame,
    *,
    include_issue_notes: bool = False,
    preparation_result: dict[str, Any] | None = None,
    validation_result: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Build review CSV content from corrected data with optional issue columns."""
    review_df = corrected_df.copy()
    if not include_issue_notes:
        return review_df

    row_issues = _collect_row_issues(preparation_result, validation_result)
    statuses: list[str] = []
    issue_messages: list[str] = []
    for idx in range(len(review_df)):
        messages = row_issues.get(idx + 2, [])
        if messages:
            statuses.append("Issue")
            issue_messages.append("; ".join(messages))
        else:
            statuses.append("")
            issue_messages.append("")

    review_df[ISSUE_STATUS_COLUMN] = statuses
    review_df[ISSUE_DETAIL_COLUMN] = issue_messages
    return review_df
