"""Upload readiness assessment with correction-plan awareness."""

from __future__ import annotations

from typing import Any

from core.config import READINESS_STATUS
from services.correction_plan_service import get_fixable_change_ids


def evaluate_upload_readiness(
    validation_result: dict[str, Any] | None = None,
    preparation_result: dict[str, Any] | None = None,
    comparison_result: dict[str, Any] | None = None,
    correction_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Determine upload readiness, deferring NOT READY while fixes are still available."""
    reasons: list[str] = []
    warnings: list[str] = []
    status = READINESS_STATUS["READY"]

    corrections_applied = bool(
        correction_plan and correction_plan.get("corrections_applied")
    )
    corrections_declined = bool(
        correction_plan and correction_plan.get("corrections_declined")
    )
    pending_fixable = bool(
        correction_plan
        and correction_plan.get("has_fixable_changes")
        and not corrections_applied
        and not corrections_declined
    )

    if pending_fixable:
        summary = correction_plan.get("summary", {})
        fix_count = sum(
            summary.get(key, 0)
            for key in (
                "rename",
                "reorder_columns",
                "add_generated_value",
                "add_empty_optional_column",
                "exclude_extra_column",
            )
        )
        manual_count = summary.get("manual_review", 0)
        return {
            "status": READINESS_STATUS["NEEDS_USER_ACTION"],
            "reasons": [],
            "warnings": [],
            "explanation": _build_explanation(
                READINESS_STATUS["NEEDS_USER_ACTION"],
                [],
                [],
                fix_count=fix_count,
                manual_count=manual_count,
            ),
            "pending_fix_count": fix_count,
            "pending_manual_count": manual_count,
        }

    if comparison_result and not corrections_applied:
        comp = comparison_result.get("comparison", {})
        if not comp.get("template_match", False):
            covered_missing = _covered_missing_columns(comp, correction_plan)
            uncovered_missing = [
                col for col in comp.get("missing_columns", [])
                if col not in covered_missing
            ]
            if uncovered_missing and not pending_fixable:
                status = READINESS_STATUS["NOT_READY"]
                reasons.append(f"Missing headers: {', '.join(uncovered_missing)}")
            if comp.get("duplicate_columns"):
                status = READINESS_STATUS["NOT_READY"]
                reasons.append(
                    f"Duplicate headers: {', '.join(comp['duplicate_columns'])}"
                )
            order_diffs = comp.get("order_differences", [])
            if order_diffs and not _has_enabled_change(correction_plan, "reorder:columns"):
                if status == READINESS_STATUS["READY"]:
                    status = READINESS_STATUS["NEEDS_USER_ACTION"]
                warnings.append(f"{len(order_diffs)} header-order difference(s)")

        if comparison_result.get("mismatch_warning"):
            warnings.append(comparison_result["mismatch_warning"])

    if validation_result:
        for issue in validation_result.get("issues", []):
            if issue.get("severity") == "error" and not _is_deferred_template_issue(
                issue,
                correction_plan,
                corrections_applied,
            ):
                status = READINESS_STATUS["NOT_READY"]
                reasons.append(issue.get("message", "Validation error"))
            elif issue.get("severity") == "warning":
                warnings.append(issue.get("message", "Validation warning"))

    if preparation_result:
        manual_review = preparation_result.get("manual_review", [])
        if manual_review:
            status = READINESS_STATUS["NOT_READY"]
            reasons.append(
                f"{len(manual_review)} item(s) require manual review before upload"
            )
        warnings.extend(preparation_result.get("warnings", []))

    if correction_plan and correction_plan.get("has_blocking_manual_review") and corrections_applied:
        blocking = [
            item for item in correction_plan.get("manual_review", [])
            if item.get("blocking")
        ]
        if blocking:
            status = READINESS_STATUS["NOT_READY"]
            for item in blocking:
                reasons.append(item.get("description", "Manual review required"))

    if warnings and status == READINESS_STATUS["READY"]:
        status = READINESS_STATUS["READY_WITH_WARNINGS"]

    return {
        "status": status,
        "reasons": reasons,
        "warnings": warnings,
        "explanation": _build_explanation(status, reasons, warnings),
    }


def _covered_missing_columns(
    comparison: dict[str, Any],
    correction_plan: dict[str, Any] | None,
) -> set[str]:
    if not correction_plan:
        return set()

    covered: set[str] = set()
    for rename in correction_plan.get("proposed_renames", []):
        target = rename.get("target_column")
        if target:
            covered.add(target)
    for change in correction_plan.get("changes", []):
        if change["category"] in {
            "rename",
            "add_generated_value",
            "add_empty_optional_column",
        }:
            target = change.get("target_column")
            if target:
                covered.add(target)
    return covered


def _has_enabled_change(correction_plan: dict[str, Any] | None, change_id: str) -> bool:
    if not correction_plan:
        return False
    enabled = set(correction_plan.get("enabled_change_ids") or [])
    if change_id in enabled:
        return True
    return change_id in get_fixable_change_ids(correction_plan) and correction_plan.get("corrections_applied")


def _is_deferred_template_issue(
    issue: dict[str, Any],
    correction_plan: dict[str, Any] | None,
    corrections_applied: bool,
) -> bool:
    if issue.get("validator") != "template":
        return False
    if corrections_applied:
        return False
    if not correction_plan or not correction_plan.get("has_fixable_changes"):
        return False
    field = issue.get("field")
    if not field:
        return issue.get("message", "").startswith("Missing required header")
    return field in _covered_missing_columns(
        {"missing_columns": [field]},
        correction_plan,
    )


def _build_explanation(
    status: str,
    reasons: list[str],
    warnings: list[str],
    fix_count: int = 0,
    manual_count: int = 0,
) -> str:
    lines = [f"Upload readiness: {status}"]

    if status == READINESS_STATUS["NEEDS_USER_ACTION"] and fix_count:
        lines.append(
            f"\nThe Copilot can make {fix_count} change(s) to prepare your file."
        )
        if manual_count:
            lines.append(
                f"{manual_count} item(s) still require manual review after preparation."
            )
        lines.append("\nReview the Prepare My File section and approve the proposed changes.")

    if reasons:
        lines.append("\nBlocking issues:")
        for reason in reasons:
            lines.append(f"- {reason}")

    if warnings:
        lines.append("\nWarnings:")
        for warning in warnings:
            lines.append(f"- {warning}")

    if status == READINESS_STATUS["READY"]:
        lines.append("\nThe file appears ready for upload.")
    elif status == READINESS_STATUS["READY_WITH_WARNINGS"]:
        lines.append("\nThe file may be uploaded but warnings should be reviewed first.")
    elif status == READINESS_STATUS["NOT_READY"]:
        lines.append("\nThe file is not ready for upload. Please resolve the issues above.")

    return "\n".join(lines)
