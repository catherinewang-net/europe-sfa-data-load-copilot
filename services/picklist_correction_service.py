"""Apply user-approved picklist value replacements."""

from __future__ import annotations

from typing import Any

import pandas as pd

from services.constants import (
    PICKLIST_STATUS_INVALID,
    PICKLIST_STATUS_MULTI_INVALID,
    PICKLIST_STATUS_NEEDS_REVIEW,
)
from services.field_mapping_service import get_confirmed_rename_map
from validators.picklist_validator import validate_picklists


def _infer_use_mapped_columns(mapped_df: pd.DataFrame, mapping_rows: list[dict[str, Any]]) -> bool:
    rename_map = get_confirmed_rename_map(mapping_rows)
    if not rename_map:
        return False
    if any(column in rename_map for column in mapped_df.columns):
        return False
    if any(column in rename_map.values() for column in mapped_df.columns):
        return True
    return False


from services.constants import (
    PICKLIST_STATUS_INVALID,
    PICKLIST_STATUS_MULTI_INVALID,
    PICKLIST_STATUS_NEEDS_REVIEW,
    PICKLIST_STATUS_NEEDS_USER_ACTION,
)


def is_whitespace_only_picklist_issue(issue: dict[str, Any]) -> bool:
    """Return True when the issue is a whitespace-trim suggestion only."""
    if issue.get("status") != PICKLIST_STATUS_NEEDS_REVIEW:
        return False
    reason = (issue.get("reason") or "").lower()
    return "trimming whitespace" in reason and bool(issue.get("suggested_replacement"))


def build_picklist_correction_plan(
    picklist_validation: dict[str, Any],
    mapped_df: pd.DataFrame,
) -> dict[str, Any]:
    """Build an approvable plan from invalid or whitespace-trim picklist issues."""
    corrections: list[dict[str, Any]] = []
    for issue in picklist_validation.get("issues", []):
        if issue.get("status") not in {
            PICKLIST_STATUS_NEEDS_USER_ACTION,
            PICKLIST_STATUS_INVALID,
            PICKLIST_STATUS_MULTI_INVALID,
            PICKLIST_STATUS_NEEDS_REVIEW,
        }:
            continue

        if is_whitespace_only_picklist_issue(issue):
            suggested = issue.get("suggested_replacement")
            corrections.append({
                **issue,
                "correction_id": issue["issue_id"],
                "column_name": _resolve_correction_column(issue, mapped_df),
                "uploaded_column": issue.get("uploaded_column"),
                "salesforce_api_field": issue.get("salesforce_api_field"),
                "original_value": issue["uploaded_value"],
                "proposed_value": suggested,
                "requires_user_selection": False,
                "is_whitespace_trim": True,
            })
            continue

        corrections.append({
            **issue,
            "correction_id": issue["issue_id"],
            "column_name": _resolve_correction_column(issue, mapped_df),
            "uploaded_column": issue.get("uploaded_column"),
            "salesforce_api_field": issue.get("salesforce_api_field"),
            "original_value": issue["uploaded_value"],
            "proposed_value": None,
            "requires_user_selection": True,
            "is_whitespace_trim": False,
        })

    return {
        "corrections": corrections,
        "correctable_count": len(corrections),
        "corrections_applied": False,
        "approved_correction_ids": [],
        "source_dataframe_shape": mapped_df.shape,
    }


def apply_picklist_corrections(
    mapped_df: pd.DataFrame,
    picklist_validation: dict[str, Any],
    approved_corrections: list[dict[str, Any]],
) -> tuple[pd.DataFrame, list[dict[str, Any]], pd.DataFrame]:
    """
    Apply approved picklist replacements to a copy of mapped_df.

    Returns corrected_df, change_log, and the unchanged original mapped_df copy.
    """
    original_copy = mapped_df.copy()
    corrected_df = mapped_df.copy()
    change_log: list[dict[str, Any]] = []

    for correction in approved_corrections:
        column_name = correction["column_name"]
        row_number = correction.get("row")
        proposed_value = correction.get("proposed_value")
        if not column_name or row_number is None or proposed_value is None:
            continue
        if column_name not in corrected_df.columns:
            continue

        row_index = row_number - 2
        if row_index < 0 or row_index >= len(corrected_df):
            continue

        current_value = corrected_df.at[row_index, column_name]
        updated_value = _apply_replacement(
            current_value=str(current_value),
            original_entry=str(correction.get("original_value", "")),
            replacement=str(proposed_value),
            field_type=correction.get("field_type"),
        )
        corrected_df.at[row_index, column_name] = updated_value
        change_log.append({
            "correction_id": correction["correction_id"],
            "row": row_number,
            "friendly_column": correction.get("uploaded_column") or column_name,
            "api_field": correction.get("salesforce_api_field") or column_name,
            "column_name": column_name,
            "original": current_value,
            "original_value": current_value,
            "corrected": updated_value,
            "proposed_value": updated_value,
            "correction_type": "picklist_replacement",
            "approval_status": "approved",
            "category": "picklist_replacement",
        })

    return corrected_df, change_log, original_copy


def revalidate_picklists_after_corrections(
    corrected_df: pd.DataFrame,
    mapping_rows: list[dict[str, Any]],
    template_context,
) -> dict[str, Any]:
    """Re-run picklist validation against corrected mapped data."""
    return validate_picklists(
        corrected_df,
        mapping_rows,
        template_context,
        use_mapped_columns=_infer_use_mapped_columns(corrected_df, mapping_rows),
    )


def _resolve_correction_column(issue: dict[str, Any], mapped_df: pd.DataFrame) -> str:
    uploaded_column = issue.get("uploaded_column")
    if uploaded_column and uploaded_column in mapped_df.columns:
        return uploaded_column
    api_field = issue.get("salesforce_api_field")
    if api_field and api_field in mapped_df.columns:
        return api_field
    return issue.get("salesforce_api_field") or issue.get("uploaded_column") or ""


def _apply_replacement(
    current_value: str,
    original_entry: str,
    replacement: str,
    field_type: str | None,
) -> str:
    if field_type and field_type.lower() == "multipicklist":
        parts = [part.strip() for part in current_value.split(";")]
        updated_parts = [
            replacement if part == original_entry else part
            for part in parts
        ]
        return ";".join(updated_parts)
    return replacement
