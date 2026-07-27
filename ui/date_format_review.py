"""Date format review and approval UI."""

from __future__ import annotations

import streamlit as st

from services.date_conversion_service import (
    SOURCE_FORMAT_DIT,
    SOURCE_FORMAT_US,
    SOURCE_FORMAT_WORKBENCH,
    STATUS_VALID,
    build_date_conversion_plan,
    default_source_format,
    display_status,
)
from ui.preparation_action_cards import format_issue_details, render_action_card

SOURCE_FORMAT_OPTIONS = [
    SOURCE_FORMAT_DIT,
    SOURCE_FORMAT_WORKBENCH,
    SOURCE_FORMAT_US,
]


def _build_date_details(plan: dict) -> str:
    """Build technical date-conversion details for the expander."""
    detail_rows: list[dict] = []
    for column, column_plan in plan.get("columns", {}).items():
        summary = column_plan["summary"]
        detail_rows.append({
            "field": column,
            "reason": (
                f"target `{column_plan['target_format']}` ({column_plan['field_type']}); "
                f"detected {summary['detected']}, convertible {summary['can_convert']}, "
                f"ambiguous {summary['ambiguous']}, invalid "
                f"{summary['invalid'] + summary['excel_serial']}"
            ),
        })
        for row in column_plan.get("rows", []):
            if row["status"] in {STATUS_VALID, "already_correct", "blank"}:
                continue
            detail_rows.append({
                "row": row["row"],
                "field": column,
                "reason": display_status(row["status"]),
                "original_value": row["original_value"],
                "proposed_value": row["proposed_value"],
            })
    return format_issue_details(detail_rows, limit=50)


def render_date_format_review(
    df,
    date_field_types: dict[str, str],
    upload_method: str,
    *,
    session_key_prefix: str = "date_format",
) -> dict | None:
    """
    Show source-format selection, per-column conversion stats, and approval controls.

    Returns approval payload or None while waiting for user action.
    """
    if not date_field_types:
        return {"approved": True, "declined": False, "source_format": default_source_format(upload_method), "plan": None}

    default_source = st.session_state.get(
        "source_date_format",
        default_source_format(upload_method),
    )
    selected_source = st.selectbox(
        "Source date format for ambiguous values",
        options=SOURCE_FORMAT_OPTIONS,
        index=SOURCE_FORMAT_OPTIONS.index(default_source)
        if default_source in SOURCE_FORMAT_OPTIONS
        else 0,
        help=(
            "DIT uploads typically use DD/MM/YYYY. Workbench uploads typically use YYYY-MM-DD. "
            "Select US (MM/DD/YYYY) when your file uses US-style slash dates."
        ),
        key=f"{session_key_prefix}_source_format",
        label_visibility="collapsed",
    )
    st.session_state["source_date_format"] = selected_source

    plan = build_date_conversion_plan(
        df,
        date_field_types,
        upload_method,
        source_format=selected_source,
    )
    st.session_state["date_conversion_plan"] = plan

    if not plan["columns"]:
        st.info("No date fields detected in the mapped columns.")
        if st.button("Continue", type="primary", key=f"{session_key_prefix}_continue_none"):
            return {
                "approved": True,
                "declined": False,
                "source_format": selected_source,
                "plan": plan,
            }
        return None

    convertible = sum(
        column_plan["summary"]["can_convert"]
        for column_plan in plan["columns"].values()
    )
    blocking = plan["has_blocking"]
    ambiguous = plan["has_ambiguous"]
    dates_applied = bool(st.session_state.get("date_conversions_approved"))

    description = (
        f"{convertible} date value(s) can be converted to the template format."
        if convertible
        else "Review date values before continuing."
    )
    if blocking:
        st.warning("Invalid or Excel serial date values require manual review before download.")
    if ambiguous and not selected_source:
        st.warning("Select a source date format to resolve ambiguous slash dates.")

    if render_action_card(
        "📅 Convert Dates",
        description,
        "✓ Convert Dates",
        key=f"{session_key_prefix}_convert_dates",
        details=_build_date_details(plan),
        applied=dates_applied,
        success_message="✅ Date values converted to the template format.",
        disabled=blocking,
    ):
        st.session_state["date_conversions_approved"] = True
        return {
            "approved": True,
            "declined": False,
            "source_format": selected_source,
            "plan": plan,
        }

    if st.button("Skip Date Conversions", key=f"{session_key_prefix}_skip"):
        st.session_state["date_conversions_approved"] = False
        return {
            "approved": False,
            "declined": True,
            "source_format": selected_source,
            "plan": plan,
        }

    return None
