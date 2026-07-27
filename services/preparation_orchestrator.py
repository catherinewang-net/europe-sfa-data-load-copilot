"""Shared preparation pipeline helpers for DIT and Workbench."""

from __future__ import annotations

from typing import Any

import pandas as pd

from services.download_readiness_service import evaluate_download_readiness
from services.template_service import resolve_template


def merge_picklist_change_log(
    preparation_result: dict[str, Any],
    picklist_plan: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge approved picklist corrections into the preparation change log."""
    if not picklist_plan or not picklist_plan.get("change_log"):
        return preparation_result

    merged = dict(preparation_result)
    change_log = list(merged.get("change_log", []))
    change_log.extend(picklist_plan["change_log"])
    merged["change_log"] = change_log
    return merged


def build_validation_summary(
    validation_result: dict[str, Any] | None,
    preparation_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a JSON-serializable validation summary for download artifacts."""
    validation = validation_result or {}
    preparation = preparation_result or {}
    picklist = validation.get("picklist_validation") or {}
    dependencies = validation.get("dependencies") or {}
    load_action = validation.get("load_action_validation") or {}
    record_check = validation.get("record_existence_validation") or {}

    return {
        "upload_method": validation.get("upload_method"),
        "template": validation.get("template"),
        "preparation_task": validation.get("preparation_task"),
        "preparation_only": validation.get("preparation_only"),
        "row_count": validation.get("row_count"),
        "has_blocking_issues": validation.get("has_blocking_issues", False),
        "download_readiness": validation.get("download_readiness"),
        "picklist_validation": {
            "valid_count": picklist.get("valid_count", 0),
            "invalid_count": picklist.get("invalid_count", 0),
            "has_blocking_issues": picklist.get("has_blocking_issues", False),
            "field_summaries": picklist.get("field_summaries", []),
        },
        "dependencies": {
            "checked": dependencies.get("checked", False),
            "blocking_count": dependencies.get("blocking_count", 0),
            "manual_review_count": len(dependencies.get("manual_review", [])),
        },
        "load_action_validation": {
            "evaluated": load_action.get("evaluated"),
            "issue_count": len(load_action.get("issues", [])),
        },
        "record_existence_validation": {
            "evaluated": record_check.get("evaluated"),
            "blocks_download": record_check.get("blocks_download", False),
        },
        "lookup_validation": {
            "evaluated": (validation.get("lookup_validation") or {}).get("evaluated"),
            "blocks_download": (validation.get("lookup_validation") or {}).get("blocks_download", False),
            "summary": (validation.get("lookup_validation") or {}).get("summary", {}),
        },
        "manual_review_count": len(validation.get("manual_review", [])),
        "issue_count": len(validation.get("issues", [])),
        "preparation_manual_review_count": len(preparation.get("manual_review", [])),
        "preparation_date_unresolved_count": len(preparation.get("date_unresolved", [])),
        "change_log_count": len(preparation.get("change_log", [])),
    }


def evaluate_shared_download_readiness(
    *,
    upload_method: str,
    template: str | None,
    mapping_rows: list[dict[str, Any]],
    type_confirmed: bool,
    load_operation: str | None,
    preparation_result: dict[str, Any] | None,
    validation_result: dict[str, Any] | None,
    row_correction_plan: dict[str, Any] | None = None,
    preparation_only: bool = False,
) -> tuple[bool, str]:
    """Single download gate for both DIT and Workbench."""
    template_context = resolve_template(template)
    validation = validation_result or {}
    allowed, message, _details = evaluate_download_readiness(
        template_context,
        mapping_rows,
        type_confirmed,
        load_operation,
        validation.get("picklist_validation"),
        validation.get("load_action_validation"),
        preparation_result,
        row_correction_plan=row_correction_plan,
        preparation_only=preparation_only,
        record_existence_validation=validation.get("record_existence_validation"),
        upload_method=upload_method,
        validation_result=validation,
    )
    return allowed, message


def apply_picklist_session_update(
    mapped_df: pd.DataFrame,
    picklist_revalidation: dict[str, Any],
    picklist_plan: dict[str, Any],
) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
    """Return updated mapped dataframe state after picklist approval."""
    return mapped_df, list(mapped_df.columns), {
        "picklist_validation": picklist_revalidation,
        "picklist_correction_plan": picklist_plan,
    }
