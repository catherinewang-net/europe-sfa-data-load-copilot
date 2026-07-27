"""Build and apply Workbench preparation plans from confirmed field mappings."""

from __future__ import annotations

from typing import Any

import pandas as pd

from core.config import CORRECTION_CATEGORIES, REQUIREDNESS
from engines.data_preparation import apply_preparation
from services.row_correction_plan_service import apply_row_corrections
from services.template_service import resolve_template
from services.workbench_mapping_service import (
    build_mapping_report,
    get_confirmed_rename_map,
    get_excluded_columns,
)


def build_workbench_preparation_plan(
    df: pd.DataFrame,
    mapping_rows: list[dict[str, Any]],
    template: str,
    load_operation: str | None,
    type_confirmed: bool,
    row_correction_plan: dict[str, Any] | None = None,
    mapping_applied: bool = False,
) -> dict[str, Any]:
    """Build an approvable Workbench preparation plan after mappings are confirmed."""
    context = resolve_template(template)
    rename_map = {} if mapping_applied else get_confirmed_rename_map(mapping_rows)
    excluded = set() if mapping_applied else get_excluded_columns(mapping_rows)
    changes: list[dict[str, Any]] = []

    for uploaded, api_field in rename_map.items():
        if uploaded == api_field:
            continue
        changes.append({
            "change_id": f"rename:{uploaded}->{api_field}",
            "category": "rename",
            "title": CORRECTION_CATEGORIES["rename"],
            "description": f"Rename `{uploaded}` to `{api_field}`",
            "source_column": uploaded,
            "target_column": api_field,
            "safe": False,
            "requires_confirmation": True,
            "blocking": False,
            "requiredness": REQUIREDNESS["BUSINESS"],
        })

    if context and context.is_account_template and type_confirmed and "Type" not in df.columns:
        type_value = context.required_type_value or "Customer"
        changes.append({
            "change_id": "generated:Type",
            "category": "add_generated_value",
            "title": CORRECTION_CATEGORIES["add_generated_value"],
            "description": f"Add Type = {type_value}",
            "target_column": "Type",
            "generated_value": type_value,
            "safe": False,
            "requires_confirmation": True,
            "blocking": False,
            "requiredness": REQUIREDNESS["COPILOT"],
        })

    if excluded:
        for column in sorted(excluded):
            changes.append({
                "change_id": f"exclude:{column}",
                "category": "exclude_extra_column",
                "title": CORRECTION_CATEGORIES["exclude_extra_column"],
                "description": f"Exclude column `{column}` from Workbench output",
                "source_column": column,
                "safe": False,
                "requires_confirmation": True,
                "blocking": False,
                "requiredness": REQUIREDNESS["OPTIONAL"],
            })

    projected_headers = _project_headers(df.columns.tolist(), rename_map, excluded, changes)
    if projected_headers:
        changes.append({
            "change_id": "reorder:columns",
            "category": "reorder_columns",
            "title": CORRECTION_CATEGORIES["reorder_columns"],
            "description": f"Reorder {len(projected_headers)} columns for Workbench output",
            "column_order": projected_headers,
            "safe": True,
            "requires_confirmation": False,
            "blocking": False,
            "requiredness": REQUIREDNESS["OPTIONAL"],
        })

    if row_correction_plan:
        for issue in row_correction_plan.get("issues", []):
            if not issue.get("auto_fixable"):
                continue
            if issue.get("category") != "convert_dates":
                continue
            changes.append({
                "change_id": f"row:{issue['issue_id']}",
                "category": "convert_dates",
                "title": "Convert dates",
                "description": issue.get("description", "Convert dates to YYYY-MM-DD"),
                "issue_id": issue["issue_id"],
                "safe": False,
                "requires_confirmation": True,
                "blocking": False,
                "requiredness": REQUIREDNESS["OPTIONAL"],
            })

        blank_row_count = row_correction_plan.get("summary", {}).get("blank_rows", {}).get("count", 0)
        if blank_row_count:
            changes.append({
                "change_id": "row:remove_blank_rows",
                "category": "remove_blank_rows",
                "title": "Remove blank rows",
                "description": f"Remove {blank_row_count} blank row(s)",
                "safe": False,
                "requires_confirmation": True,
                "blocking": False,
                "requiredness": REQUIREDNESS["OPTIONAL"],
            })

    summary = _build_summary(changes)
    safe_changes = [change for change in changes if change.get("safe")]
    confirmation_changes = [
        change for change in changes
        if change.get("requires_confirmation") and not change.get("safe")
    ]

    return {
        "upload_method": "Workbench",
        "template": template,
        "load_operation": load_operation,
        "changes": changes,
        "safe_changes": safe_changes,
        "confirmation_changes": confirmation_changes,
        "manual_review": [],
        "summary": summary,
        "has_fixable_changes": bool(safe_changes or confirmation_changes),
        "has_blocking_manual_review": False,
        "corrections_applied": False,
        "corrections_declined": False,
        "mapping_rows": mapping_rows,
        "type_confirmed": type_confirmed,
        "row_correction_plan": row_correction_plan,
    }


