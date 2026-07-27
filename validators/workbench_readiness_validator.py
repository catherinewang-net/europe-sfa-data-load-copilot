"""Workbench download and preparation readiness checks."""

from __future__ import annotations

from typing import Any

from services.constants import MAPPING_STATUS_CONFIRMED
from services.field_mapping_service import is_valid_api_header
from services.template_service import TemplateContext, get_relevant_skipped_files
from services.workbench_mapping_service import (
    detect_mapping_collisions,
    get_invalid_rows,
    get_unresolved_rows,
)


def evaluate_workbench_readiness(
    template_context: TemplateContext | None,
    mapping_rows: list[dict[str, Any]],
    type_confirmed: bool,
    load_operation: str | None,
    picklist_validation: dict[str, Any] | None,
    load_action_validation: dict[str, Any] | None,
    preparation_result: dict[str, Any] | None = None,
    row_correction_plan: dict[str, Any] | None = None,
    *,
    preparation_only: bool = False,
    record_existence_validation: dict[str, Any] | None = None,
    validation_result: dict[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    reasons: list[str] = []
    warnings: list[str] = []

    if template_context is None:
        return False, "No template selected.", {"reasons": ["No template selected."], "warnings": []}

    if not template_context.metadata_available and not template_context.fallback_config:
        return False, template_context.metadata_message or "Template metadata unavailable.", {
            "reasons": [template_context.metadata_message or "Template metadata unavailable."],
            "warnings": [],
        }

    if not template_context.salesforce_object:
        return False, "Salesforce object could not be resolved.", {
            "reasons": ["Salesforce object could not be resolved."],
            "warnings": [],
        }

    for collision in detect_mapping_collisions(mapping_rows):
        reasons.append(collision["message"])

    if template_context.is_account_template:
        if not template_context.account_type_valid:
            reasons.append(template_context.account_type_error or "Account.Type metadata error.")
        elif not type_confirmed:
            reasons.append("Required Account.Type logic must be approved before download.")

    for row in get_invalid_rows(mapping_rows):
        reasons.append(
            row.get("validation_error")
            or f"Invalid mapping for uploaded column '{row['uploaded_column']}'."
        )

    unresolved = get_unresolved_rows(mapping_rows)
    if unresolved:
        reasons.append("Every included uploaded column must have a confirmed Salesforce API mapping.")

    if load_operation == "Update" and not preparation_only:
        if load_action_validation and load_action_validation.get("manual_review"):
            reasons.append("Update requires Id to be populated for all rows.")
        for issue in (load_action_validation or {}).get("issues", []):
            if issue.get("severity") == "error":
                reasons.append(issue.get("message", "Update validation failed."))
        if record_existence_validation and record_existence_validation.get("blocks_download"):
            for issue in record_existence_validation.get("issues", []):
                if issue.get("severity") == "error":
                    reasons.append(issue.get("message", "Update record check failed."))
            for item in record_existence_validation.get("manual_review", []):
                reasons.append(item.get("reason", "Update record check requires manual review."))
    elif load_operation == "Insert" and not preparation_only:
        for issue in (load_action_validation or {}).get("issues", []):
            if issue.get("severity") == "error" and issue.get("field") == "Id":
                continue
            if issue.get("severity") == "error":
                reasons.append(issue.get("message", "Insert validation failed."))
        if record_existence_validation and record_existence_validation.get("blocks_download"):
            for issue in record_existence_validation.get("issues", []):
                if issue.get("severity") == "error":
                    reasons.append(issue.get("message", "Insert record check failed."))

    if preparation_only:
        warnings.append("Prepared for Workbench. Load-action-specific checks were not performed.")

    if picklist_validation and picklist_validation.get("has_blocking_issues"):
        reasons.append("Unresolved picklist validation errors remain for required fields.")

    if row_correction_plan and (
        row_correction_plan.get("has_blocking_issues")
        or row_correction_plan.get("has_blocking_manual_review")
    ):
        reasons.append("Resolve blocking row-level data quality issues before download.")

    if preparation_result:
        date_unresolved = preparation_result.get("date_unresolved", [])
        if date_unresolved:
            reasons.append(
                f"{len(date_unresolved)} unresolved date value(s) remain in the prepared file."
            )
        corrected_df = preparation_result.get("corrected_df")
        if corrected_df is not None:
            for col in corrected_df.columns:
                if not is_valid_api_header(str(col)):
                    reasons.append(f"Invalid CSV header detected: {col}")

    mapped_api_fields = {
        row.get("confirmed_api_field")
        for row in mapping_rows
        if row.get("status") == MAPPING_STATUS_CONFIRMED and row.get("confirmed_api_field")
    }
    for skipped in get_relevant_skipped_files(
        template_context,
        template_context.salesforce_object,
        mapped_api_fields,
    ):
        warnings.append(f"Skipped Salesforce metadata file requires manual review: {skipped}")

    can_download = not reasons
    message = "Ready for Workbench-ready CSV download." if can_download else reasons[0]
    return can_download, message, {"reasons": reasons, "warnings": warnings}
