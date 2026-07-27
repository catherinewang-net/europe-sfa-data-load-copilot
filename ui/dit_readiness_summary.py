"""Template readiness summary for Data Import Tool workflow."""

from __future__ import annotations

import streamlit as st

from services.dit_ux_service import build_template_readiness_summary


def render_template_readiness_summary(
    *,
    correction_plan: dict | None,
    picklist_validation: dict | None = None,
    prerequisite_status: dict | None = None,
    upload_order_plan: dict | None = None,
    enabled_change_ids: set[str] | None = None,
    picklist_corrections_applied: int = 0,
    template: str = "",
) -> dict:
    summary = build_template_readiness_summary(
        correction_plan=correction_plan,
        picklist_validation=picklist_validation,
        prerequisite_status=prerequisite_status,
        upload_order_plan=upload_order_plan,
        enabled_change_ids=enabled_change_ids,
        picklist_corrections_applied=picklist_corrections_applied,
        template=template,
    )

    st.markdown("#### Template Readiness Summary")
    cols = st.columns(5)
    cols[0].metric(
        "Required columns",
        f"{summary['required_present']}/{summary['required_total']}",
    )
    cols[1].metric(
        "Optional included",
        str(summary["optional_included"]),
    )
    cols[2].metric(
        "Optional excluded",
        str(summary["optional_excluded"]),
    )
    picklist_counts = summary["picklist_summary"]
    picklist_detail = (
        f"Review {picklist_counts.get('Needs Review', 0)} · "
        f"Needs Action {picklist_counts.get('Needs User Action', 0)}"
    )
    cols[3].metric(
        "Picklist corrections",
        str(summary["picklist_corrections_applied"]),
        delta=picklist_detail,
        delta_color="off",
    )
    prereq_label = "Confirmed" if summary["prerequisites_confirmed"] else "Needs confirmation"
    cols[4].metric("Prerequisites", prereq_label)

    st.info(f"**Next action:** {summary['next_action']}")
    return summary
