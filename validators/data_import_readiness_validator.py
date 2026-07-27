"""Data Import Tool upload readiness checks."""

from __future__ import annotations

from typing import Any

from core.config import READINESS_STATUS
from services.template_service import TemplateContext


def evaluate_data_import_readiness(
    comparison_result: dict[str, Any] | None,
    preparation_result: dict[str, Any] | None,
    validation_result: dict[str, Any] | None,
    correction_plan: dict[str, Any] | None,
) -> dict[str, Any]:
    """Assess whether a DIT file is ready for download after approved corrections."""
    reasons: list[str] = []
    warnings: list[str] = []
    status = READINESS_STATUS["READY"]

    comparison = (comparison_result or {}).get("comparison", {})
    if comparison.get("missing_columns"):
        reasons.append(
            "Required template columns are still missing: "
            + ", ".join(comparison["missing_columns"])
        )

    optional_missing = comparison.get("optional_missing_columns") or []
    if optional_missing and not comparison.get("missing_columns"):
        warnings.append(
            "Optional template columns were not included; this does not block readiness."
        )

    if correction_plan:
        if correction_plan.get("has_blocking_manual_review") and not correction_plan.get("corrections_applied"):
            status = READINESS_STATUS["NEEDS_USER_ACTION"]
            reasons.append("Manual review items must be resolved before upload.")
        elif correction_plan.get("has_fixable_changes") and not correction_plan.get("corrections_applied"):
            status = READINESS_STATUS["NEEDS_USER_ACTION"]
            warnings.append("Approve the Data Import Tool preparation plan before download.")

    if preparation_result and preparation_result.get("manual_review"):
        status = READINESS_STATUS["NEEDS_USER_ACTION"]
        reasons.append("Resolve manual review items before downloading the corrected file.")

    if preparation_result and preparation_result.get("date_unresolved"):
        status = READINESS_STATUS["NOT_READY"]
        reasons.append(
            f"{len(preparation_result['date_unresolved'])} unresolved date value(s) remain."
        )

    validation = validation_result or {}
    dependencies = validation.get("dependencies", {})
    blocking_dependencies = [
        item for item in dependencies.get("manual_review", [])
        if item.get("blocking")
    ]
    if blocking_dependencies:
        reasons.append(
            f"{len(blocking_dependencies)} cross-template dependency issue(s) require manual review."
        )

    if validation.get("has_blocking_issues") and not blocking_dependencies:
        reasons.append("Validation reported blocking issues.")

    if reasons:
        if status == READINESS_STATUS["READY"]:
            status = READINESS_STATUS["NOT_READY"]

    return {
        "status": status,
        "reasons": reasons,
        "warnings": warnings,
        "can_download": not reasons,
        "message": reasons[0] if reasons else "Ready for Data Import Tool CSV download.",
    }


def evaluate_data_import_download_readiness(
    template_context: TemplateContext | None,
    mapping_rows: list[dict[str, Any]],
    picklist_validation: dict[str, Any] | None,
    load_action_validation: dict[str, Any] | None,
    preparation_result: dict[str, Any] | None = None,
    row_correction_plan: dict[str, Any] | None = None,
    *,
    validation_result: dict[str, Any] | None = None,
    record_existence_validation: dict[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Unified DIT download gate aligned with preparation readiness checks."""
    reasons: list[str] = []
    warnings: list[str] = []

    if template_context is None:
        return False, "No template selected.", {"reasons": ["No template selected."], "warnings": []}

    if not template_context.metadata_available and not template_context.fallback_config:
        message = template_context.metadata_message or "Template metadata unavailable."
        return False, message, {"reasons": [message], "warnings": []}

    if picklist_validation and picklist_validation.get("has_blocking_issues"):
        reasons.append("Unresolved picklist validation errors remain for required fields.")

    if row_correction_plan and (
        row_correction_plan.get("has_blocking_issues")
        or row_correction_plan.get("has_blocking_manual_review")
    ):
        reasons.append("Resolve blocking row-level data quality issues before download.")

    if preparation_result:
        manual_review = preparation_result.get("manual_review", [])
        if manual_review:
            reasons.append("Resolve manual review items before downloading the corrected file.")
        date_unresolved = preparation_result.get("date_unresolved", [])
        if date_unresolved:
            reasons.append(
                f"{len(date_unresolved)} unresolved date value(s) remain in the prepared file."
            )

    validation = validation_result or {}
    dependencies = validation.get("dependencies", {})
    blocking_dependencies = [
        item for item in dependencies.get("manual_review", [])
        if item.get("blocking")
    ]
    if blocking_dependencies:
        reasons.append(
            f"{len(blocking_dependencies)} cross-template dependency issue(s) require manual review."
        )

    if validation.get("has_blocking_issues") and not blocking_dependencies:
        reasons.append("Validation reported blocking issues.")

    if record_existence_validation and record_existence_validation.get("blocks_download"):
        for issue in record_existence_validation.get("issues", []):
            if issue.get("severity") == "error":
                reasons.append(issue.get("message", "Record existence check failed."))
        for item in record_existence_validation.get("manual_review", []):
            reasons.append(item.get("reason", "Record existence check requires manual review."))

    if load_action_validation:
        for issue in load_action_validation.get("issues", []):
            if issue.get("severity") == "error":
                reasons.append(issue.get("message", "Load validation failed."))

    can_download = not reasons
    message = "Ready for Data Import Tool CSV download." if can_download else reasons[0]
    return can_download, message, {"reasons": reasons, "warnings": warnings}
