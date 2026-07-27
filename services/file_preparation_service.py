"""Apply approved correction-plan changes to a copy of the uploaded file."""

from __future__ import annotations

from typing import Any

import pandas as pd

from engines.data_preparation import apply_preparation
from engines.mapping_confirmation import build_mapping_report, get_confirmed_rename_map, get_excluded_columns
from services.correction_plan_service import build_correction_plan
from services.row_correction_plan_service import apply_row_corrections
from services.template_service import resolve_template


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
        runtime["date_fields"] = [
            csv_label
            for csv_label in context.template_definition.api_to_csv_label.values()
            if "date" in csv_label.lower()
        ]

    if fallback_config:
        runtime.setdefault("date_fields", fallback_config.get("date_fields", []))
        if "column_mappings" not in runtime:
            runtime["column_mappings"] = fallback_config.get("column_mappings", {})

    return runtime


def prepare_file(
    original_df: pd.DataFrame,
    uploaded_headers: list[str],
    upload_method: str,
    template: str,
    load_operation: str | None,
    correction_plan: dict[str, Any],
    enabled_change_ids: set[str],
    mapping_rows: list[dict] | None = None,
    type_confirmed: bool = False,
    enabled_formatting_issue_ids: set[str] | None = None,
    formatting_review: dict[str, Any] | None = None,
    row_correction_plan: dict[str, Any] | None = None,
    enabled_row_issue_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Apply approved structural corrections and optional Workbench preparation."""
    proposed_df = apply_correction_changes(original_df, correction_plan, enabled_change_ids)
    corrected_df = proposed_df.copy()
    change_log = list(build_change_log(correction_plan, enabled_change_ids))
    manual_review = [
        dict(item)
        for item in correction_plan.get("manual_review", [])
        if not _manual_issue_resolved(item, enabled_change_ids, correction_plan)
    ]

    if row_correction_plan and enabled_row_issue_ids:
        corrected_df, row_change_log = apply_row_corrections(
            corrected_df,
            row_correction_plan,
            enabled_row_issue_ids,
        )
        change_log.extend(row_change_log)

    preparation_result: dict[str, Any] | None = None
    if upload_method == "Workbench" and mapping_rows and load_operation:
        context = resolve_template(template)
        template_mapping = _build_runtime_template_mapping(
            context,
            context.fallback_config if context else None,
        )
        if template_mapping:
            preparation_result = apply_preparation(
                corrected_df,
                template_mapping,
                load_operation,
                template,
                confirmed_rename_map=get_confirmed_rename_map(mapping_rows),
                excluded_columns=get_excluded_columns(mapping_rows),
                type_confirmed=type_confirmed,
                enabled_formatting_issue_ids=enabled_formatting_issue_ids,
                formatting_review=formatting_review,
            )
            corrected_df = preparation_result["corrected_df"]
            change_log.extend(preparation_result.get("change_log", []))
            manual_review.extend(preparation_result.get("manual_review", []))

    stats = _build_stats(change_log, correction_plan, enabled_change_ids)

    return {
        "original_df": original_df.copy(),
        "proposed_df": proposed_df,
        "corrected_df": corrected_df,
        "change_log": change_log,
        "manual_review": manual_review,
        "warnings": preparation_result.get("warnings", []) if preparation_result else [],
        "stats": stats,
        "mapping_report": build_mapping_report(mapping_rows or []),
        "formatting_applied": preparation_result.get("formatting_applied", []) if preparation_result else [],
        "confirmed_api_fields": list(corrected_df.columns),
        "correction_plan": {
            **correction_plan,
            "corrections_applied": True,
            "enabled_change_ids": sorted(enabled_change_ids),
        },
        "row_correction_plan": {
            **(row_correction_plan or {}),
            "corrections_applied": bool(enabled_row_issue_ids),
            "enabled_issue_ids": sorted(enabled_row_issue_ids or []),
        } if row_correction_plan else None,
    }


def apply_correction_changes(
    original_df: pd.DataFrame,
    correction_plan: dict[str, Any],
    enabled_change_ids: set[str],
) -> pd.DataFrame:
    """Apply enabled correction-plan items to a dataframe copy."""
    working = original_df.copy()
    changes_by_id = {
        change["change_id"]: change
        for change in correction_plan.get("changes", [])
    }

    for change_id in _ordered_change_ids(correction_plan, enabled_change_ids):
        change = changes_by_id.get(change_id)
        if not change:
            continue
        working = _apply_single_change(working, change)

    return working


def build_change_log(
    correction_plan: dict[str, Any],
    enabled_change_ids: set[str],
) -> list[dict[str, Any]]:
    log: list[dict[str, Any]] = []
    for change in correction_plan.get("changes", []):
        if change["change_id"] not in enabled_change_ids:
            continue
        entry = {
            "category": change["category"],
            "row": None,
            "field": change.get("target_column") or change.get("source_column"),
            "original_value": change.get("source_column") or "",
            "new_value": change.get("target_column") or change.get("generated_value") or "",
            "reason": change.get("description", change.get("title", "")),
        }
        log.append(entry)
    return log


def rebuild_correction_plan(
    original_df: pd.DataFrame,
    uploaded_headers: list[str],
    upload_method: str,
    template: str,
    load_operation: str | None,
    comparison_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_correction_plan(
        original_df,
        uploaded_headers,
        upload_method,
        template,
        load_operation,
        comparison_result,
    )


def _ordered_change_ids(
    correction_plan: dict[str, Any],
    enabled_change_ids: set[str],
) -> list[str]:
    priority = {
        "rename": 1,
        "exclude_extra_column": 2,
        "add_generated_value": 3,
        "add_empty_optional_column": 4,
        "reorder_columns": 5,
    }
    enabled = [
        change["change_id"]
        for change in correction_plan.get("changes", [])
        if change["change_id"] in enabled_change_ids
    ]
    return sorted(
        enabled,
        key=lambda change_id: priority.get(
            next(
                (
                    change["category"]
                    for change in correction_plan.get("changes", [])
                    if change["change_id"] == change_id
                ),
                "rename",
            ),
            99,
        ),
    )


def _apply_single_change(df: pd.DataFrame, change: dict[str, Any]) -> pd.DataFrame:
    category = change["category"]
    if category == "rename":
        source = change["source_column"]
        target = change["target_column"]
        if source in df.columns and source != target:
            df = df.rename(columns={source: target})
        return df

    if category == "exclude_extra_column":
        source = change["source_column"]
        if source in df.columns:
            return df.drop(columns=[source])
        return df

    if category == "add_generated_value":
        target = change["target_column"]
        value = change.get("generated_value", "")
        df = df.copy()
        df[target] = value
        return df

    if category == "add_empty_optional_column":
        target = change["target_column"]
        if target not in df.columns:
            df = df.copy()
            df[target] = ""
        return df

    if category == "reorder_columns":
        order = change.get("column_order") or list(df.columns)
        ordered = [column for column in order if column in df.columns]
        for column in df.columns:
            if column not in ordered:
                ordered.append(column)
        return df[ordered]

    return df


def _manual_issue_resolved(
    issue: dict[str, Any],
    enabled_change_ids: set[str],
    correction_plan: dict[str, Any],
) -> bool:
    target = issue.get("target_column")
    if not target:
        return False
    for change in correction_plan.get("changes", []):
        if change.get("target_column") != target:
            continue
        if change["change_id"] in enabled_change_ids:
            return change["category"] != "required_data_missing"
    return False


def _build_stats(
    change_log: list[dict[str, Any]],
    correction_plan: dict[str, Any],
    enabled_change_ids: set[str],
) -> dict[str, int]:
    enabled_changes = [
        change for change in correction_plan.get("changes", [])
        if change["change_id"] in enabled_change_ids
    ]
    return {
        "headers_renamed": sum(1 for change in enabled_changes if change["category"] == "rename"),
        "columns_reordered": sum(1 for change in enabled_changes if change["category"] == "reorder_columns"),
        "generated_columns_added": sum(
            1 for change in enabled_changes if change["category"] == "add_generated_value"
        ),
        "optional_columns_added": sum(
            1 for change in enabled_changes if change["category"] == "add_empty_optional_column"
        ),
        "columns_excluded": sum(1 for change in enabled_changes if change["category"] == "exclude_extra_column"),
        "dates_converted": sum(1 for entry in change_log if entry["category"] == "convert_dates"),
        "blank_rows_removed": sum(1 for entry in change_log if entry["category"] == "remove_blank_rows"),
        "whitespace_trimmed": sum(1 for entry in change_log if entry["category"] == "trim_whitespace"),
        "leading_zeroes_restored": sum(
            1 for entry in change_log if entry["category"] == "restore_leading_zeroes"
        ),
        "phones_normalized": sum(1 for entry in change_log if entry["category"] == "normalize_phone"),
        "formatting_issues_flagged": 0,
        "rows_requiring_manual_review": len(correction_plan.get("manual_review", [])),
    }
