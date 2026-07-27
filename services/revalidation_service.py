"""Revalidation after approved row and header corrections."""

from __future__ import annotations

from typing import Any

import pandas as pd

from engines.validation_engine import run_validation
from services.metadata_session_service import invalidate_metadata_dependent_session_state
from services.readiness_service import evaluate_upload_readiness
from services.row_correction_plan_service import build_row_correction_plan


def revalidate_prepared_file(
    original_df: pd.DataFrame,
    raw_headers: list[str],
    working_df: pd.DataFrame,
    upload_method: str,
    template: str,
    load_operation: str | None,
    mapping_rows: list[dict[str, Any]] | None,
    preparation_result: dict[str, Any] | None,
    correction_plan: dict[str, Any] | None,
    row_correction_plan: dict[str, Any] | None = None,
    raw_csv_content: str | None = None,
    use_mapped_columns: bool = False,
    source_date_format: str | None = None,
    post_conversion: bool = True,
) -> dict[str, Any]:
    """Re-run header and row validation against the corrected dataframe."""
    if row_correction_plan is None:
        row_correction_plan = build_row_correction_plan(
            working_df,
            upload_method,
            template,
            mapping_rows=mapping_rows,
            raw_csv_content=raw_csv_content,
            source_date_format=source_date_format,
            post_conversion=post_conversion,
        )

    validation_bundle = run_validation(
        working_df,
        list(working_df.columns),
        upload_method,
        template,
        mapping_rows=mapping_rows,
        load_operation=load_operation,
        type_confirmed=True,
        preparation_result=preparation_result,
        correction_plan=correction_plan,
        use_mapped_columns=use_mapped_columns,
    )

    readiness = evaluate_upload_readiness(
        validation_result=validation_bundle,
        preparation_result=preparation_result,
        comparison_result=validation_bundle.get("template_comparison"),
        correction_plan=correction_plan,
    )

    if row_correction_plan.get("has_fixable_issues") and not row_correction_plan.get("corrections_applied"):
        readiness = evaluate_upload_readiness(
            validation_result=validation_bundle,
            preparation_result=preparation_result,
            comparison_result=validation_bundle.get("template_comparison"),
            correction_plan={
                **(correction_plan or {}),
                "has_fixable_changes": True,
                "corrections_applied": False,
                "summary": row_correction_plan.get("summary", {}),
            },
        )

    if row_correction_plan.get("has_blocking_manual_review") and row_correction_plan.get("corrections_applied"):
        readiness = evaluate_upload_readiness(
            validation_result=validation_bundle,
            preparation_result={
                **(preparation_result or {}),
                "manual_review": row_correction_plan.get("manual_review", []),
            },
            comparison_result=validation_bundle.get("template_comparison"),
            correction_plan=correction_plan,
        )

    return {
        "validation_bundle": validation_bundle,
        "readiness": readiness,
        "row_correction_plan": row_correction_plan,
    }


def clear_stale_metadata_validation(session_state: dict[str, Any]) -> None:
    """Remove cached picklist and metadata-dependent validation from the session."""
    invalidate_metadata_dependent_session_state(session_state)
