"""Grouped Data Preparation Issues UI."""

from __future__ import annotations

from typing import Any

import streamlit as st

from ui.preparation_action_cards import (
    ALL_CLEANUP_CATEGORIES,
    build_cleanup_category_summaries,
    count_fixable_issues,
    format_issue_details,
    render_data_cleanup_card,
)

ISSUE_GROUPS = (
    ("csv_structure", "CSV Structure"),
    ("addresses", "Address Fields"),
    ("eans", "EANs"),
    ("federation_ids", "User/Federation IDs"),
    ("punctuation", "Punctuation and Hidden Characters"),
    ("salesforce_record_check", "Salesforce Record Check"),
)


def group_preparation_issues(issues: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {key: [] for key, _label in ISSUE_GROUPS}
    for issue in issues:
        category = issue.get("category", "")
        if category in grouped:
            grouped[category].append(issue)
    return grouped


def render_data_preparation_issues(
    row_correction_plan: dict[str, Any] | None,
    *,
    show_section_header: bool = True,
) -> str | None:
    """
    Render grouped preparation issues as an action-first cleanup card.

    Returns ``apply_all``, ``review_individual``, ``skip``, or None.
    """
    plan = row_correction_plan or {"issues": []}
    issues = plan.get("issues", [])
    grouped = group_preparation_issues(issues)

    cleanup_count, _cleanup_rows = count_fixable_issues(plan, ALL_CLEANUP_CATEGORIES)
    individual_review_mode = bool(st.session_state.get("data_prep_individual_mode"))

    if not cleanup_count and not any(grouped.values()):
        if show_section_header:
            st.caption("No data cleanup or quality issues detected.")
        return None

    if show_section_header:
        st.subheader("Data Cleanup")

    if not cleanup_count:
        return None

    cleanup_issues = [
        issue for issue in issues
        if issue.get("category") in ALL_CLEANUP_CATEGORIES
        and (issue.get("safe") or issue.get("requires_confirmation"))
    ]
    category_summaries = build_cleanup_category_summaries(plan)
    cleanup_applied = bool(
        row_correction_plan
        and row_correction_plan.get("corrections_applied")
    )

    return render_data_cleanup_card(
        cleanup_count=cleanup_count,
        category_summaries=category_summaries,
        details=format_issue_details(cleanup_issues),
        applied=cleanup_applied,
        success_message="✅ Data cleanup applied successfully.",
        show_technical_details=not individual_review_mode,
        show_action_buttons=not cleanup_applied,
    )
