"""Data Quality Review UI for row-level corrections."""

from __future__ import annotations

import streamlit as st

from services.row_correction_plan_service import get_safe_issue_ids


def render_data_quality_review(plan: dict) -> dict[str, set[str]] | None:
    """Display row-level data quality issues and return approved issue IDs."""
    st.subheader("Data Quality Review")
    st.caption(
        "Review row-level data issues detected after header matching. "
        "Approved fixes are applied only to a corrected copy of your file."
    )

    summary = plan.get("summary", {})
    _render_summary(summary)

    manual_count = summary.get("manual_review", 0)
    if manual_count:
        st.markdown("**Manual review required:**")
        for issue in plan.get("manual_review", []):
            row_label = f"Row {issue['row']}: " if issue.get("row") else ""
            field_label = f"`{issue['field']}` " if issue.get("field") else ""
            st.markdown(f"- {row_label}{field_label}{issue.get('reason', 'Manual review required')}")

    fixable = [
        issue for issue in plan.get("issues", [])
        if issue.get("safe") or issue.get("requires_confirmation")
    ]
    if not fixable and not manual_count:
        if st.button("Continue", type="primary", key="dq_continue_none"):
            return {"enabled_issue_ids": set(), "declined": False}
        return None

    col1, col2, col3 = st.columns(3)
    with col1:
        apply_safe = st.button("Apply All Safe Changes", type="primary", key="dq_apply_safe")
    with col2:
        review_individual = st.button("Review Changes Individually", key="dq_review_individual")
    with col3:
        skip = st.button("Skip Data Corrections", key="dq_skip")

    if skip:
        st.session_state.pop("data_quality_individual_mode", None)
        return {"enabled_issue_ids": set(), "declined": True}

    if apply_safe:
        st.session_state.pop("data_quality_individual_mode", None)
        return {"enabled_issue_ids": get_safe_issue_ids(plan), "declined": False}

    if review_individual:
        st.session_state["data_quality_individual_mode"] = True

    if st.session_state.get("data_quality_individual_mode"):
        st.markdown("**Select row corrections to apply:**")
        selected_ids: set[str] = set()
        for issue in fixable:
            default = issue.get("safe", False)
            row_label = f"Row {issue['row']}" if issue.get("row") else "File"
            field_label = issue.get("field") or "(structure)"
            label = (
                f"{row_label} `{field_label}`: "
                f"`{issue.get('original_value', '')}` -> `{issue.get('proposed_value', '')}`"
            )
            if st.checkbox(
                label,
                value=default,
                key=f"dq_issue_{issue['issue_id']}",
            ):
                selected_ids.add(issue["issue_id"])

        if st.button("Apply Selected Changes", type="primary", key="dq_apply_selected"):
            st.session_state.pop("data_quality_individual_mode", None)
            return {"enabled_issue_ids": selected_ids, "declined": False}

    return None


def _render_summary(summary: dict) -> None:
    dates = summary.get("dates", {})
    if any(dates.values()):
        st.markdown("**Dates**")
        if dates.get("convertible"):
            st.markdown(f"- {dates['convertible']} value(s) can be converted to the target format")
        if dates.get("ambiguous"):
            st.markdown(f"- {dates['ambiguous']} ambiguous date(s) require review")
        if dates.get("invalid"):
            st.markdown(f"- {dates['invalid']} invalid date value(s)")

    identifiers = summary.get("identifiers", {})
    if any(identifiers.values()):
        st.markdown("**Identifiers**")
        if identifiers.get("scientific_notation"):
            st.markdown(f"- {identifiers['scientific_notation']} value(s) contain scientific notation")
        if identifiers.get("leading_zeroes"):
            st.markdown(f"- {identifiers['leading_zeroes']} identifier format issue(s) detected")
        if identifiers.get("manual"):
            st.markdown(f"- {identifiers['manual']} identifier issue(s) require manual review")

    addresses = summary.get("addresses", {})
    if any(addresses.values()):
        st.markdown("**Addresses**")
        if addresses.get("whitespace"):
            st.markdown(f"- {addresses['whitespace']} address field(s) contain extra spaces or line breaks")

    phones = summary.get("phones", {})
    if phones.get("formatting"):
        st.markdown("**Phone numbers**")
        st.markdown(f"- {phones['formatting']} phone value(s) contain formatting issues")

    booleans = summary.get("booleans", {})
    if booleans.get("convertible"):
        st.markdown("**Booleans**")
        st.markdown(f"- {booleans['convertible']} value(s) can be converted to TRUE/FALSE")

    csv_structure = summary.get("csv_structure", {})
    if csv_structure.get("malformed_rows"):
        st.markdown("**CSV structure**")
        st.markdown(f"- {csv_structure['malformed_rows']} malformed row(s) detected")

    duplicates = summary.get("duplicates", {})
    if duplicates.get("duplicate_keys"):
        st.markdown("**Duplicate keys**")
        st.markdown(f"- {duplicates['duplicate_keys']} duplicate External ID issue(s)")