def apply_workbench_preparation(
    original_df: pd.DataFrame,
    preparation_plan: dict[str, Any],
    enabled_change_ids: set[str],
    mapping_rows: list[dict[str, Any]],
    type_confirmed: bool,
    row_correction_plan: dict[str, Any] | None = None,
    enabled_row_issue_ids: set[str] | None = None,
    mapped_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Apply an approved Workbench preparation plan to a copy of the uploaded file."""
    context = resolve_template(preparation_plan["template"])
    template_mapping = _build_runtime_template_mapping(context, context.fallback_config if context else None)
    if not template_mapping:
        raise ValueError(f"No runtime template mapping available for: {preparation_plan['template']}")

    working = (mapped_df if mapped_df is not None else original_df).copy()
    mapping_applied = mapped_df is not None
    change_log: list[dict[str, Any]] = []

    enabled_row_ids = enabled_row_issue_ids or set()
    if row_correction_plan:
        enabled_row_ids.update(
            change["issue_id"]
            for change in preparation_plan.get("changes", [])
            if change.get("change_id") in enabled_change_ids and change.get("issue_id")
        )
        if "row:remove_blank_rows" in enabled_change_ids:
            enabled_row_ids.update(
                issue["issue_id"]
                for issue in row_correction_plan.get("issues", [])
                if issue.get("category") == "blank_rows"
            )

    if row_correction_plan and enabled_row_ids:
        working, row_change_log = apply_row_corrections(
            working,
            row_correction_plan,
            enabled_row_ids,
        )
        change_log.extend(row_change_log)

    preparation_result = apply_preparation(
        working,
        template_mapping,
        preparation_plan["load_operation"],
        preparation_plan["template"],
        confirmed_rename_map={} if mapping_applied else get_confirmed_rename_map(mapping_rows),
        excluded_columns=set() if mapping_applied else get_excluded_columns(mapping_rows),
        type_confirmed=type_confirmed,
    )
    corrected_df = preparation_result["corrected_df"]
    change_log.extend(preparation_result.get("change_log", []))

    return {
        "original_df": original_df.copy(),
        "proposed_df": working.copy(),
        "corrected_df": corrected_df,
        "change_log": change_log,
        "manual_review": preparation_result.get("manual_review", []),
        "warnings": preparation_result.get("warnings", []),
        "stats": preparation_result.get("stats", {}),
        "mapping_report": build_mapping_report(mapping_rows),
        "formatting_applied": preparation_result.get("formatting_applied", []),
        "confirmed_api_fields": list(corrected_df.columns),
        "preparation_plan": {
            **preparation_plan,
            "corrections_applied": True,
            "enabled_change_ids": sorted(enabled_change_ids),
        },
        "row_correction_plan": row_correction_plan,
    }


def get_fixable_change_ids(plan: dict[str, Any]) -> set[str]:
    return {
        change["change_id"]
        for change in plan.get("changes", [])
        if change.get("safe") or change.get("requires_confirmation")
    }


def get_safe_change_ids(plan: dict[str, Any]) -> set[str]:
    return {change["change_id"] for change in plan.get("safe_changes", [])}


def get_header_rename_change_ids(plan: dict[str, Any]) -> set[str]:
    return {
        change["change_id"]
        for change in plan.get("changes", [])
        if change.get("category") == "rename"
    }


def _project_headers(
    uploaded_headers: list[str],
    rename_map: dict[str, str],
    excluded: set[str],
    changes: list[dict[str, Any]],
) -> list[str]:
    headers = [header for header in uploaded_headers if header not in excluded]
    headers = [rename_map.get(header, header) for header in headers]
    for change in changes:
        if change["category"] == "add_generated_value" and change["target_column"] not in headers:
            headers.append(change["target_column"])
    return headers


def _build_runtime_template_mapping(context, fallback_config):
    if not context or not context.salesforce_object:
        return None

    runtime = {
        "salesforce_object": context.salesforce_object,
        "required_type": context.required_type_value,
    }

    if context.template_definition:
        runtime["column_mappings"] = {
            csv_label: {"suggested_api_field": api_name, "default_status": "needs_confirmation"}
            for csv_label, api_name in context.template_definition.csv_label_to_api.items()
        }

    if fallback_config:
        if "column_mappings" not in runtime:
            runtime["column_mappings"] = fallback_config.get("column_mappings", {})
        runtime.setdefault("date_fields", fallback_config.get("date_fields", []))

    return runtime


def _build_summary(changes: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        "rename": 0,
        "reorder_columns": 0,
        "add_generated_value": 0,
        "convert_dates": 0,
        "remove_blank_rows": 0,
        "exclude_extra_column": 0,
    }
    for change in changes:
        category = change["category"]
        if category in summary:
            summary[category] += 1
    return summary
