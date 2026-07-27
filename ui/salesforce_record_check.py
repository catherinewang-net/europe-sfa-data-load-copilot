"""Salesforce Record Check UI."""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from services.constants import (
    RECORD_CHECK_DUPLICATE_MATCH,
    RECORD_CHECK_NOT_FOUND,
    RECORD_CHECK_POSSIBLE_EXISTING,
    RECORD_CHECK_UNAVAILABLE,
)
from services.external_id_discovery_service import discover_identifier_fields
from validators.record_existence_validator import (
    build_record_existence_report_rows,
    validate_record_existence,
)


def render_salesforce_record_check(
    df: pd.DataFrame,
    mapping_rows: list[dict],
    template_context,
    load_operation: str | None,
    record_existence_validation: dict | None,
    *,
    use_mapped_columns: bool = False,
) -> dict | None:
    """Render live Salesforce record check controls and summary."""
    st.subheader("Salesforce Record Check")
    st.caption(
        "Read-only live lookup against Salesforce. "
        "Local metadata is used for identifier discovery; live org data is queried only when connected."
    )

    if not load_operation:
        st.info("Load-action-specific record checks were not performed (Prepare & Validate).")
        return None

    object_name = template_context.salesforce_object if template_context else None
    mapped_api_fields = {
        row.get("confirmed_api_field")
        for row in mapping_rows
        if row.get("confirmed_api_field")
    }
    candidates = discover_identifier_fields(
        object_name or "",
        mapped_api_fields=mapped_api_fields,
    )
    candidate_options = [field["field_api_name"] for field in candidates]
    default_field = (record_existence_validation or {}).get("identifier_field")
    if default_field not in candidate_options and candidate_options:
        default_field = candidate_options[0]

    skip_live_check = st.checkbox(
        "Skip live Salesforce record check",
        value=bool(st.session_state.get("skip_live_record_check", False)),
        key="skip_live_record_check",
        help="Use this for formatting-only preparation when live org access is unavailable.",
    )

    selected_field = None
    if candidate_options:
        selected_field = st.selectbox(
            "Matching identifier field",
            options=candidate_options,
            index=candidate_options.index(default_field) if default_field in candidate_options else 0,
            format_func=lambda api_name: _format_candidate_label(api_name, candidates),
            key="record_check_identifier_field",
        )
    else:
        st.warning("No reliable identifier fields were discovered from metadata.")

    connection = (record_existence_validation or {}).get("connection") or {}
    if connection.get("available"):
        st.success(connection.get("message", "Live Salesforce connection is available."))
    elif connection.get("status") == "skipped" or skip_live_check:
        st.info("Live Salesforce record check is skipped.")
    elif (record_existence_validation or {}).get("status") == RECORD_CHECK_UNAVAILABLE:
        st.warning(RECORD_CHECK_UNAVAILABLE)
    elif connection.get("status") == "not_evaluated":
        st.info("Live record check has not been evaluated yet.")
    else:
        st.warning(connection.get("message", RECORD_CHECK_UNAVAILABLE))

    if record_existence_validation and record_existence_validation.get("evaluated"):
        _render_summary(record_existence_validation, load_operation)

    if st.button("Run Salesforce Record Check", type="primary"):
        return {
            "identifier_field": selected_field,
            "skip_live_check": skip_live_check,
            "rerun": True,
        }
    return None


def apply_salesforce_record_check(
    df: pd.DataFrame,
    mapping_rows: list[dict],
    template_context,
    load_operation: str | None,
    approval: dict,
    *,
    use_mapped_columns: bool = False,
    client=None,
) -> dict:
    """Execute record existence validation based on UI approval."""
    return validate_record_existence(
        df,
        mapping_rows,
        load_operation,
        template_context,
        identifier_field=approval.get("identifier_field"),
        skip_live_check=approval.get("skip_live_check", False),
        use_mapped_columns=use_mapped_columns,
        client=client,
    )


def render_record_existence_download(record_existence_validation: dict) -> None:
    rows = build_record_existence_report_rows(record_existence_validation)
    if not rows:
        return
    csv_bytes = pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "Download Record Existence Report",
        data=io.BytesIO(csv_bytes),
        file_name="salesforce_record_existence_report.csv",
        mime="text/csv",
    )


def _render_summary(result: dict, load_operation: str) -> None:
    summary = result.get("summary") or {}
    st.markdown(
        f"**Object:** `{result.get('object_name')}` · "
        f"**Matching field:** `{result.get('identifier_field')}` · "
        f"**Rows checked:** {summary.get('checked_rows', 0)}"
    )

    counts = {
        "New identifiers": summary.get("new_identifier_count", 0),
        "Possible existing": summary.get("possible_existing_count", 0),
        "Existing found": summary.get("existing_count", 0),
        "Not found": summary.get("missing_count", 0),
        "Duplicate matches": summary.get("duplicate_match_count", 0),
    }
    if load_operation == "Insert":
        display_counts = {
            "New identifiers": counts["New identifiers"],
            "Possible existing": counts["Possible existing"],
        }
    else:
        display_counts = {
            "Existing found": counts["Existing found"],
            "Not found": counts["Not found"],
            "Duplicate matches": counts["Duplicate matches"],
        }
    st.dataframe(
        pd.DataFrame([display_counts]),
        use_container_width=True,
        hide_index=True,
    )

    row_results = result.get("row_results") or []
    flagged = [
        row for row in row_results
        if row.get("status") in {
            RECORD_CHECK_POSSIBLE_EXISTING,
            RECORD_CHECK_NOT_FOUND,
            RECORD_CHECK_DUPLICATE_MATCH,
        }
    ]
    if flagged:
        st.markdown("**Rows requiring review**")
        st.dataframe(
            pd.DataFrame([
                {
                    "Row": row.get("row"),
                    "Uploaded value": row.get("uploaded_value"),
                    "Status": row.get("status"),
                    "Match count": row.get("match_count"),
                    "Salesforce Ids": ";".join(row.get("salesforce_ids") or []),
                }
                for row in flagged
            ]),
            use_container_width=True,
            hide_index=True,
        )

    render_record_existence_download(result)


def _format_candidate_label(api_name: str, candidates: list[dict]) -> str:
    for candidate in candidates:
        if candidate["field_api_name"] == api_name:
            kinds = ", ".join(candidate.get("identifier_kinds") or [])
            return f"{api_name} ({kinds})"
    return api_name
