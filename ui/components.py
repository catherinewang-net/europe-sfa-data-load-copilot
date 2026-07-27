"""Streamlit UI components — display only, no business logic."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pandas as pd
import streamlit as st

from core.config import READINESS_STATUS
from engines.ai_summary import generate_copilot_summary
from engines.field_mapping import get_fields_to_add


def render_file_overview(filename: str, row_count: int, col_count: int) -> None:
    st.subheader("File Overview")
    stat_cols = st.columns(3)
    stats = [
        ("File name", filename),
        ("Number of rows", f"{row_count:,}"),
        ("Number of columns", f"{col_count:,}"),
    ]
    for col, (label, value) in zip(stat_cols, stats):
        with col:
            st.markdown(
                f"""
                <div class="file-stat">
                    <div class="file-stat-label">{label}</div>
                    <div class="file-stat-value">{value}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_preview(df: pd.DataFrame) -> None:
    st.subheader("Preview")
    st.caption("First 10 rows")
    st.dataframe(df.head(10), use_container_width=True, hide_index=True)


def render_mapping_plan(template_config: dict, template: str) -> None:
    """Show Salesforce object context for Account templates."""
    fields_to_add = get_fields_to_add(template_config)

    st.markdown(
        f"**Salesforce Object:** {template_config['salesforce_object']}  \n"
        f"**Required Type Value:** {template_config.get('required_type', 'N/A')}"
    )
    st.markdown("**Fields that will be added (after confirmation):**")
    for field in fields_to_add:
        st.markdown(f"- `{field}`")
    st.caption(
        "Field mappings must be confirmed in the section below before "
        "a Workbench-ready CSV can be generated."
    )


