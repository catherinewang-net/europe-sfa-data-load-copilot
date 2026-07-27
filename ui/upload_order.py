"""Visual upload order guidance — cards, progress summary, and prerequisite controls."""

from __future__ import annotations

from io import StringIO
from typing import Any

import pandas as pd
import streamlit as st

from services.constants import (
    PREREQ_STATUS_ALREADY_LOADED,
    PREREQ_STATUS_INCLUDED,
    PREREQ_STATUS_NOT_LOADED,
    PREREQ_STATUS_UNKNOWN,
)
from services.dit_ux_service import (
    PREREQ_UI_ICONS,
    PREREQ_UI_LABELS,
    SESSION_PREREQ_CONFIRMED,
    evaluate_prerequisite_gate,
)
from services.upload_order_service import (
    build_dependency_issues_report,
    build_upload_order_plan,
    build_upload_order_report_rows,
)
from ui.preparation_action_cards import render_technical_details_expander

PREREQ_OPTIONS = [
    PREREQ_STATUS_ALREADY_LOADED,
    PREREQ_STATUS_INCLUDED,
    PREREQ_STATUS_NOT_LOADED,
    PREREQ_STATUS_UNKNOWN,
]

PREREQ_OPTION_LABELS = {
    PREREQ_STATUS_ALREADY_LOADED: "Confirmed Uploaded",
    PREREQ_STATUS_INCLUDED: "Confirmed Uploaded (included in this deployment)",
    PREREQ_STATUS_NOT_LOADED: "Not Uploaded",
    PREREQ_STATUS_UNKNOWN: "Unknown",
}

STATUS_UPLOADED = "uploaded"
STATUS_READY = "ready"
STATUS_NEEDS_CONFIRMATION = "needs_confirmation"
STATUS_BLOCKED = "blocked"
STATUS_NOT_STARTED = "not_started"
STATUS_INCLUDED = "included"

STATUS_DISPLAY: dict[str, dict[str, str]] = {
    STATUS_UPLOADED: {
        "icon": "✅",
        "label": "Confirmed Uploaded",
        "explanation": "This dependency is already loaded in Salesforce.",
        "css_class": "upload-status-uploaded",
    },
    STATUS_READY: {
        "icon": "🟢",
        "label": "Ready to Upload",
        "explanation": "All prerequisites are satisfied. This file can be uploaded now.",
        "css_class": "upload-status-ready",
    },
    STATUS_NEEDS_CONFIRMATION: {
        "icon": "🟡",
        "label": "Needs Confirmation",
        "explanation": "Confirm prerequisite status before this file can be uploaded.",
        "css_class": "upload-status-needs-confirmation",
    },
    STATUS_BLOCKED: {
        "icon": "🔴",
        "label": "Not Uploaded",
        "explanation": "Required parent data must be uploaded first.",
        "css_class": "upload-status-blocked",
    },
    STATUS_NOT_STARTED: {
        "icon": "⚪",
        "label": "Unknown",
        "explanation": "Prerequisite upload status has not been confirmed.",
        "css_class": "upload-status-not-started",
    },
    STATUS_INCLUDED: {
        "icon": "🔵",
        "label": "Included in Deployment",
        "explanation": "This template is part of the current deployment batch.",
        "css_class": "upload-status-included",
    },
}

SUMMARY_KEYS = (
    STATUS_UPLOADED,
    STATUS_READY,
    STATUS_NEEDS_CONFIRMATION,
    STATUS_BLOCKED,
)


def map_prereq_to_ui_status(prereq_status: str) -> str:
    """Map service prerequisite status strings to UI status keys."""
    mapping = {
        PREREQ_STATUS_ALREADY_LOADED: STATUS_UPLOADED,
        PREREQ_STATUS_INCLUDED: STATUS_INCLUDED,
        PREREQ_STATUS_NOT_LOADED: STATUS_BLOCKED,
        PREREQ_STATUS_UNKNOWN: STATUS_NEEDS_CONFIRMATION,
    }
    return mapping.get(prereq_status, STATUS_NEEDS_CONFIRMATION)


