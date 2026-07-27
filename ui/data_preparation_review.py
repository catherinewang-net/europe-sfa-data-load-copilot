"""Unified data preparation review UI after header mapping."""

from __future__ import annotations

import streamlit as st

from services.row_correction_plan_service import get_safe_issue_ids
from services.workbench_preparation_service import get_safe_change_ids
from ui.data_preparation_issues import render_data_preparation_issues
from ui.issue_editor import FIX_ISSUES_TITLE
from ui.preparation_action_cards import TECHNICAL_DETAILS_TITLE, render_technical_details_expander


def render_data_preparation_review(
    row_correction_plan: dict | None,
    workbench_plan: dict | None = None,
    mapping_rows: list[dict] | None = None,
    picklist_validation: dict | None = None,
    *,
    show_section_header: bool = True,
) -> dict[str, set[str] | bool] | None:
    """
    Display unified row-level and structural preparation review.

    Returns enabled row issue IDs, enabled workbench change IDs, and declined flag.
    """
    card_action = render_data_preparation_issues(
        row_correction_plan,
        show_section_header=show_section_header,
    )

    if card_action == "skip":
        st.session_state.pop("data_prep_individual_mode", None)
        return {"enabled_issue_ids": set(), "enabled_change_ids": set(), "declined": True}

    if card_action == "apply_all":
        st.session_state.pop("data_prep_individual_mode", None)
        row_plan = row_correction_plan or {"issues": []}
        return {
            "enabled_issue_ids": get_safe_issue_ids(row_plan) if row_plan else set(),
            "enabled_change_ids": get_safe_change_ids(workbench_plan) if workbench_plan else set(),
            "declined": False,
        }

    if card_action == "review_individual":
        st.session_state["data_prep_individual_mode"] = True

    row_plan = row_correction_plan or {"issues": [], "manual_review": [], "summary": {}}
    manual_items = list(row_plan.get("manual_review", []))
    if workbench_plan:
        manual_items.extend(workbench_plan.get("manual_review", []))

    if manual_items and not st.session_state.get("data_prep_individual_mode"):
        def _render_manual_review() -> None:
            for issue in manual_items:
                row_label = f"Row {issue['row']}: " if issue.get("row") else ""
                field_label = f"`{issue.get('field')}` " if issue.get("field") else ""
                reason = issue.get("reason") or issue.get("description") or "Manual review required"
                st.markdown(f"- {row_label}{field_label}{reason}")
            st.caption("Use the Fix Issues in Copilot section after preparation to correct unresolved values.")

        render_technical_details_expander(
            render_fn=_render_manual_review,
            title=FIX_ISSUES_TITLE,
        )

    row_fixable = [
        issue for issue in row_plan.get("issues", [])
        if issue.get("safe") or issue.get("requires_confirmation")
    ]
    prep_changes = [
        change for change in (workbench_plan or {}).get("changes", [])
        if change.get("safe") or change.get("requires_confirmation")
    ]

    if not row_fixable and not prep_changes and not manual_items:
        if st.button("Continue", type="primary", key="data_prep_continue_none"):
            return {
                "enabled_issue_ids": set(),
                "enabled_change_ids": set(),
                "declined": False,
            }
        return None

    if st.session_state.get("data_prep_individual_mode"):
        selected_issue_ids: set[str] = set()
        selected_change_ids: set[str] = set()

        with st.expander(TECHNICAL_DETAILS_TITLE, expanded=False):
            if row_fixable:
                for issue in row_fixable:
                    row_label = f"Row {issue['row']}" if issue.get("row") else "File"
                    field_label = issue.get("field") or "(structure)"
                    label = (
                        f"{row_label} `{field_label}`: "
                        f"`{issue.get('original_value', '')}` -> `{issue.get('proposed_value', '')}`"
                    )
                    default_checked = issue.get("safe", False)
                    if st.checkbox(label, value=default_checked, key=f"data_prep_issue_{issue['issue_id']}"):
                        selected_issue_ids.add(issue["issue_id"])

            if prep_changes:
                for change in prep_changes:
                    label = change.get("description", change.get("title", change["change_id"]))
                    if st.checkbox(label, value=change.get("safe", False), key=f"data_prep_change_{change['change_id']}"):
                        selected_change_ids.add(change["change_id"])

        if st.button("Apply Selected Changes", type="primary", key="data_prep_apply_selected"):
            st.session_state.pop("data_prep_individual_mode", None)
            return {
                "enabled_issue_ids": selected_issue_ids,
                "enabled_change_ids": selected_change_ids,
                "declined": False,
            }

    return None
