"""Salesforce Picklist Validation UI."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from services.dit_ux_service import (
    DEFAULT_PICKLIST_FILTERS,
    SESSION_PICKLIST_BULK,
    SESSION_PICKLIST_FILTER,
    SESSION_PICKLIST_REVIEW_EXPANDED_FIELD,
    advance_picklist_review_after_save,
    apply_bulk_picklist_decision,
    build_picklist_column_summary_lines,
    build_picklist_field_groups,
    build_picklist_review_button_label,
    build_picklist_review_rows,
    build_picklist_status_summary,
    count_reviewable_picklist_corrections,
    filter_picklist_issues,
    group_repeated_whitespace_trims,
    picklist_review_row_index_key,
    resolve_picklist_review_row_index,
    set_picklist_review_expanded_field,
)
from services.picklist_correction_service import (
    apply_picklist_corrections,
    build_picklist_correction_plan,
    revalidate_picklists_after_corrections,
)
from services.issue_edit_service import validate_picklist_replacement
from ui.issue_editor import render_picklist_issue_editor
from ui.preparation_action_cards import (
    TECHNICAL_DETAILS_TITLE,
    format_issue_details,
)

PICKLIST_ALL_VALID_MESSAGE = "✓ All values are valid."


def _correction_to_picklist_issue(correction: dict) -> dict:
    field = correction.get("salesforce_api_field") or correction.get("friendly_column")
    return {
        "edit_key": correction["correction_id"],
        "issue_id": correction.get("issue_id") or correction["correction_id"],
        "issue_type": "picklist",
        "row": correction.get("row"),
        "field": field,
        "friendly_column": correction.get("friendly_column") or field,
        "current_value": correction.get("uploaded_value", ""),
        "problem": "Invalid value",
        "allowed_values": list(correction.get("allowed_values") or []),
        "category": "picklist",
    }


def _invalid_corrections_for_field(field_group: dict) -> list[dict]:
    return [
        correction for correction in field_group.get("corrections", [])
        if not correction.get("is_whitespace_trim")
    ]


def _build_approved_correction(
    correction: dict,
    proposed_value: str,
    picklist_validation: dict,
) -> dict:
    summaries = picklist_validation.get("field_summaries", [])
    return {
        **correction,
        "proposed_value": proposed_value,
        "field_type": next(
            (
                item.get("field_type")
                for item in summaries
                if item.get("salesforce_field") == correction.get("salesforce_api_field")
            ),
            None,
        ),
    }


def _render_inline_picklist_editor(
    field_group: dict,
    invalid_corrections: list[dict],
    picklist_validation: dict,
    plan: dict,
    *,
    upload_method: str = "Data Import Tool",
) -> dict | None:
    """Render inline picklist editor beneath the review button for one field."""
    api_field = field_group["salesforce_field"]
    if st.session_state.get(SESSION_PICKLIST_REVIEW_EXPANDED_FIELD) != api_field:
        return None

    if not invalid_corrections:
        advance_picklist_review_after_save(
            st.session_state,
            api_field,
            remaining_invalid_count=0,
        )
        return None

    row_index_key = picklist_review_row_index_key(api_field)
    row_index = st.session_state.get(row_index_key, 0)
    correction, row_index = resolve_picklist_review_row_index(invalid_corrections, row_index)
    st.session_state[row_index_key] = row_index
    if correction is None:
        return None

    issue = _correction_to_picklist_issue(correction)
    field_key = api_field.replace(".", "_")
    st.markdown(f"**Row {correction.get('row')}**")
    saved = render_picklist_issue_editor(
        issue,
        upload_method=upload_method,
        session_key_prefix=f"picklist_inline_{field_key}_{row_index}",
        inside_expander=True,
    )
    if saved is None:
        return None

    remaining_invalid_count = len(invalid_corrections) - 1
    advance_picklist_review_after_save(
        st.session_state,
        api_field,
        remaining_invalid_count=remaining_invalid_count,
    )
    return {
        "approved_corrections": [
            _build_approved_correction(
                correction,
                saved["proposed_value"],
                picklist_validation,
            ),
        ],
        "plan": plan,
    }


def _render_picklist_field_card(
    field_group: dict,
    picklist_validation: dict,
    plan: dict,
    *,
    upload_method: str = "Data Import Tool",
) -> dict | None:
    """Render one picklist field card with optional inline review editor."""
    friendly = field_group["friendly_column"]
    api_field = field_group["salesforce_field"]
    field_key = api_field.replace(".", "_")
    icon = field_group["status_icon"]
    rows = field_group["affected_rows"]
    row_word = "row" if rows == 1 else "rows"
    invalid_corrections = _invalid_corrections_for_field(field_group)
    invalid_count = count_reviewable_picklist_corrections(field_group.get("corrections", []))

    with st.container(border=True):
        st.markdown(f"**{friendly}**")
        st.caption(f"Salesforce API: `{api_field}`")
        if invalid_count == 0 and not field_group.get("whitespace_only"):
            st.markdown(PICKLIST_ALL_VALID_MESSAGE)
        else:
            st.markdown(f"{icon} {rows} affected {row_word}")

        allowed_values = field_group.get("allowed_values") or []
        if allowed_values:
            with st.expander("View Allowed Values"):
                for value in allowed_values:
                    st.markdown(f"- `{value}`")

        if field_group.get("suggested_example"):
            st.caption(f"Whitespace trim example: {field_group['suggested_example']}")

        if field_group.get("whitespace_only"):
            if st.button(
                f"Apply Trim to All — {friendly}",
                key=f"picklist_apply_trim_{field_key}",
                use_container_width=True,
            ):
                return {
                    "approved_corrections": _approved_whitespace_for_field(field_group, picklist_validation),
                    "plan": plan,
                }
            return None

        if invalid_count <= 0:
            return None

        button_label = build_picklist_review_button_label(invalid_count)
        if st.button(
            button_label,
            key=f"picklist_review_field_{field_key}",
            use_container_width=True,
        ):
            set_picklist_review_expanded_field(st.session_state, api_field)

        return _render_inline_picklist_editor(
            field_group,
            invalid_corrections,
            picklist_validation,
            plan,
            upload_method=upload_method,
        )


def _sync_picklist_filter() -> set[str]:
    stored = st.session_state.get(SESSION_PICKLIST_FILTER)
    if stored is None:
        stored = list(DEFAULT_PICKLIST_FILTERS)
        st.session_state[SESSION_PICKLIST_FILTER] = stored
    return set(stored)


def _build_picklist_details(
    review_rows: list[dict],
    filtered_issues: list[dict],
) -> str:
    detail_rows = [
        {
            "row": row.get("row"),
            "field": row.get("friendly_column") or row.get("api_field"),
            "reason": row.get("problem") or row.get("status"),
            "original_value": row.get("uploaded_value"),
            "proposed_value": row.get("suggested_correction"),
        }
        for row in review_rows
        if any(issue.get("issue_id") == row.get("issue_id") for issue in filtered_issues)
    ]
    return format_issue_details(detail_rows, limit=50)


def _collect_approved_corrections(
    correctable: list[dict],
    picklist_validation: dict,
    bulk_decisions: dict,
    *,
    show_individual: bool,
) -> list[dict]:
    approved: list[dict] = []
    summaries = picklist_validation.get("field_summaries", [])

    if not show_individual:
        return apply_bulk_picklist_decision(correctable, bulk_decisions)

    for correction in correctable:
        correction_id = correction["correction_id"]
        if bulk_decisions.get(correction_id) == "Keep for Manual Review":
            continue
        if bulk_decisions.get(correction_id):
            approved.append({
                **correction,
                "proposed_value": bulk_decisions[correction_id],
                "field_type": next(
                    (
                        item.get("field_type")
                        for item in summaries
                        if item.get("salesforce_field") == correction.get("salesforce_api_field")
                    ),
                    None,
                ),
            })
            continue

        allowed_values = correction.get("allowed_values") or []
        options = ["Keep for Manual Review", *allowed_values]

        selected = st.selectbox(
            f"Row {correction.get('row')} `{correction.get('friendly_column') or correction.get('salesforce_api_field')}` "
            f"({correction.get('uploaded_value')})",
            options=options,
            index=0,
            key=f"picklist_choice_{correction_id}",
        )
        if selected != "Keep for Manual Review":
            validation = validate_picklist_replacement(selected, allowed_values)
            if not validation["valid"]:
                continue
            approved.append({
                **correction,
                "proposed_value": selected,
                "field_type": next(
                    (
                        item.get("field_type")
                        for item in summaries
                        if item.get("salesforce_field") == correction.get("salesforce_api_field")
                    ),
                    None,
                ),
            })
    return approved


def _approved_whitespace_for_field(
    field_group: dict,
    picklist_validation: dict,
) -> list[dict]:
    summaries = picklist_validation.get("field_summaries", [])
    return [
        {
            **correction,
            "field_type": next(
                (
                    item.get("field_type")
                    for item in summaries
                    if item.get("salesforce_field") == correction.get("salesforce_api_field")
                ),
                None,
            ),
        }
        for correction in field_group.get("corrections", [])
        if correction.get("is_whitespace_trim") and correction.get("proposed_value")
    ]


def render_picklist_validation(
    picklist_validation: dict,
    mapped_df: pd.DataFrame,
    mapping_rows: list[dict],
    template_context,
) -> dict | None:
    """Render picklist validation results and return approved corrections."""
    st.subheader("Picklist Review")

    for item in picklist_validation.get("field_summaries", []):
        if item.get("fallback_warning"):
            st.warning(item["fallback_warning"])

    summary_lines = build_picklist_column_summary_lines(picklist_validation)
    if summary_lines:
        st.markdown("**Picklist Review**")
        for line in summary_lines:
            st.markdown(f"- {line}")

    review_rows = build_picklist_review_rows(picklist_validation)
    plan = build_picklist_correction_plan(picklist_validation, mapped_df)
    correctable = plan.get("corrections", [])
    if not correctable:
        if picklist_validation.get("has_blocking_issues"):
            st.error("Unresolved invalid picklist values remain. Choose valid API values before download.")
        else:
            st.success("All picklist values passed validation.")
        return None

    field_groups = build_picklist_field_groups(picklist_validation, correctable)
    attention_count = len(correctable)
    field_count = len(field_groups)
    field_word = "field" if field_count == 1 else "fields"

    with st.container(border=True):
        st.subheader("Picklist Values")
        st.caption(
            f"{attention_count} value(s) require attention across {field_count} {field_word}."
        )

        for field_group in field_groups:
            card_result = _render_picklist_field_card(
                field_group,
                picklist_validation,
                plan,
            )
            if card_result is not None:
                return card_result

    filtered_issues = filter_picklist_issues(
        picklist_validation.get("issues", []),
        set(st.session_state.get(SESSION_PICKLIST_FILTER) or DEFAULT_PICKLIST_FILTERS),
    )
    picklist_details = _build_picklist_details(
        review_rows,
        filtered_issues or picklist_validation.get("issues", []),
    )

    with st.expander(TECHNICAL_DETAILS_TITLE, expanded=False):
        st.markdown(picklist_details)
        approval = _render_picklist_individual_review_content(
            picklist_validation,
            review_rows,
            correctable,
            plan,
            show_row_editors=False,
        )
        if approval is not None:
            return approval

    return None


def _render_picklist_individual_review_content(
    picklist_validation: dict,
    review_rows: list[dict],
    correctable: list[dict],
    plan: dict,
    *,
    show_row_editors: bool = True,
) -> dict | None:
    active_filters = _sync_picklist_filter()
    filter_options = sorted({
        issue.get("status")
        for issue in picklist_validation.get("issues", [])
        if issue.get("status")
    } | set(DEFAULT_PICKLIST_FILTERS))
    status_summary = build_picklist_status_summary(picklist_validation)

    selected_filters = st.multiselect(
        "Show picklist issues",
        options=filter_options,
        default=sorted(active_filters & set(filter_options)),
        key="picklist_status_filter",
    )
    st.session_state[SESSION_PICKLIST_FILTER] = selected_filters

    filtered_issues = filter_picklist_issues(
        picklist_validation.get("issues", []),
        set(selected_filters) if selected_filters else set(DEFAULT_PICKLIST_FILTERS),
    )
    if filtered_issues:
        display_rows = [
            row for row in review_rows
            if any(
                issue.get("issue_id") == row.get("issue_id")
                for issue in filtered_issues
            )
        ]
        st.dataframe(
            pd.DataFrame([
                {
                    "Row": row.get("row"),
                    "Column": row.get("friendly_column"),
                    "Salesforce field": row.get("api_field"),
                    "Current value": row.get("uploaded_value"),
                    "Problem": row.get("problem"),
                    "Allowed API values": row.get("allowed_values_display"),
                    "Status": row.get("status"),
                }
                for row in display_rows
            ]),
            use_container_width=True,
            hide_index=True,
        )
    elif picklist_validation.get("field_summaries"):
        st.caption("No picklist issues match the current filter.")

    st.caption(
        f"Valid: {status_summary.get('Valid', 0)} · "
        f"Needs Review: {status_summary.get('Needs Review', 0)} · "
        f"Needs User Action: {status_summary.get('Needs User Action', 0)} · "
        f"Not Checked: {status_summary.get('Not Checked', 0)}"
    )

    repeated_groups = {
        key: items for key, items in group_repeated_whitespace_trims(correctable).items()
        if len(items) > 1
    }
    bulk_decisions = dict(st.session_state.get(SESSION_PICKLIST_BULK) or {})

    if repeated_groups:
        st.markdown("**Repeated whitespace trims**")
        bulk_cols = st.columns(2)
        with bulk_cols[0]:
            apply_all = st.button("Apply Trim to All", key="picklist_apply_trim_all")
        with bulk_cols[1]:
            keep_manual = st.button("Keep for Manual Review", key="picklist_keep_manual")

        if apply_all:
            for _key, items in repeated_groups.items():
                first = items[0]
                replacement = first.get("proposed_value")
                if replacement:
                    for item in items:
                        bulk_decisions[item["correction_id"]] = replacement
            st.session_state[SESSION_PICKLIST_BULK] = bulk_decisions
            st.rerun()
        if keep_manual:
            for _key, items in repeated_groups.items():
                for item in items:
                    bulk_decisions[item["correction_id"]] = "Keep for Manual Review"
            st.session_state[SESSION_PICKLIST_BULK] = bulk_decisions
            st.rerun()

    st.markdown("**Select valid API values for invalid picklist rows**")
    approved = _collect_approved_corrections(
        correctable,
        picklist_validation,
        bulk_decisions,
        show_individual=show_row_editors,
    )
    if st.button("Apply Selected Picklist Replacements", type="primary", key="picklist_apply_selected"):
        return {"approved_corrections": approved, "plan": plan}

    return None


def apply_picklist_validation_result(
    mapped_df: pd.DataFrame,
    picklist_validation: dict,
    approval: dict,
    mapping_rows: list[dict],
    template_context,
) -> tuple[pd.DataFrame, dict, dict]:
    """Apply approved picklist replacements and revalidate."""
    corrected_df, change_log, _original_copy = apply_picklist_corrections(
        mapped_df,
        picklist_validation,
        approval.get("approved_corrections", []),
    )
    revalidation = revalidate_picklists_after_corrections(
        corrected_df,
        mapping_rows,
        template_context,
    )
    plan = approval.get("plan", {})
    plan["corrections_applied"] = True
    plan["approved_correction_ids"] = [
        item["correction_id"] for item in approval.get("approved_corrections", [])
    ]
    plan["change_log"] = change_log
    return corrected_df, revalidation, plan