def map_readiness_to_ui_status(readiness: str) -> str:
    """Map service step readiness to UI status keys."""
    mapping = {
        "Ready": STATUS_READY,
        "Blocked": STATUS_BLOCKED,
        "Needs Review": STATUS_NEEDS_CONFIRMATION,
    }
    return mapping.get(readiness, STATUS_NOT_STARTED)


def resolve_prerequisite_status(
    parent_template: str,
    included_templates: set[str],
    prerequisite_status: dict[str, str],
) -> str:
    """Mirror service resolution without importing private helpers."""
    if parent_template in prerequisite_status:
        return prerequisite_status[parent_template]
    if parent_template in included_templates:
        return PREREQ_STATUS_INCLUDED
    return PREREQ_STATUS_UNKNOWN


def build_step_dependencies(
    step: dict[str, Any],
    *,
    included_templates: set[str],
    prerequisite_status: dict[str, str],
) -> list[dict[str, Any]]:
    dependencies: list[dict[str, Any]] = []
    for parent in step.get("parents") or []:
        parent_template = parent.get("template")
        if not parent_template:
            continue
        prereq = resolve_prerequisite_status(
            parent_template,
            included_templates,
            prerequisite_status,
        )
        dependencies.append({
            "template": parent_template,
            "object": parent.get("object"),
            "dependency_field": parent.get("dependency_field"),
            "reason": parent.get("reason"),
            "prerequisite_status": prereq,
            "status": map_prereq_to_ui_status(prereq),
            "required": True,
        })
    return dependencies


def missing_dependency_templates(dependencies: list[dict[str, Any]]) -> list[str]:
    return [
        item["template"]
        for item in dependencies
        if item.get("status") in {STATUS_BLOCKED, STATUS_NEEDS_CONFIRMATION}
    ]


def build_upload_order_view_model(
    plan: dict[str, Any],
    *,
    deployment_templates: list[str],
    current_template: str,
    prerequisite_status: dict[str, str],
) -> dict[str, Any]:
    """Transform service plan into a UI-friendly structured model."""
    included_templates = set(deployment_templates)
    steps: list[dict[str, Any]] = []

    for step in plan.get("steps", []):
        dependencies = build_step_dependencies(
            step,
            included_templates=included_templates,
            prerequisite_status=prerequisite_status,
        )
        status = map_readiness_to_ui_status(step.get("readiness", ""))
        if (
            status == STATUS_READY
            and step.get("template") in included_templates
            and dependencies
            and all(dep.get("status") == STATUS_INCLUDED for dep in dependencies)
        ):
            status = STATUS_INCLUDED
        missing = missing_dependency_templates(dependencies)
        steps.append({
            "sequence": step.get("step"),
            "template": step.get("template"),
            "object": step.get("object"),
            "reason": step.get("reason"),
            "status": status,
            "status_display": STATUS_DISPLAY[status],
            "dependencies": dependencies,
            "missing": missing,
            "required_parent": step.get("required_parent"),
            "dependency_field": step.get("dependency_field"),
            "readiness": step.get("readiness"),
            "prerequisite_status": step.get("prerequisite_status"),
        })

    summary = compute_deployment_summary(steps)
    next_action = compute_next_recommended_action(steps, plan)
    single_file = len(deployment_templates) <= 1

    return {
        "steps": steps,
        "summary": summary,
        "next_action": next_action,
        "single_file": single_file,
        "current_template": current_template,
        "deployment_templates": deployment_templates,
        "cycles": plan.get("cycles") or [],
        "missing_parents": plan.get("missing_parents") or [],
        "issues": plan.get("issues") or [],
        "message": plan.get("message"),
        "plan": plan,
    }


