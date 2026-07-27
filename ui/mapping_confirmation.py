"""Confirm Salesforce Field Mappings UI for Workbench uploads."""

from __future__ import annotations

import streamlit as st

from services.constants import (
    MAPPING_ACTION_EXCLUDE,
    MAPPING_ACTION_KEEP,
    MAPPING_ACTION_MAP,
    MAPPING_STATUS_CONFIRMED,
    MAPPING_STATUS_EXACT_API,
    MAPPING_STATUS_EXCLUDED,
    MAPPING_STATUS_NEEDS_CONFIRMATION,
    MAPPING_STATUS_UNRESOLVED,
)
from services.workbench_field_catalog_service import (
    WorkbenchFieldOption,
    filter_field_options,
    parse_api_field_from_display,
)
from services.workbench_field_matcher import CONFIDENCE_HIGH
from services.workbench_mapping_service import (
    apply_mapping_action,
    confirm_all_high_confidence,
    detect_mapping_collisions,
    exclude_all_unmapped,
    filter_valid_mapping_rows,
    get_mapping_summary,
    mappings_ready_for_preparation,
    reset_mappings,
    rows_to_session,
)


ACTION_LABELS = {
    MAPPING_ACTION_MAP: "Map to Salesforce Field",
    MAPPING_ACTION_KEEP: "Keep Existing Header",
    MAPPING_ACTION_EXCLUDE: "Do Not Include",
}


def _option_map(options: list[WorkbenchFieldOption]) -> dict[str, WorkbenchFieldOption]:
    return {option.display_label: option for option in options}


def _display_status(row: dict) -> str:
    status = row.get("status")
    if status == MAPPING_STATUS_CONFIRMED:
        return "Confirmed"
    if status == MAPPING_STATUS_EXCLUDED:
        return "Excluded"
    if status == MAPPING_STATUS_EXACT_API and row.get("resolved"):
        return "Exact API Header"
    if status in (MAPPING_STATUS_NEEDS_CONFIRMATION, MAPPING_STATUS_UNRESOLVED):
        return "Unresolved"
    return str(status or "Unresolved")


