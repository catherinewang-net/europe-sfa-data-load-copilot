"""Workbench Preparation Plan UI."""

from __future__ import annotations

import streamlit as st

from core.config import CORRECTION_CATEGORIES
from services.workbench_preparation_service import (
    get_header_rename_change_ids,
    get_safe_change_ids,
)


def render_workbench_preparation_plan(preparation_plan: dict) -> dict[str, set[str]] | None:
    """
    Display the Workbench preparation plan and return approved change IDs.

    Returns:
        {"enabled_change_ids": set[str], "declined": bool}
        None while waiting for user action
    """
    st.subheader("Workbench Preparation Plan")
    st.caption(
        "Review the changes the Copilot can make after your field mappings are confirmed. "
        "Your original upload is never modified."
    )

    st.markdown(
        f"**Target tool:** Workbench  \n"
        f"**Template:** {preparation_plan.get('template')}  \n"
        f"**Load action:** {preparation_plan.get('load_operation')}"
    )

    summary = preparation_plan.get("summary", {})
    fixable_count = sum(summary.values())
    if fixable_count:
        st.markdown("**The Copilot can make these changes:**")
        _render_summary_lines(summary)
        for change in preparation_plan.get("changes", []):
            if change.get("category") == "rename":
                st.markdown(f"- Rename `{change['source_column']}` to `{change['target_column']}`")
            elif change.get("category") == "add_generated_value":
                st.markdown(f"- {change.get('description')}")
            elif change.get("category") == "convert_dates":
                st.markdown(f"- {change.get('description')}")
            elif change.get("category") == "remove_blank_rows":
                st.markdown(f"- {change.get('description')}")
            elif change.get("category") == "exclude_extra_column":
                st.markdown(f"- {change.get('description')}")
    else:
        st.info("No automatic structural changes were detected for this file.")

    changes = [
        change for change in preparation_plan.get("changes", [])
        if change.get("safe") or change.get("requires_confirmation")
    ]
    if not changes:
        if st.button("Continue", type="primary", key="workbench_prepare_continue_none"):
            return {"enabled_change_ids": set(), "declined": False}
        return None

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        approve_all = st.button("Approve All Changes", type="primary", key="workbench_prepare_all")
    with col2:
        apply_safe = st.button("Apply Safe Changes Only", key="workbench_prepare_safe")
    with col3:
        review_individual = st.button("Review Individually", key="workbench_prepare_individual")
    with col4:
        skip = st.button("Skip", key="workbench_prepare_skip")

    if skip:
        st.session_state.pop("workbench_prepare_individual_mode", None)
        return {"enabled_change_ids": set(), "declined": True}

    if approve_all:
        st.session_state.pop("workbench_prepare_individual_mode", None)
        enabled = {
            change["change_id"]
            for change in preparation_plan.get("changes", [])
            if change.get("safe") or change.get("requires_confirmation")
        }
        return {"enabled_change_ids": enabled, "declined": False}

    if apply_safe:
        st.session_state.pop("workbench_prepare_individual_mode", None)
        return {"enabled_change_ids": get_safe_change_ids(preparation_plan), "declined": False}

    if review_individual:
        st.session_state["workbench_prepare_individual_mode"] = True

    if st.session_state.get("workbench_prepare_individual_mode"):
        st.markdown("**Select changes to apply:**")
        selected_ids: set[str] = set()
        for change in changes:
            category_label = CORRECTION_CATEGORIES.get(change["category"], change["category"])
            label = change.get("description", change.get("title"))
            if change.get("category") == "rename":
                label = f"{change['source_column']} → {change['target_column']}"
            default = change.get("safe", False)
            if st.checkbox(
                f"{category_label}: {label}",
                value=default,
                key=f"workbench_prepare_change_{change['change_id']}",
            ):
                selected_ids.add(change["change_id"])

        if st.button("Apply Selected Changes", type="primary", key="workbench_prepare_apply_selected"):
            st.session_state.pop("workbench_prepare_individual_mode", None)
            return {"enabled_change_ids": selected_ids, "declined": False}

    return None


def _render_summary_lines(summary: dict[str, int]) -> None:
    labels = {
        "rename": "Rename columns to Salesforce API names",
        "reorder_columns": "Reorder columns",
        "add_generated_value": "Add generated values",
        "convert_dates": "Convert dates to YYYY-MM-DD",
        "remove_blank_rows": "Remove blank rows",
        "exclude_extra_column": "Exclude columns marked Do Not Include",
    }
    for key, label in labels.items():
        count = summary.get(key, 0)
        if count:
            st.markdown(f"- {label}: **{count}**")
