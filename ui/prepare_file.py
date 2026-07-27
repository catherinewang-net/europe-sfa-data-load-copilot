"""Header Review UI for Data Import Tool correction plans."""

from __future__ import annotations

import streamlit as st

from core.config import CORRECTION_CATEGORIES
from services.correction_plan_service import get_reorder_change_ids
from services.dit_ux_service import (
    HEADER_ACTION_EXCLUDE,
    HEADER_ACTION_RENAME,
    SESSION_HEADER_DECISIONS,
    SESSION_OPTIONAL_EXCLUSIONS,
    approve_all_high_confidence_headers,
    build_dit_header_review_rows,
    build_structure_change_lines,
    exclude_all_optional_unmapped,
    resolve_header_decisions_to_change_ids,
    resolve_template_context,
)
from ui.preparation_action_cards import (
    format_header_order_details,
    format_structure_change_details,
    render_action_card,
    render_technical_details_expander,
)


def _sync_header_decisions(rows: list[dict]) -> dict[str, str]:
    stored = dict(st.session_state.get(SESSION_HEADER_DECISIONS) or {})
    for row in rows:
        key = row["uploaded_header"] if row["uploaded_header"] != "—" else row["target_header"]
        stored.setdefault(key, row.get("default_action"))
    st.session_state[SESSION_HEADER_DECISIONS] = stored
    return stored


def _sync_optional_exclusions(rows: list[dict], decisions: dict[str, str]) -> set[str]:
    exclusions = set(st.session_state.get(SESSION_OPTIONAL_EXCLUSIONS) or [])
    for row in rows:
        if row.get("required"):
            continue
        key = row["uploaded_header"] if row["uploaded_header"] != "—" else row["target_header"]
        if decisions.get(key) == HEADER_ACTION_EXCLUDE:
            exclusions.add(key)
        elif key in exclusions and decisions.get(key) != HEADER_ACTION_EXCLUDE:
            exclusions.discard(key)
    st.session_state[SESSION_OPTIONAL_EXCLUSIONS] = sorted(exclusions)
    return exclusions


def _comparison_from_plan(correction_plan: dict) -> dict:
    return (
        correction_plan.get("comparison_result", {}).get("comparison", {})
        or {}
    )


