"""Lookup validation UI for DIT and Workbench.

Deprecated: live lookup validation was removed from the active UI path.
Use ui.data_preparation_warnings for dependency-based guidance instead.
"""

from __future__ import annotations

from io import StringIO

import pandas as pd
import streamlit as st

from services.constants import (
    LOOKUP_METHOD_BUSINESS_KEY,
    LOOKUP_METHOD_COMPOSITE,
    LOOKUP_METHOD_EXTERNAL_ID,
    LOOKUP_METHOD_NAME,
    LOOKUP_METHOD_SALESFORCE_ID,
    LOOKUP_METHOD_UNKNOWN,
    LOOKUP_STATUS_NEEDS_REVIEW,
    LOOKUP_STATUS_NOT_CHECKED,
    LOOKUP_STATUS_NOT_FOUND,
    LOOKUP_STATUS_PARENT_FIRST,
    LOOKUP_STATUS_VALID,
)
from validators.lookup_validator import build_lookup_validation_report_rows


MATCHING_METHOD_OPTIONS = [
    LOOKUP_METHOD_SALESFORCE_ID,
    LOOKUP_METHOD_EXTERNAL_ID,
    LOOKUP_METHOD_BUSINESS_KEY,
    LOOKUP_METHOD_NAME,
    LOOKUP_METHOD_COMPOSITE,
    LOOKUP_METHOD_UNKNOWN,
]


def render_lookup_validation(
    lookup_validation: dict,
    mapped_df: pd.DataFrame,
    mapping_rows: list[dict],
) -> dict | None:
    """Render lookup validation results and return user decisions."""
    st.subheader("Lookup Validation")
    st.caption(
        "Lookup fields are identified from Salesforce metadata on retained mapped columns. "
        "The Copilot never invents Salesforce IDs or parent records."
    )

    summary = lookup_validation.get("summary", {})
    if summary:
        metric_cols = st.columns(4)
        metrics = [
            ("Lookup fields", summary.get("lookup_fields_checked", 0)),
            ("Rows checked", summary.get("rows_checked", 0)),
            ("Valid lookups", summary.get("valid_count", 0)),
            ("Needs review", summary.get("needs_review_count", 0)),
        ]
        for col, (label, value) in zip(metric_cols, metrics):
            with col:
                st.metric(label, value)

        detail_cols = st.columns(4)
        detail_metrics = [
            ("Not found", summary.get("not_found_count", 0)),
            ("Multiple matches", summary.get("multiple_match_count", 0)),
            ("Not checked", summary.get("not_checked_count", 0)),
            ("Parents first", summary.get("parent_first_count", 0)),
        ]
        for col, (label, value) in zip(detail_cols, detail_metrics):
            with col:
                st.metric(label, value)

    field_summaries = lookup_validation.get("field_summaries", [])
    if field_summaries:
        st.dataframe(
            pd.DataFrame([
                {
                    "Source object": item.get("source_object"),
                    "Lookup field": item.get("lookup_field"),
                    "Field label": item.get("field_label"),
                    "Uploaded column": item.get("uploaded_column"),
                    "Referenced object": item.get("referenced_object"),
                    "Relationship": item.get("relationship_type"),
                    "Required": item.get("required"),
                    "Metadata source": item.get("metadata_source"),
                }
                for item in field_summaries
            ]),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("No lookup or reference fields were found in the retained mapped columns.")

    row_results = lookup_validation.get("row_results", [])
    review_rows = [
        row for row in row_results
        if row.get("status") != LOOKUP_STATUS_VALID
    ]
    if row_results:
        display_rows = review_rows or row_results
        st.markdown("**Lookup row results**")
        st.dataframe(
            pd.DataFrame([
                {
                    "Row": row.get("row"),
                    "Source object": row.get("source_object"),
                    "Lookup field": row.get("lookup_field"),
                    "Uploaded value": row.get("uploaded_value"),
                    "Referenced object": row.get("referenced_object"),
                    "Matching method": row.get("matching_method"),
                    "Status": row.get("status"),
                    "Reason": row.get("reason"),
                    "Parent action": row.get("parent_action"),
                }
                for row in display_rows
            ]),
            use_container_width=True,
            hide_index=True,
        )

    report_rows = build_lookup_validation_report_rows(lookup_validation)
    if report_rows:
        report_buffer = StringIO()
        pd.DataFrame(report_rows).to_csv(report_buffer, index=False)
        st.download_button(
            "Download Lookup Validation Report",
            data=report_buffer.getvalue(),
            file_name="lookup_validation_report.csv",
            mime="text/csv",
        )

    if lookup_validation.get("metadata_only"):
        st.info(
            lookup_validation.get(
                "message",
                "Live Salesforce lookup checks were not performed. Values remain metadata-only.",
            )
        )

    if lookup_validation.get("has_blocking_issues"):
        st.error("Blocking lookup validation issues remain.")

    decisions: list[dict] = []
    actionable = [
        row for row in review_rows
        if row.get("status") in {
            LOOKUP_STATUS_NEEDS_REVIEW,
            LOOKUP_STATUS_NOT_CHECKED,
            LOOKUP_STATUS_NOT_FOUND,
            LOOKUP_STATUS_PARENT_FIRST,
        }
    ]
    if not actionable:
        if row_results:
            st.success("All checked lookup values passed validation or were confirmed.")
        return None

    st.markdown("**Lookup review actions**")
    for row in actionable:
        row_key = f"lookup_row_{row.get('row')}_{row.get('lookup_field')}"
        selected_method = st.selectbox(
            f"Row {row.get('row')} `{row.get('lookup_field')}` matching method",
            options=MATCHING_METHOD_OPTIONS,
            index=MATCHING_METHOD_OPTIONS.index(row.get("matching_method", LOOKUP_METHOD_UNKNOWN))
            if row.get("matching_method") in MATCHING_METHOD_OPTIONS
            else len(MATCHING_METHOD_OPTIONS) - 1,
            key=f"{row_key}_method",
        )
        action = st.radio(
            f"Row {row.get('row')} action",
            options=[
                "Keep for manual review",
                "Exclude row from download",
            ],
            key=f"{row_key}_action",
            horizontal=True,
        )
        decisions.append({
            "row": row.get("row"),
            "lookup_field": row.get("lookup_field"),
            "matching_method": selected_method,
            "action": "exclude" if action.startswith("Exclude") else "manual_review",
        })

    if st.button("Apply lookup review decisions", key="apply_lookup_review"):
        return {"decisions": decisions}
    return None
