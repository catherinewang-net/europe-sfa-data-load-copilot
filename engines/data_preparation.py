"""Structural data preparation — mapping-driven transforms only."""

from __future__ import annotations

from typing import Any

import pandas as pd

from engines.mapping_confirmation import build_column_order

STRUCTURAL_STEPS = [
    "drop_excluded_columns",
    "rename_headers",
    "populate_type",
    "add_id_column",
    "reorder_columns",
]


def build_formatting_review(
    df: pd.DataFrame,
    template_config: dict[str, Any],
    confirmed_rename_map: dict[str, str],
    excluded_columns: set[str],
    raw_csv_content: str | None = None,
) -> dict[str, Any]:
    """Deprecated — formatting detection lives in row_correction_plan_service."""
    from engines.formatting_review import detect_formatting_issues

    return detect_formatting_issues(
        df,
        template_config,
        confirmed_rename_map,
        excluded_columns,
        raw_csv_content=raw_csv_content,
    )


def apply_preparation(
    df: pd.DataFrame,
    template_config: dict[str, Any],
    load_operation: str | None,
    template_name: str,
    confirmed_rename_map: dict[str, str],
    excluded_columns: set[str],
    type_confirmed: bool,
    enabled_formatting_issue_ids: set[str] | None = None,
    formatting_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    working = df.copy()
    change_log: list[dict[str, Any]] = []
    manual_review: list[dict[str, Any]] = []
    warnings: list[str] = []

    required_type = template_config.get("required_type")
    salesforce_object = template_config.get("salesforce_object", "Account")

    stats = {
        "headers_renamed": 0,
        "type_values_changed": 0,
        "dates_converted": 0,
        "blank_rows_removed": 0,
        "whitespace_trimmed": 0,
        "leading_zeroes_restored": 0,
        "phones_normalized": 0,
        "formatting_issues_flagged": 0,
        "rows_requiring_manual_review": 0,
    }

    cols_to_drop = [c for c in excluded_columns if c in working.columns]
    if cols_to_drop:
        working.drop(columns=cols_to_drop, inplace=True)
        for col in cols_to_drop:
            change_log.append({
                "category": "rename_headers",
                "row": None,
                "field": col,
                "original_value": col,
                "new_value": "",
                "reason": "Column excluded from Workbench output (Do Not Include)",
            })

    stats["headers_renamed"] = _rename_columns(working, confirmed_rename_map, change_log)

    if required_type and type_confirmed:
        stats["type_values_changed"] = _apply_type_column(
            working, required_type, template_name, change_log
        )

    _ensure_id_column(working, load_operation, change_log, warnings)
    _check_id_requirements(working, load_operation, manual_review, warnings)

    confirmed_api_fields = list(confirmed_rename_map.values())
    if type_confirmed and required_type and "Type" not in confirmed_api_fields:
        confirmed_api_fields.append("Type")
    if "Id" in working.columns:
        if "Id" not in confirmed_api_fields:
            confirmed_api_fields.insert(0, "Id")

    column_order = build_column_order(confirmed_api_fields, salesforce_object)
    working = _reorder_columns(working, column_order)

    stats["rows_requiring_manual_review"] = len(manual_review)

    return {
        "corrected_df": working,
        "change_log": change_log,
        "manual_review": manual_review,
        "warnings": warnings,
        "stats": stats,
        "formatting_applied": [],
        "confirmed_api_fields": list(working.columns),
    }


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _rename_columns(
    df: pd.DataFrame,
    confirmed_rename_map: dict[str, str],
    change_log: list[dict],
) -> int:
    rename_map = {
        dit: api
        for dit, api in confirmed_rename_map.items()
        if dit in df.columns and dit != api
    }
    for dit, api in rename_map.items():
        change_log.append({
            "category": "rename_headers",
            "row": None,
            "field": dit,
            "original_value": dit,
            "new_value": api,
            "reason": "Confirmed mapping: DIT header renamed to Salesforce API field",
        })
    if rename_map:
        df.rename(columns=rename_map, inplace=True)
    return len(rename_map)


def _apply_type_column(
    df: pd.DataFrame,
    required_type: str,
    template_name: str,
    change_log: list[dict],
) -> int:
    changes = 0
    if "Type" not in df.columns:
        df["Type"] = required_type
        for idx in df.index:
            change_log.append({
                "category": "populate_type",
                "row": idx + 2,
                "field": "Type",
                "original_value": "",
                "new_value": required_type,
                "reason": f"Type populated for Account template ({template_name})",
            })
            changes += 1
        return changes

    for idx, value in df["Type"].items():
        text = "" if _is_blank(value) else str(value).strip()
        if not text or text != required_type:
            change_log.append({
                "category": "populate_type",
                "row": idx + 2,
                "field": "Type",
                "original_value": text,
                "new_value": required_type,
                "reason": f"Type corrected for Account template ({template_name})",
            })
            df.at[idx, "Type"] = required_type
            changes += 1
    return changes


def _ensure_id_column(
    df: pd.DataFrame,
    load_operation: str | None,
    change_log: list[dict],
    warnings: list[str],
) -> None:
    if not load_operation or load_operation == "Insert":
        return
    if "Id" in df.columns:
        return
    df.insert(0, "Id", "")
    change_log.append({
        "category": "add_id_column",
        "row": None,
        "field": "Id",
        "original_value": "",
        "new_value": "",
        "reason": "Id column added for Workbench load",
    })
    if load_operation == "Insert":
        warnings.append("Id column added and left blank for insert operation.")


def _check_id_requirements(
    df: pd.DataFrame,
    load_operation: str | None,
    manual_review: list[dict],
    warnings: list[str],
) -> None:
    if not load_operation or load_operation != "Update":
        if load_operation == "Insert" and "Id" in df.columns:
            if df["Id"].apply(lambda v: not _is_blank(v)).any():
                warnings.append(
                    "Insert operation selected but Id column contains values. "
                    "These were left unchanged."
                )
        return

    if "Id" not in df.columns:
        for idx in df.index:
            manual_review.append({
                "row": idx + 2,
                "field": "Id",
                "value": "",
                "reason": "Update operation requires Id to be populated manually",
            })
        return

    for idx, value in df["Id"].items():
        if _is_blank(value):
            manual_review.append({
                "row": idx + 2,
                "field": "Id",
                "value": "",
                "reason": "Update operation requires Id to be populated manually",
            })


def _reorder_columns(df: pd.DataFrame, column_order: list[str]) -> pd.DataFrame:
    ordered = [c for c in column_order if c in df.columns]
    for col in df.columns:
        if col not in ordered:
            ordered.append(col)
    return df[ordered]
