"""Formatting Review UI — display and approval only."""

from __future__ import annotations

import streamlit as st

from core.config import FORMATTING_CATEGORIES


def render_formatting_review(review: dict) -> dict[str, set[str]] | None:
    """
    Display Formatting Review and return approved formatting selections.

    Returns:
        {"enabled_issue_ids": set[str]} when user approves or skips
        None while waiting for user action
    """
    st.subheader("Formatting Review")
    st.caption(
        "Review detected formatting issues before generating the Workbench-ready CSV. "
        "The original upload is never modified."
    )

    issues = review.get("issues", [])
    if not issues:
        st.info("No formatting issues detected.")
        if st.button("Continue to Generate CSV", type="primary", key="fmt_continue_none"):
            return {"enabled_issue_ids": set()}
        return None

    st.markdown("**Detected issues**")
    for issue in issues:
        field_label = issue.get("field") or "(entire row)"
        safe_label = "Safe auto-fix" if issue.get("safe") else "Manual review only"
        category_label = FORMATTING_CATEGORIES.get(issue["category"], issue["category"])

        st.markdown(
            f"**{category_label}** — `{field_label}`  \n"
            f"Affected rows: **{issue['affected_row_count']:,}**  \n"
            f"Original example: `{issue['original_example']}`  \n"
            f"Proposed correction: `{issue['proposed_correction']}`  \n"
            f"Reason: {issue['reason']}  \n"
            f"Status: {safe_label}"
        )
        st.divider()

    col1, col2, col3 = st.columns(3)
    with col1:
        apply_all = st.button(
            "Apply All Safe Formatting Changes",
            type="primary",
            key="fmt_apply_all_safe",
        )
    with col2:
        review_individual = st.button("Review Individually", key="fmt_review_individual")
    with col3:
        skip = st.button("Skip Formatting Changes", key="fmt_skip")

    if skip:
        st.session_state.pop("formatting_review_individual_mode", None)
        return {"enabled_issue_ids": set()}

    if apply_all:
        st.session_state.pop("formatting_review_individual_mode", None)
        return {
            "enabled_issue_ids": {
                issue["issue_id"]
                for issue in issues
                if issue.get("safe")
            }
        }

    if review_individual:
        st.session_state["formatting_review_individual_mode"] = True

    if st.session_state.get("formatting_review_individual_mode"):
        st.markdown("**Select formatting changes to apply:**")
        selected_issue_ids: set[str] = set()

        for issue in issues:
            field_label = issue.get("field") or "entire row"
            category_label = FORMATTING_CATEGORIES.get(issue["category"], issue["category"])
            label = (
                f"{category_label} — `{field_label}` "
                f"({issue['affected_row_count']} affected rows)"
            )

            if not issue.get("safe"):
                st.checkbox(
                    f"{label} — manual review only, cannot auto-fix",
                    value=False,
                    disabled=True,
                    key=f"fmt_disabled_{issue['issue_id']}",
                )
                continue

            if st.checkbox(label, value=True, key=f"fmt_select_{issue['issue_id']}"):
                selected_issue_ids.add(issue["issue_id"])

        if st.button("Apply Selected Formatting Changes", type="primary", key="fmt_apply_selected"):
            st.session_state.pop("formatting_review_individual_mode", None)
            return {"enabled_issue_ids": selected_issue_ids}

    return None