def compute_deployment_summary(steps: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {key: 0 for key in SUMMARY_KEYS}
    uploaded_dependencies: set[str] = set()
    for step in steps:
        status = step.get("status", STATUS_NOT_STARTED)
        if status == STATUS_READY:
            counts[STATUS_READY] += 1
        elif status == STATUS_BLOCKED:
            counts[STATUS_BLOCKED] += 1
        elif status == STATUS_NEEDS_CONFIRMATION:
            counts[STATUS_NEEDS_CONFIRMATION] += 1
        elif status == STATUS_INCLUDED:
            counts[STATUS_READY] += 1
        for dep in step.get("dependencies", []):
            if dep.get("status") == STATUS_UPLOADED:
                uploaded_dependencies.add(dep["template"])
    counts[STATUS_UPLOADED] = len(uploaded_dependencies)
    total = len(steps)
    completed = counts[STATUS_UPLOADED] + counts[STATUS_READY]
    progress_pct = int((completed / total) * 100) if total else 0
    return {
        "counts": counts,
        "total": total,
        "progress_pct": progress_pct,
    }


def compute_next_recommended_action(
    steps: list[dict[str, Any]],
    plan: dict[str, Any],
) -> dict[str, Any]:
    if plan.get("cycles"):
        return {
            "headline": "Resolve circular dependencies before uploading.",
            "why": plan.get("message") or "Circular dependency detected in upload order.",
            "template": None,
            "microcopy": "Review the dependency chain and adjust your deployment batch.",
        }

    for step in steps:
        if step.get("status") == STATUS_BLOCKED:
            missing = step.get("missing") or []
            target = missing[0] if missing else step.get("template")
            parents = step.get("required_parent") or "parent templates"
            return {
                "headline": f"Upload {target} next.",
                "why": (
                    f"{step['template']} depends on {parents}. "
                    f"{' and '.join(missing) or 'Required parents'} still need to be loaded."
                ),
                "template": target,
                "microcopy": "One dependency left before this file is ready.",
            }

    for step in steps:
        if step.get("status") == STATUS_NEEDS_CONFIRMATION:
            unknown = [
                dep["template"]
                for dep in step.get("dependencies", [])
                if dep.get("status") == STATUS_NEEDS_CONFIRMATION
            ]
            return {
                "headline": "Confirm prerequisite status.",
                "why": (
                    f"Mark whether {', '.join(unknown) or 'parent templates'} "
                    f"are already uploaded, included in this deployment, or still missing."
                ),
                "template": step.get("template"),
                "microcopy": "You're almost there — confirm the items below.",
            }

    for step in steps:
        if step.get("status") == STATUS_READY:
            return {
                "headline": f"Upload {step['template']} next.",
                "why": step.get("reason") or "All prerequisites for this template are complete.",
                "template": step.get("template"),
                "microcopy": "Great — all prerequisites are complete.",
            }

    if steps:
        first = steps[0]
        return {
            "headline": f"Start with {first['template']}.",
            "why": first.get("reason") or "Follow the recommended upload sequence.",
            "template": first.get("template"),
            "microcopy": "Next up: your first file in the sequence.",
        }

    return {
        "headline": "No upload order steps were generated.",
        "why": "Select templates to build a deployment sequence.",
        "template": None,
        "microcopy": "",
    }


def sync_deployment_prerequisites(
    deployment_templates: list[str],
    prerequisite_status: dict[str, str] | None,
) -> dict[str, str]:
    """Reset prerequisites when deployment changes; otherwise preserve selections."""
    deployment_key = tuple(sorted(deployment_templates))
    stored_key = st.session_state.get("upload_order_deployment_key")
    if stored_key != deployment_key:
        st.session_state["upload_order_deployment_key"] = deployment_key
        st.session_state["upload_prerequisites"] = {}
        return {}

    stored = dict(st.session_state.get("upload_prerequisites") or {})
    if prerequisite_status:
        stored.update(prerequisite_status)
    return stored


def merge_prerequisite_updates(
    current: dict[str, str],
    updates: dict[str, str],
) -> dict[str, str]:
    merged = dict(current)
    merged.update(updates)
    return merged


def status_badge_html(status_key: str, *, extra: str = "") -> str:
    display = STATUS_DISPLAY.get(status_key, STATUS_DISPLAY[STATUS_NOT_STARTED])
    extra_html = f'<div class="upload-status-extra">{extra}</div>' if extra else ""
    return (
        f'<div class="upload-status-badge {display["css_class"]}" '
        f'role="status" aria-label="{display["label"]}: {display["explanation"]}">'
        f'<span class="upload-status-icon" aria-hidden="true">{display["icon"]}</span>'
        f'<span class="upload-status-label">{display["label"]}</span>'
        f'<span class="upload-status-explanation">{display["explanation"]}</span>'
        f"{extra_html}"
        f"</div>"
    )


def render_upload_order_summary(view_model: dict[str, Any]) -> None:
    summary = view_model["summary"]
    counts = summary["counts"]
    st.markdown("#### Deployment Progress")
    cols = st.columns(4)
    stat_defs = [
        (STATUS_UPLOADED, "Completed"),
        (STATUS_READY, "Ready"),
        (STATUS_NEEDS_CONFIRMATION, "Needs Confirmation"),
        (STATUS_BLOCKED, "Blocked"),
    ]
    for col, (status_key, title) in zip(cols, stat_defs):
        display = STATUS_DISPLAY[status_key]
        with col:
            st.markdown(
                f"""
                <div class="upload-summary-stat">
                    <div class="upload-summary-icon" aria-hidden="true">{display["icon"]}</div>
                    <div class="upload-summary-value">{counts[status_key]}</div>
                    <div class="upload-summary-label">{title}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    if summary["total"] > 0:
        st.progress(summary["progress_pct"] / 100)
        st.caption(
            f"{summary['progress_pct']}% of deployment steps are uploaded or ready "
            f"({summary['total']} total)."
        )


def render_next_recommended_action(view_model: dict[str, Any]) -> None:
    action = view_model["next_action"]
    st.markdown("#### Next Recommended Action")
    st.markdown(
        f"""
        <div class="upload-next-action">
            <div class="upload-next-action-headline">{action["headline"]}</div>
            <div class="upload-next-action-why"><strong>Why:</strong> {action["why"]}</div>
            {f'<div class="upload-next-action-micro">{action["microcopy"]}</div>' if action.get("microcopy") else ""}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_prerequisite_checklist(
    dependencies: list[dict[str, Any]],
    prerequisite_status: dict[str, str],
    *,
    key_prefix: str,
) -> dict[str, str]:
    """Render prerequisite radio controls and return updated statuses."""
    updated: dict[str, str] = {}
    if not dependencies:
        return updated

    for index, item in enumerate(dependencies):
        parent_template = item.get("template")
        if not parent_template:
            continue
        current = prerequisite_status.get(parent_template, PREREQ_STATUS_UNKNOWN)
        default_index = (
            PREREQ_OPTIONS.index(current) if current in PREREQ_OPTIONS else len(PREREQ_OPTIONS) - 1
        )
        prereq = prerequisite_status.get(parent_template, PREREQ_STATUS_UNKNOWN)
        display_icon = PREREQ_UI_ICONS.get(prereq, "⚪")
        display_label = PREREQ_UI_LABELS.get(prereq, "Unknown")
        st.markdown(
            f"**{parent_template}** — "
            f"{display_icon} {display_label}"
        )
        selected = st.radio(
            f"Prerequisite status for {parent_template}",
            options=PREREQ_OPTIONS,
            index=default_index,
            format_func=lambda value: PREREQ_OPTION_LABELS.get(value, value),
            key=f"{key_prefix}_prereq_{index}_{parent_template}",
            help=item.get("reason") or "Confirm whether this parent template is already available.",
            label_visibility="collapsed",
        )
        updated[parent_template] = selected
    return updated


def render_upload_order_card(
    step: dict[str, Any],
    *,
    expanded: bool,
    key_prefix: str,
    prerequisite_status: dict[str, str],
) -> dict[str, str]:
    status = step.get("status", STATUS_NOT_STARTED)
    display = step.get("status_display") or STATUS_DISPLAY[status]
    missing = step.get("missing") or []
    missing_text = ", ".join(missing) if missing else "None"
    depends_on = step.get("required_parent") or "None"

    card_header = (
        f"Step {step.get('sequence')}: {step.get('template')} — "
        f"{display['icon']} {display['label']}"
    )
    with st.expander(card_header, expanded=expanded):
        st.markdown(
            f"""
            <div class="upload-order-card">
                <div class="upload-order-card-meta">
                    <div><span class="upload-order-card-label">Salesforce Object</span>
                    <strong>{step.get("object") or "—"}</strong></div>
                    <div><span class="upload-order-card-label">Depends on</span>
                    <strong>{depends_on}</strong></div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(status_badge_html(status, extra=f"Missing: {missing_text}" if missing else ""), unsafe_allow_html=True)
        if step.get("reason"):
            st.caption(step["reason"])

        dependencies = step.get("dependencies") or []
        if dependencies:
            st.markdown("**Mark Prerequisites**")
            return render_prerequisite_checklist(
                dependencies,
                prerequisite_status,
                key_prefix=f"{key_prefix}_step_{step.get('sequence')}",
            )
    return {}


def render_upload_order_cards(
    view_model: dict[str, Any],
    prerequisite_status: dict[str, str],
) -> dict[str, str]:
    steps = view_model.get("steps") or []
    if not steps:
        st.caption("No upload order steps were generated for the selected templates.")
        return {}

    updated: dict[str, str] = {}
    single_file = view_model.get("single_file", False)

    if single_file:
        current = view_model.get("current_template")
        step = next((item for item in steps if item.get("template") == current), steps[0])
        st.markdown("**Current File**")
        st.markdown(f"### {step.get('template')}")
        st.markdown(status_badge_html(step.get("status", STATUS_NOT_STARTED)), unsafe_allow_html=True)

        dependencies = step.get("dependencies") or []
        if dependencies:
            st.markdown("**Prerequisites**")
            for dep in dependencies:
                dep_display = STATUS_DISPLAY.get(dep.get("status", STATUS_NEEDS_CONFIRMATION))
                st.markdown(
                    f"- {dep_display['icon']} **{dep['template']}** — {dep_display['label']}"
                )
            st.markdown("**Confirm prerequisite status**")
            updated.update(
                render_prerequisite_checklist(
                    dependencies,
                    prerequisite_status,
                    key_prefix="single",
                )
            )
        else:
            st.success("No unresolved parent templates were identified for this file.")
        return updated

    st.markdown("**Recommended Upload Sequence**")
    for index, step in enumerate(steps):
        expanded = step.get("status") in {STATUS_BLOCKED, STATUS_NEEDS_CONFIRMATION}
        step_updates = render_upload_order_card(
            step,
            expanded=expanded,
            key_prefix=f"multi_{index}",
            prerequisite_status=prerequisite_status,
        )
        updated.update(step_updates)
        if index < len(steps) - 1:
            st.markdown('<div class="upload-order-arrow" aria-hidden="true">↓</div>', unsafe_allow_html=True)
    return updated


def build_dependency_table_rows(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "Step": step.get("step"),
            "Template": step.get("template"),
            "Salesforce object": step.get("object"),
            "Reason": step.get("reason"),
            "Required parent": step.get("required_parent"),
            "Dependency field": step.get("dependency_field"),
            "Readiness": step.get("readiness"),
            "Prerequisite status": step.get("prerequisite_status"),
        }
        for step in plan.get("steps", [])
    ]


def render_dependency_details(plan: dict[str, Any]) -> None:
    rows = build_dependency_table_rows(plan)

    def _render_details() -> None:
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.caption("No dependency rows are available.")

        missing_parents = plan.get("missing_parents") or []
        if missing_parents:
            st.markdown("**Missing or unresolved parents**")
            st.dataframe(
                pd.DataFrame([
                    {
                        "Child template": item.get("child_template"),
                        "Parent template": item.get("parent_template"),
                        "Dependency field": item.get("dependency_field"),
                        "Reason": item.get("reason"),
                        "Status": item.get("status"),
                        "Recommended action": item.get("recommended_action"),
                    }
                    for item in missing_parents
                ]),
                use_container_width=True,
                hide_index=True,
            )

        order_rows = build_upload_order_report_rows(plan)
        if order_rows:
            order_buffer = StringIO()
            pd.DataFrame(order_rows).to_csv(order_buffer, index=False)
            st.download_button(
                "Download Upload Order Plan",
                data=order_buffer.getvalue(),
                file_name="upload_order_plan.csv",
                mime="text/csv",
                key="upload_order_plan_download",
            )

        issue_rows = build_dependency_issues_report(plan)
        if issue_rows:
            issue_buffer = StringIO()
            pd.DataFrame(issue_rows).to_csv(issue_buffer, index=False)
            st.download_button(
                "Download Dependency Issues Report",
                data=issue_buffer.getvalue(),
                file_name="dependency_issues_report.csv",
                mime="text/csv",
                key="dependency_issues_download",
            )

    render_technical_details_expander(render_fn=_render_details)


def render_upload_order_guidance(
    template: str,
    *,
    deployment_templates: list[str] | None = None,
    prerequisite_status: dict[str, str] | None = None,
) -> dict[str, str]:
    """Render upload order guidance and return updated prerequisite statuses."""
    deployment_templates = deployment_templates or [template]
    single_file = len(deployment_templates) <= 1
    section_title = "Upload Prerequisites" if single_file else "Recommended Upload Order"
    st.subheader(section_title)
    st.caption(
        "Upload order is derived from Salesforce metadata and business dependency rules. "
        "Parent files do not need to be uploaded into the Copilot if they are already loaded elsewhere."
    )

    prerequisite_status = sync_deployment_prerequisites(deployment_templates, prerequisite_status)
    included_templates = set(deployment_templates)

    reset_col, _spacer = st.columns([1, 3])
    with reset_col:
        if st.button("Reset Deployment Progress", key="reset_upload_prerequisites"):
            st.session_state["upload_prerequisites"] = {}
            st.session_state[SESSION_PREREQ_CONFIRMED] = False
            prerequisite_status = {}
            st.rerun()

    plan = build_upload_order_plan(
        deployment_templates,
        prerequisite_status=prerequisite_status,
        included_templates=included_templates,
    )

    view_model = build_upload_order_view_model(
        plan,
        deployment_templates=deployment_templates,
        current_template=template,
        prerequisite_status=prerequisite_status,
    )

    if plan.get("cycles"):
        st.error(plan.get("message"))

    if not single_file:
        render_upload_order_summary(view_model)
        render_next_recommended_action(view_model)

    updates = render_upload_order_cards(view_model, prerequisite_status)
    prerequisite_status = merge_prerequisite_updates(prerequisite_status, updates)

    all_dependencies: list[dict[str, Any]] = []
    for step in view_model.get("steps", []):
        all_dependencies.extend(step.get("dependencies") or [])

    confirmed = st.session_state.get(SESSION_PREREQ_CONFIRMED, False)
    if all_dependencies:
        confirmed = st.checkbox(
            "I confirm the required prerequisite files have already been uploaded.",
            value=confirmed,
            key="upload_prerequisites_confirmed_checkbox",
        )
        st.session_state[SESSION_PREREQ_CONFIRMED] = confirmed
        can_continue, gate_message = evaluate_prerequisite_gate(
            all_dependencies,
            prerequisite_status,
            confirmed,
        )
        if not can_continue:
            st.warning(gate_message)
        elif gate_message:
            st.info(gate_message)

    if not single_file:
        render_dependency_details(plan)

    st.session_state["upload_prerequisites"] = prerequisite_status
    return prerequisite_status