def render_comparison_results(
    result: dict,
    correction_plan: dict | None = None,
) -> None:
    """Show template match status; detailed comparison lives in technical expander."""
    from ui.preparation_action_cards import (
        format_header_order_details,
        render_technical_details_expander,
    )

    comparison = result["comparison"]
    if comparison["template_match"]:
        status = "Ready"
        status_color = "#15803d"
        background = "#f0fdf4"
        border = "#bbf7d0"
    elif (
        correction_plan
        and correction_plan.get("has_fixable_changes")
        and not correction_plan.get("corrections_applied")
    ):
        status = "Needs User Action"
        status_color = "#b45309"
        background = "#fffbeb"
        border = "#fde68a"
    else:
        status = "Not Ready"
        status_color = "#b91c1c"
        background = "#fef2f2"
        border = "#fecaca"

    if result.get("mismatch_warning"):
        st.warning(result["mismatch_warning"])

    st.markdown(
        f"""
        <div style="
            background: {background};
            border: 1px solid {border};
            border-radius: 0.5rem;
            padding: 1rem 1.25rem;
            margin-bottom: 1rem;
        ">
            <div style="font-size: 0.8rem; color: #64748b;">Template match</div>
            <div style="font-size: 1.25rem; font-weight: 700; color: {status_color};">
                {status} — {comparison['match_percentage']}% column match
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    def _render_technical_comparison() -> None:
        reference_path = result["reference_path"]
        cols = st.columns(4)
        cols[0].metric("Match", f"{comparison['match_percentage']}%")
        cols[1].metric("Uploaded Columns", comparison["uploaded_column_count"])
        cols[2].metric("Expected Columns", comparison["expected_column_count"])
        cols[3].metric("Matching Headers", len(comparison["matching_headers"]))

        st.markdown(
            f"**Upload method:** {result['upload_method']}  \n"
            f"**Template:** {result['template']}  \n"
            f"**Reference file:** `{reference_path.name}`"
        )

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown("**Matching headers**")
            _list_or_none(comparison["matching_headers"])
        with c2:
            st.markdown("**Proposed renames**")
            proposed = comparison.get("proposed_renames", [])
            if proposed:
                for rename in proposed:
                    st.markdown(
                        f"- `{rename['source_column']}` → `{rename['target_column']}`"
                    )
            else:
                st.caption("None")
        with c3:
            st.markdown("**Potential manual review**")
            manual_items = comparison.get("manual_mapping_required", [])
            missing_required = comparison.get("missing_columns", [])
            extras = comparison.get("extra_columns", [])
            if manual_items or missing_required or extras:
                for item in manual_items:
                    st.markdown(f"- {item.get('description', 'Manual mapping required')}")
                for column in missing_required:
                    st.markdown(f"- Required field `{column}` has no confirmed mapping")
                for column in extras:
                    st.markdown(f"- Extra column `{column}` is not part of the target template")
            else:
                st.caption("None")
        with c4:
            st.markdown("**Generated / conditional fields**")
            generated = comparison.get("generated_fields", [])
            conditional = comparison.get("conditional_fields", [])
            if generated or conditional:
                for item in generated:
                    st.markdown(f"- Generated: `{item['field']}` = `{item['value']}`")
                for item in conditional:
                    st.markdown(f"- Conditional: {item.get('description', item.get('field'))}")
            else:
                st.caption("None")

        if comparison.get("optional_missing_columns"):
            st.markdown("**Optional template columns not present**")
            _list_or_none(comparison["optional_missing_columns"])

        if comparison["order_differences"]:
            st.markdown("**Header-order differences**")
            st.markdown(format_header_order_details(comparison["order_differences"]))
        if comparison.get("duplicate_columns"):
            st.markdown("**Duplicate headers**")
            _list_or_none(comparison["duplicate_columns"])

    render_technical_details_expander(render_fn=_render_technical_comparison)


def render_preparation_results(
    result: dict,
    template: str,
    original_filename: str,
    upload_method: str,
    can_download: bool,
    download_message: str,
    validation_result: dict | None = None,
    comparison_result: dict | None = None,
    preparation_only: bool = False,
) -> None:
    """Show corrected preview and download; technical stats live in expander."""
    from ui.preparation_action_cards import render_technical_details_expander

    for warning in result.get("warnings", []):
        st.warning(warning)

    st.subheader("Corrected Preview")
    corrected_df = result.get("corrected_df")

    if corrected_df is None:
        st.error("Corrected preview is unavailable.")
        return

    date_status_preview = result.get("date_status_preview")

    if isinstance(date_status_preview, pd.DataFrame):
        if not date_status_preview.empty:
            preview_df = date_status_preview
        else:
            preview_df = corrected_df
    elif date_status_preview is not None:
        preview_df = date_status_preview
    else:
        preview_df = corrected_df

    st.dataframe(preview_df.head(10), use_container_width=True, hide_index=True)

    date_unresolved = result.get("date_unresolved", [])

    base_name = Path(original_filename).stem
    from services.export_service import (
        build_review_dataframe,
        build_review_filename,
        build_review_issue_examples,
        build_tool_ready_filename,
    )
    from validators.common import export_csv_with_quoting

    tool_ready_filename = build_tool_ready_filename(base_name, upload_method)
    review_filename = build_review_filename(base_name)

    if not can_download:
        from engines.upload_readiness import assess_readiness

        readiness = assess_readiness(
            validation_result=validation_result,
            preparation_result=result,
            comparison_result=comparison_result,
            correction_plan=result.get("correction_plan"),
        )
        render_readiness(readiness)
        if download_message:
            st.caption(download_message)

        issue_examples = build_review_issue_examples(result, validation_result)
        if issue_examples:
            st.warning(
                "⚠️ This file still has unresolved issues and may fail during upload.\n\n"
                "Examples:\n"
                + "\n".join(issue_examples)
            )

    st.markdown("**Download Review CSV**")
    st.caption(
        "This file includes your approved changes, but unresolved issues may still "
        "cause Salesforce upload failures."
    )
    include_issue_notes = st.checkbox(
        "Include issue notes in review file",
        key="include_issue_notes_in_review",
    )
    review_df = build_review_dataframe(
        corrected_df,
        include_issue_notes=include_issue_notes,
        preparation_result=result,
        validation_result=validation_result,
    )
    st.download_button(
        "Download Review CSV",
        data=export_csv_with_quoting(review_df),
        file_name=review_filename,
        mime="text/csv",
        use_container_width=True,
        key="download_review_csv",
    )

    if can_download:
        st.markdown("**Download Tool-Ready CSV**")
        st.caption("All blocking issues have been resolved.")
        st.download_button(
            "Download Tool-Ready CSV",
            data=export_csv_with_quoting(corrected_df),
            file_name=tool_ready_filename,
            mime="text/csv",
            use_container_width=True,
            key="download_tool_ready_csv",
        )

        if preparation_only:
            st.info(
                "Your file has been prepared for the selected tool. "
                "Insert or Update requirements were not checked."
            )
        else:
            st.success("Your corrected file is ready to download.")
    else:
        st.info(
            "Tool-ready download will become available after blocking issues are resolved."
        )

    def _render_technical_preparation_details() -> None:
        from engines.upload_readiness import assess_readiness
        from services.preparation_orchestrator import build_validation_summary
        from services.upload_order_service import (
            build_dependency_issues_report,
            build_upload_order_report_rows,
        )

        readiness = assess_readiness(
            validation_result=validation_result,
            preparation_result=result,
            comparison_result=comparison_result,
            correction_plan=result.get("correction_plan"),
        )
        render_readiness(readiness)

        stats = result["stats"]
        cols = st.columns(6)
        cols[0].metric("Headers Renamed", stats.get("headers_renamed", 0))
        cols[1].metric("Dates Converted", stats.get("dates_converted", 0))
        cols[2].metric("Whitespace Trimmed", stats.get("whitespace_trimmed", 0))
        cols[3].metric("Blank Rows Removed", stats.get("blank_rows_removed", 0))
        cols[4].metric("Phones Normalized", stats.get("phones_normalized", 0))
        cols[5].metric("Manual Review", stats.get("rows_requiring_manual_review", 0))

        formatting_applied = result.get("formatting_applied", [])
        if formatting_applied:
            st.caption(
                "Formatting categories applied: "
                + ", ".join(formatting_applied)
            )

        if date_unresolved:
            st.subheader("Unresolved Date Issues")
            st.dataframe(pd.DataFrame(date_unresolved), use_container_width=True, hide_index=True)

        if result["manual_review"]:
            st.subheader("Manual Review Items")
            st.dataframe(pd.DataFrame(result["manual_review"]), use_container_width=True, hide_index=True)

        summary_text = generate_copilot_summary(
            upload_method, template,
            validation_result=validation_result,
            preparation_result=result,
            readiness=readiness,
        )
        st.markdown("**Copilot Summary**")
        st.markdown(summary_text)

        st.download_button(
            "Download Change Log",
            data=json.dumps(result["change_log"], indent=2),
            file_name=f"{base_name}_change_log.json",
            mime="application/json",
            key="tech_download_change_log",
        )
        if validation_result:
            st.download_button(
                "Download Validation Summary",
                data=json.dumps(
                    build_validation_summary(validation_result, result),
                    indent=2,
                ),
                file_name=f"{base_name}_validation_summary.json",
                mime="application/json",
                key="tech_download_validation_summary",
            )

            upload_plan = validation_result.get("upload_order_plan") or {}
            order_rows = build_upload_order_report_rows(upload_plan)
            if order_rows:
                order_buffer = StringIO()
                pd.DataFrame(order_rows).to_csv(order_buffer, index=False)
                st.download_button(
                    "Download Upload Order Plan",
                    data=order_buffer.getvalue(),
                    file_name=f"{base_name}_upload_order_plan.csv",
                    mime="text/csv",
                    key="tech_download_upload_order",
                )

            issue_rows = build_dependency_issues_report(upload_plan)
            if issue_rows:
                issue_buffer = StringIO()
                pd.DataFrame(issue_rows).to_csv(issue_buffer, index=False)
                st.download_button(
                    "Download Dependency Issues Report",
                    data=issue_buffer.getvalue(),
                    file_name=f"{base_name}_dependency_issues_report.csv",
                    mime="text/csv",
                    key="tech_download_dependency_issues",
                )
        st.download_button(
            "Download Mapping Report",
            data=json.dumps(result.get("mapping_report", {}), indent=2),
            file_name=f"{base_name}_mapping_report.json",
            mime="application/json",
            key="tech_download_mapping_report",
        )
        st.download_button(
            "Download Manual Review Report",
            data=json.dumps(result["manual_review"], indent=2),
            file_name=f"{base_name}_manual_review.json",
            mime="application/json",
            key="tech_download_manual_review",
        )

    render_technical_details_expander(render_fn=_render_technical_preparation_details)


def render_readiness(readiness: dict) -> None:
    status = readiness["status"]
    css_class = {
        READINESS_STATUS["READY"]: "readiness-ready",
        READINESS_STATUS["READY_WITH_WARNINGS"]: "readiness-warn",
        READINESS_STATUS["NEEDS_HEADER_REVIEW"]: "readiness-warn",
        READINESS_STATUS["NEEDS_USER_ACTION"]: "readiness-warn",
        READINESS_STATUS["NOT_READY"]: "readiness-not-ready",
    }.get(status, "readiness-not-ready")

    st.markdown(
        f'<p class="{css_class}">Upload Readiness: {status}</p>',
        unsafe_allow_html=True,
    )
    st.markdown(readiness.get("explanation", ""))


def _list_or_none(items: list) -> None:
    if items:
        for item in items:
            st.markdown(f"- `{item}`")
    else:
        st.caption("None")
