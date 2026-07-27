"""Data preparation warnings UI — dependency guidance without live Salesforce checks."""

from __future__ import annotations

from typing import Any

import streamlit as st

from services.constants import (
    PREREQ_STATUS_ALREADY_LOADED,
    PREREQ_STATUS_INCLUDED,
)
from services.upload_order_service import (
    build_preparation_warnings,
    build_upload_order_plan,
    is_preparation_warning_acknowledged,
)
from ui.preparation_action_cards import render_technical_details_expander

SESSION_PREPARATION_WARNINGS_ACK = "preparation_warnings_acknowledged"


def _acknowledgement_checkbox_label(parent_template: str) -> str:
    if parent_template:
        return f"I understand {parent_template} must be uploaded first."
    return "I understand this prerequisite."


def _render_warning_details(warnings: list[dict[str, Any]]) -> None:
    for warning in warnings:
        parent_template = warning.get("parent_template", "")
        st.markdown(f"**{parent_template} → {warning.get('current_template', '')}**")
        if warning.get("reason"):
            st.markdown(f"Reason: {warning['reason']}")
        if warning.get("dependency_field"):
            st.markdown(f"Dependency field: {warning['dependency_field']}")
        if warning.get("recommended_action"):
            st.markdown(f"Recommended action: {warning['recommended_action']}")
        if warning is not warnings[-1]:
            st.divider()


def render_data_preparation_warnings(
    template: str,
    *,
    deployment_templates: list[str] | None = None,
    prerequisite_status: dict[str, str] | None = None,
    upload_order_plan: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Render dependency-based preparation warnings for a single uploaded file."""
    deployment_templates = deployment_templates or [template]
    prerequisite_status = dict(prerequisite_status or {})
    included_templates = set(deployment_templates)

    st.subheader("Data Preparation Warnings")

    if upload_order_plan is None:
        upload_order_plan = build_upload_order_plan(
            deployment_templates,
            prerequisite_status=prerequisite_status,
            included_templates=included_templates,
        )

    warnings = build_preparation_warnings(
        template,
        deployment_templates=deployment_templates,
        prerequisite_status=prerequisite_status,
        upload_order_plan=upload_order_plan,
    )

    if not warnings:
        st.success("No prerequisite upload warnings for this template.")
        st.session_state[SESSION_PREPARATION_WARNINGS_ACK] = {}
        return prerequisite_status

    acknowledged = dict(st.session_state.get(SESSION_PREPARATION_WARNINGS_ACK) or {})

    for warning in warnings:
        parent_template = warning["parent_template"]
        st.markdown(f"⚠️ {warning['message']}")

        if warning.get("already_satisfied"):
            acknowledged[parent_template] = True
            if parent_template in included_templates and parent_template != template:
                prerequisite_status[parent_template] = PREREQ_STATUS_INCLUDED
            else:
                prerequisite_status.setdefault(parent_template, PREREQ_STATUS_ALREADY_LOADED)
            continue

        checked = st.checkbox(
            _acknowledgement_checkbox_label(parent_template),
            value=acknowledged.get(parent_template, False),
            key=f"prep_warn_ack_{parent_template}",
        )
        acknowledged[parent_template] = checked
        if checked:
            prerequisite_status[parent_template] = PREREQ_STATUS_ALREADY_LOADED

    st.session_state[SESSION_PREPARATION_WARNINGS_ACK] = acknowledged
    st.session_state["upload_prerequisites"] = prerequisite_status

    all_acknowledged = all(
        is_preparation_warning_acknowledged(
            warning,
            prerequisite_status=prerequisite_status,
            preparation_warnings_acknowledged=acknowledged,
        )
        for warning in warnings
    )
    if all_acknowledged:
        st.success("✅ Warnings acknowledged.")
    else:
        st.warning("⚠️ Please acknowledge the upload prerequisites before continuing.")

    render_technical_details_expander(render_fn=lambda: _render_warning_details(warnings))
    return prerequisite_status


def preparation_warnings_ready(
    template: str,
    *,
    deployment_templates: list[str] | None = None,
    prerequisite_status: dict[str, str] | None = None,
    upload_order_plan: dict[str, Any] | None = None,
    preparation_warnings_acknowledged: dict[str, bool] | None = None,
) -> bool:
    """Return True when all preparation warnings are satisfied or acknowledged."""
    warnings = build_preparation_warnings(
        template,
        deployment_templates=deployment_templates,
        prerequisite_status=prerequisite_status,
        upload_order_plan=upload_order_plan,
    )
    acknowledged = preparation_warnings_acknowledged or {}
    prereq_status = prerequisite_status or {}
    if not warnings:
        return True
    return all(
        is_preparation_warning_acknowledged(
            warning,
            prerequisite_status=prereq_status,
            preparation_warnings_acknowledged=acknowledged,
        )
        for warning in warnings
    )
