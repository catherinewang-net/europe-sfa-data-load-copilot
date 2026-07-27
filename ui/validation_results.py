"""Validation results UI sections."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from ui.preparation_action_cards import render_technical_details_expander


def _render_validation_details(validation_bundle: dict[str, Any]) -> None:
    metadata_info = validation_bundle.get("metadata_source", {})
    mapping_rows = validation_bundle.get("mapping_rows", [])
    picklist_validation = validation_bundle.get("picklist_validation", {})
    manual_review = validation_bundle.get("manual_review", [])
    download_readiness = validation_bundle.get("download_readiness", {})

    st.markdown("### A. Salesforce Metadata Source")
    st.markdown(
        f"- **Repository mode:** {metadata_info.get('repository_mode', 'Local SFDX Metadata')}  \n"
        f"- **Template source:** `{metadata_info.get('template_source', 'Unavailable')}`  \n"
        f"- **Salesforce object:** `{metadata_info.get('salesforce_object', '—')}`  \n"
        f"- **Record type:** `{metadata_info.get('record_type') or '—'}`  \n"
        f"- **Metadata load status:** {metadata_info.get('metadata_load_status', 'Unknown')}  \n"
        f"- **Skipped XML files:** {metadata_info.get('skipped_xml_files', 0)}"
    )

    st.markdown("### B. Field Mapping Review")
    if mapping_rows:
        mapping_df = pd.DataFrame([
            {
                "Uploaded header": row.get("dit_column"),
                "Suggested API field": row.get("suggested_api_field") or "—",
                "Exists on object": row.get("exists_on_object", False),
                "Mapping source": row.get("mapping_source"),
                "User confirmation": row.get("status"),
                "Include/exclude": (
                    "Excluded"
                    if row.get("status") == "Do Not Include"
                    else "Included"
                    if row.get("status") == "Confirmed"
                    else "Pending"
                ),
            }
            for row in mapping_rows
        ])
        st.dataframe(mapping_df, use_container_width=True, hide_index=True)
    else:
        st.caption("No mapping rows available.")

    st.markdown("### C. Picklist Validation")
    summaries = picklist_validation.get("field_summaries", [])
    if summaries:
        summary_df = pd.DataFrame(summaries)
        st.dataframe(summary_df, use_container_width=True, hide_index=True)
    else:
        st.caption("No picklist fields were validated.")

    invalid_issues = [
        issue for issue in picklist_validation.get("issues", [])
        if issue.get("status") not in {"Valid", "Metadata Unavailable"}
    ]
    if invalid_issues:
        st.markdown("**Invalid picklist values**")
        st.dataframe(pd.DataFrame(invalid_issues), use_container_width=True, hide_index=True)

    st.markdown("### D. Load Action Validation")
    load_action_validation = validation_bundle.get("load_action_validation")
    if load_action_validation:
        status = load_action_validation.get("status") or load_action_validation.get("load_operation") or "—"
        st.markdown(f"- **Status:** {status}")
        if not load_action_validation.get("evaluated", True):
            st.info(load_action_validation.get("message", "Load-action-specific checks were not performed."))
        elif load_action_validation.get("issues"):
            st.dataframe(pd.DataFrame(load_action_validation["issues"]), use_container_width=True, hide_index=True)
        else:
            st.caption("No load-action issues detected.")
    else:
        st.caption("Load action validation was not run.")

    st.markdown("### E. Manual Review")
    if manual_review:
        st.dataframe(pd.DataFrame(manual_review), use_container_width=True, hide_index=True)
    else:
        st.caption("No manual review items.")

    reasons = download_readiness.get("reasons", [])
    warnings = download_readiness.get("warnings", [])
    if reasons:
        st.error("Download blocked:\n\n" + "\n".join(f"- {reason}" for reason in reasons))
    if warnings:
        st.warning("\n".join(f"- {warning}" for warning in warnings))


def render_validation_results(validation_bundle: dict[str, Any]) -> None:
    """Render full validation diagnostics inside a technical expander."""
    render_technical_details_expander(
        render_fn=lambda: _render_validation_details(validation_bundle),
    )
