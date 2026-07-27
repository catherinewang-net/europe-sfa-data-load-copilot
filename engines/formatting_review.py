"""Formatting issue detection — delegates to unified row correction validators."""

from __future__ import annotations

from typing import Any

import pandas as pd

from validators.blank_row_validator import validate_blank_rows
from validators.whitespace_validator import validate_whitespace

FORMATTING_CATEGORIES = {
    "trim_whitespace": "Leading/trailing spaces",
    "remove_blank_rows": "Completely blank rows",
}

SAFE_FORMATTING_CATEGORIES = {
    "trim_whitespace",
    "remove_blank_rows",
}


def detect_formatting_issues(
    df: pd.DataFrame,
    template_config: dict[str, Any],
    confirmed_rename_map: dict[str, str],
    excluded_columns: set[str],
    raw_csv_content: str | None = None,
) -> dict[str, Any]:
    """
    Compatibility wrapper for legacy formatting review callers.

    Detection is delegated to the unified row correction validators.
    """
    del template_config, confirmed_rename_map, raw_csv_content
    working_columns = [col for col in df.columns if col not in excluded_columns]
    flat_issues = validate_whitespace(df, working_columns)
    flat_issues.extend(validate_blank_rows(df))

    grouped = _group_issues(flat_issues)
    summary = {key: 0 for key in FORMATTING_CATEGORIES}
    for issue in grouped:
        category = _legacy_category(issue["category"])
        if category in summary:
            summary[category] += issue["affected_row_count"]

    return {
        "issues": grouped,
        "summary": summary,
        "total_issue_groups": len(grouped),
        "has_safe_fixes": any(issue.get("safe") for issue in grouped),
    }


def apply_formatting_fixes(
    df: pd.DataFrame,
    enabled_categories: set[str],
    template_config: dict[str, Any],
    confirmed_rename_map: dict[str, str],
    excluded_columns: set[str],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Deprecated — use services.row_correction_plan_service.apply_row_corrections."""
    del template_config, confirmed_rename_map, excluded_columns
    from services.row_correction_plan_service import apply_row_corrections, build_row_correction_plan

    plan = build_row_correction_plan(df, "Workbench", "")
    enabled_issue_ids = {
        issue["issue_id"]
        for issue in plan.get("issues", [])
        if issue.get("safe") and _legacy_category(issue["category"]) in enabled_categories
    }
    return apply_row_corrections(df, plan, enabled_issue_ids)


def apply_selected_formatting_issues(
    df: pd.DataFrame,
    issues: list[dict[str, Any]],
    enabled_issue_ids: set[str],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Deprecated — use services.row_correction_plan_service.apply_row_corrections."""
    del issues
    from services.row_correction_plan_service import apply_row_corrections, build_row_correction_plan

    plan = build_row_correction_plan(df, "Workbench", "")
    return apply_row_corrections(df, plan, enabled_issue_ids)


def get_manual_review_from_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    manual_review: list[dict[str, Any]] = []
    for issue in issues:
        if issue.get("safe"):
            continue
        for detail in issue.get("details", []):
            manual_review.append({
                "row": detail.get("row"),
                "field": issue.get("field"),
                "value": detail.get("original_value", ""),
                "reason": issue.get("reason", "Requires manual review"),
            })
    return manual_review


def _legacy_category(category: str) -> str:
    if category == "whitespace":
        return "trim_whitespace"
    if category == "blank_rows":
        return "remove_blank_rows"
    return category


def _group_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str | None], dict[str, Any]] = {}

    for issue in issues:
        category = _legacy_category(issue["category"])
        key = (category, issue.get("field"))
        if key not in grouped:
            grouped[key] = {
                "issue_id": f"{category}:{issue.get('field') or 'all'}",
                "category": category,
                "field": issue.get("field"),
                "affected_row_count": 0,
                "original_example": issue.get("original_value", ""),
                "proposed_correction": issue.get("proposed_value", ""),
                "reason": issue.get("reason", ""),
                "safe": issue.get("safe", True),
                "details": [],
            }

        entry = grouped[key]
        entry["affected_row_count"] += 1
        entry["details"].append({
            "row": issue.get("row"),
            "original_value": issue.get("original_value"),
            "new_value": issue.get("proposed_value"),
        })

    return list(grouped.values())