def render_prepare_file(correction_plan: dict) -> dict[str, set[str]] | None:
    """
    Display the Template Structure UI and return approved change IDs.

    Returns:
        {"enabled_change_ids": set[str], "declined": bool}
        None while waiting for user action
    """
    st.subheader("Header Review")
    st.caption(
        "Review how uploaded headers compare to the selected Data Import Tool template. "
        "Your original upload is never modified."
    )

    template = correction_plan.get("template", "")
    template_context = resolve_template_context(template)
    optional_exclusions = set(st.session_state.get(SESSION_OPTIONAL_EXCLUSIONS) or [])

    file_style = correction_plan.get("file_style", {})
    template_meta = (
        f"**Detected file style:** {file_style.get('style', 'Unknown')}  \n"
        f"**Target tool:** {correction_plan.get('upload_method')}  \n"
        f"**Template:** {template}"
    )

    header_rows = build_dit_header_review_rows(
        correction_plan,
        template_context,
        optional_exclusions,
    )
    decisions = _sync_header_decisions(header_rows)

    summary = correction_plan.get("summary", {})
    comparison = _comparison_from_plan(correction_plan)
    order_differences = comparison.get("order_differences", [])
    reorder_count = summary.get("reorder_columns", 0)
    structure_lines = build_structure_change_lines(summary, template)
    header_order_applied = bool(st.session_state.get("header_order_formatted"))

    if reorder_count or order_differences:
        structure_details_parts = []
        if order_differences:
            structure_details_parts.append(format_header_order_details(order_differences))
        if structure_lines:
            structure_details_parts.append(format_structure_change_details(structure_lines))
        structure_details = "\n\n".join(structure_details_parts) if structure_details_parts else None

        if render_action_card(
            "🗂️ Template Structure",
            "The uploaded columns do not match the selected template order.",
            "✓ Format Header Order",
            key="prepare_format_header_order",
            details=structure_details,
            applied=header_order_applied,
            success_message="✅ Header order matches the selected template.",
        ):
            enabled_ids = get_reorder_change_ids(correction_plan)
            enabled_ids.update(
                resolve_header_decisions_to_change_ids(
                    correction_plan,
                    decisions,
                    optional_exclusions,
                )
            )
            st.session_state["header_order_formatted"] = True
            return {"enabled_change_ids": enabled_ids, "declined": False}

    if header_rows:
        def _render_header_mapping_table() -> None:
            st.markdown(template_meta)
            header_cols = st.columns([1.5, 1.5, 0.8, 0.8, 1.4, 1.2, 0.9])
            header_cols[0].markdown("**Uploaded Header**")
            header_cols[1].markdown("**Target Header**")
            header_cols[2].markdown("**Required/Optional**")
            header_cols[3].markdown("**Match Confidence**")
            header_cols[4].markdown("**Reason**")
            header_cols[5].markdown("**Action**")
            header_cols[6].markdown("**Status**")

            for row in header_rows:
                key = row["uploaded_header"] if row["uploaded_header"] != "—" else row["target_header"]
                cols = st.columns([1.5, 1.5, 0.8, 0.8, 1.4, 1.2, 0.9])
                cols[0].markdown(f"`{row['uploaded_header']}`")
                cols[1].markdown(
                    f"`{row['target_header']}`" if row["target_header"] != "—" else "—"
                )
                badge = row["requiredness"]
                badge_color = "#b91c1c" if badge == "Required" else "#64748b"
                cols[2].markdown(
                    f'<span style="background:{badge_color};color:white;padding:2px 8px;'
                    f'border-radius:4px;font-size:0.75rem;">{badge}</span>',
                    unsafe_allow_html=True,
                )
                cols[3].markdown(str(row["confidence"]))
                cols[4].markdown(row["reason"])

                action_options = row["actions"]
                current_action = decisions.get(key, row.get("default_action"))
                if current_action not in action_options:
                    current_action = action_options[0]
                selected_action = cols[5].radio(
                    "Action",
                    options=action_options,
                    index=action_options.index(current_action),
                    key=f"dit_header_action_{key}",
                    label_visibility="collapsed",
                )
                if selected_action != decisions.get(key):
                    decisions[key] = selected_action
                    st.session_state[SESSION_HEADER_DECISIONS] = decisions
                    _sync_optional_exclusions(header_rows, decisions)

                status = row["status"]
                if selected_action == HEADER_ACTION_EXCLUDE:
                    status = "Excluded"
                elif selected_action == HEADER_ACTION_RENAME:
                    status = "Suggested"
                cols[6].markdown(status)

        render_technical_details_expander(render_fn=_render_header_mapping_table)
    else:
        render_technical_details_expander(content=template_meta)

    optional_exclusions = _sync_optional_exclusions(header_rows, decisions)

    manual_count = summary.get("manual_review", 0)

    if manual_count:
        def _render_manual_header_review() -> None:
            for item in correction_plan.get("manual_review", []):
                st.markdown(f"- {item.get('description', item.get('title', 'Manual review item'))}")

        render_technical_details_expander(render_fn=_render_manual_header_review)

    changes = [
        change for change in correction_plan.get("changes", [])
        if change.get("safe") or change.get("requires_confirmation")
    ]
    if not changes and not manual_count:
        if st.button("Continue to Data Validation", type="primary", key="prepare_continue_none"):
            return {"enabled_change_ids": set(), "declined": False}
        return None

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        approve_renames = st.button(
            "Approve All High-Confidence Header Changes",
            type="primary",
            key="prepare_approve_renames",
        )
    with col2:
        exclude_unmapped = st.button("Exclude All Unmapped Columns", key="prepare_exclude_unmapped")
    with col3:
        review_individual = st.button("Review Individually", key="prepare_review_individual")
    with col4:
        skip = st.button("Skip Data Changes", key="prepare_skip")

    if skip:
        st.session_state.pop("prepare_individual_mode", None)
        st.session_state.pop("header_order_formatted", None)
        return {"enabled_change_ids": set(), "declined": True}

    if approve_renames:
        st.session_state.pop("prepare_individual_mode", None)
        st.session_state.pop("header_order_formatted", None)
        return {"enabled_change_ids": approve_all_high_confidence_headers(correction_plan), "declined": False}

    if exclude_unmapped:
        st.session_state.pop("prepare_individual_mode", None)
        st.session_state.pop("header_order_formatted", None)
        return {
            "enabled_change_ids": exclude_all_optional_unmapped(correction_plan, template_context),
            "declined": False,
        }

    if review_individual:
        st.session_state["prepare_individual_mode"] = True

    if st.session_state.get("prepare_individual_mode"):
        st.markdown("**Select header changes to apply:**")
        selected_ids: set[str] = set()
        for change in changes:
            category_label = CORRECTION_CATEGORIES.get(change["category"], change["category"])
            default = change.get("safe", False) or change.get("category") == "rename"
            label = change.get("description", change.get("title"))
            if change.get("category") == "rename":
                label = f"{change['source_column']} → {change['target_column']}"
            if st.checkbox(
                f"{category_label}: {label}",
                value=default,
                key=f"prepare_change_{change['change_id']}",
            ):
                selected_ids.add(change["change_id"])

        if st.button("Continue to Data Validation", type="primary", key="prepare_apply_selected"):
            st.session_state.pop("prepare_individual_mode", None)
            st.session_state.pop("header_order_formatted", None)
            return {"enabled_change_ids": selected_ids, "declined": False}

    enabled_from_rows = resolve_header_decisions_to_change_ids(
        correction_plan,
        decisions,
        optional_exclusions,
    )
    if enabled_from_rows and st.button(
        "Continue to Data Validation",
        type="primary",
        key="prepare_continue_decisions",
    ):
        st.session_state.pop("header_order_formatted", None)
        return {"enabled_change_ids": enabled_from_rows, "declined": False}

    return None