def render_mapping_confirmation(
    mapping_rows: list[dict],
    field_catalog: list[WorkbenchFieldOption],
    required_type: str | None,
    type_metadata_valid: bool = True,
    type_metadata_error: str | None = None,
    template_name: str | None = None,
    uploaded_headers: list[str] | None = None,
    load_operation: str | None = None,
    template_context=None,
    is_account_template: bool = False,
) -> tuple[list[dict], bool, bool]:
    """
    Render Workbench Header Review UI.

    Returns updated mapping rows, whether Type addition is confirmed,
    and whether the user clicked Continue to Data Validation.
    """
    st.subheader("Header Review")
    st.caption(
        "Review how each uploaded column should appear in the Workbench-ready CSV. "
        "Excluded columns are omitted from validation and download."
    )

    valid_rows = filter_valid_mapping_rows(mapping_rows)
    summary = get_mapping_summary(valid_rows)
    metric_cols = st.columns(3)
    metric_cols[0].metric("Resolved columns", summary["resolved"])
    metric_cols[1].metric("Excluded columns", summary["excluded"])
    metric_cols[2].metric("Still unresolved", summary["unresolved"])

    collisions = detect_mapping_collisions(valid_rows)
    for collision in collisions:
        st.error(collision["message"])

    filter_query = st.text_input(
        "Filter API fields",
        placeholder="Search by API name or label (e.g. billing postal, channel, CUST_ID)...",
        key="api_field_filter",
    )
    catalog_by_api = {option.api_name: option for option in field_catalog}

    action_cols = st.columns(4)
    with action_cols[0]:
        if st.button("Approve All High-Confidence Header Changes", type="secondary"):
            count = confirm_all_high_confidence(mapping_rows)
            st.session_state["workbench_mappings"] = rows_to_session(mapping_rows)
            st.success(f"Confirmed {count} high-confidence mapping(s).")
            st.rerun()
    with action_cols[1]:
        if st.button("Exclude All Unmapped Columns", type="secondary"):
            count = exclude_all_unmapped(mapping_rows)
            st.session_state["workbench_mappings"] = rows_to_session(mapping_rows)
            st.success(f"Excluded {count} column(s).")
            st.rerun()
    with action_cols[2]:
        if st.button("Review Individually", type="secondary"):
            st.session_state["header_review_individual_mode"] = True
            st.info("Review each column below and choose an action.")
    with action_cols[3]:
        if st.button("Reset Choices") and template_name and uploaded_headers:
            st.session_state["mapping_rows"] = reset_mappings(
                uploaded_headers,
                template_name,
                load_operation,
            )
            st.session_state.pop("workbench_mappings", None)
            st.session_state.pop("mapped_df", None)
            st.session_state.pop("header_review_complete", None)
            st.session_state.pop("proposed_df", None)
            st.rerun()

    if not valid_rows:
        st.warning("No usable uploaded column headers were found.")
        return mapping_rows, False, False

    header_cols = st.columns([1.8, 1.8, 0.9, 1.6, 1.8, 1.1])
    header_cols[0].markdown("**Uploaded Header**")
    header_cols[1].markdown("**Suggested Target**")
    header_cols[2].markdown("**Match Confidence**")
    header_cols[3].markdown("**Reason**")
    header_cols[4].markdown("**Action**")
    header_cols[5].markdown("**Status**")

    for row in valid_rows:
        uploaded_col = row.get("uploaded_column") or row["dit_column"]
        confidence = row.get("confidence") or "—"
        status_label = _display_status(row)
        reason = row.get("reason") or "—"

        cols = st.columns([1.8, 1.8, 0.9, 1.6, 1.8, 1.1])
        cols[0].markdown(f"**{uploaded_col}**")

        action_options = [MAPPING_ACTION_MAP, MAPPING_ACTION_EXCLUDE]
        if row.get("can_keep_existing_header"):
            action_options.insert(1, MAPPING_ACTION_KEEP)

        current_action = row.get("action") or MAPPING_ACTION_MAP
        if current_action not in action_options:
            action_options.append(current_action)

        selected_action = cols[4].radio(
            "Action",
            options=action_options,
            format_func=lambda value: ACTION_LABELS.get(value, value),
            index=action_options.index(current_action),
            key=f"map_action_{uploaded_col}",
            label_visibility="collapsed",
            horizontal=False,
        )
        if selected_action != current_action:
            target = row.get("suggested_api_field") if selected_action == MAPPING_ACTION_MAP else None
            apply_mapping_action(mapping_rows, uploaded_col, selected_action, target)
            st.session_state["workbench_mappings"] = rows_to_session(mapping_rows)
            st.rerun()

        suggested = row.get("suggested_api_field")
        current_api = row.get("confirmed_api_field") or suggested
        target_selection = "— Select API field —"
        if current_api and current_api in catalog_by_api:
            target_selection = catalog_by_api[current_api].display_label

        if selected_action == MAPPING_ACTION_MAP:
            row_filtered = filter_field_options(field_catalog, filter_query, uploaded_col)
            if filter_query.strip() and not row_filtered:
                row_filtered = field_catalog

            ranked_labels = []
            for candidate in row.get("ranked_candidates", []):
                api_field = candidate.get("api_field")
                if api_field in catalog_by_api:
                    ranked_labels.append(catalog_by_api[api_field].display_label)

            suggested_label = None
            if suggested in catalog_by_api:
                suggested_label = catalog_by_api[suggested].display_label

            row_option_labels = list(dict.fromkeys(
                ["— Select API field —"]
                + ([suggested_label] if suggested_label else [])
                + ranked_labels
                + [option.display_label for option in row_filtered]
                + ([target_selection] if target_selection not in {"— Select API field —"} else [])
            ))

            selected_label = cols[1].selectbox(
                "Suggested Target",
                options=row_option_labels,
                index=row_option_labels.index(target_selection)
                if target_selection in row_option_labels
                else 0,
                key=f"map_target_{uploaded_col}",
                label_visibility="collapsed",
            )
            selected_option = _option_map(field_catalog).get(selected_label)
            if selected_option:
                st.caption(f"{selected_option.writeability}")

            selected_api = parse_api_field_from_display(selected_label)
            if (
                selected_api
                and selected_label != "— Select API field —"
                and (
                    row.get("confirmed_api_field") != selected_api
                    or not row.get("resolved")
                    or row.get("action") != MAPPING_ACTION_MAP
                )
            ):
                apply_mapping_action(mapping_rows, uploaded_col, MAPPING_ACTION_MAP, selected_api)
                st.session_state["workbench_mappings"] = rows_to_session(mapping_rows)
                st.rerun()
            cols[2].markdown(str(confidence))
            cols[3].markdown(reason)
        elif selected_action == MAPPING_ACTION_KEEP:
            cols[1].markdown(f"`{uploaded_col}`")
            cols[2].markdown(str(confidence))
            cols[3].markdown(reason or "Exact API field name match")
        else:
            cols[1].markdown("_Excluded_")
            cols[2].markdown("—")
            cols[3].markdown("Column will not be included in output")

        cols[5].markdown(status_label)

        if row.get("validation_error"):
            st.caption(row["validation_error"])
        if row.get("has_duplicate_assignment"):
            st.warning(f"`{uploaded_col}` shares a target API field with another uploaded column.")
        if row.get("is_ambiguous") and not row.get("resolved"):
            st.caption("Multiple similar fields found — choose the correct Salesforce API field.")
        elif (
            row.get("status") == MAPPING_STATUS_NEEDS_CONFIRMATION
            and row.get("confidence") == CONFIDENCE_HIGH
            and not row.get("resolved")
        ):
            st.caption("High-confidence suggestion — confirm the target field or choose another action.")

    type_confirmed = False
    if required_type:
        st.divider()
        if not type_metadata_valid:
            st.error(type_metadata_error or "Account.Type metadata is invalid for this template.")
        else:
            st.markdown(
                f"**Account template requires Type column**  \n"
                f"Every row will be populated with: `{required_type}`"
            )
            type_confirmed = st.checkbox(
                f"I confirm adding and populating the Type column with '{required_type}'",
                key="confirm_type_column",
            )

    ready, block_message = mappings_ready_for_preparation(
        mapping_rows,
        type_confirmed if is_account_template else True,
        is_account_template,
        template_context,
    )
    continue_clicked = False
    if st.button(
        "Continue to Data Validation",
        type="primary",
        disabled=not ready,
    ):
        continue_clicked = True
    elif not ready:
        st.info(block_message)

    st.session_state["workbench_mappings"] = rows_to_session(mapping_rows)
    return mapping_rows, type_confirmed, continue_clicked
