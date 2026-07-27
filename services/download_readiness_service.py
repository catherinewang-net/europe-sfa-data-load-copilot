"""Download gating for Workbench-ready CSV output."""

from __future__ import annotations

from typing import Any

from services.template_service import TemplateContext
from validators.data_import_readiness_validator import evaluate_data_import_download_readiness
from validators.workbench_readiness_validator import evaluate_workbench_readiness


def evaluate_download_readiness(
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
    upload_method: str | None = None,
    validation_result: dict[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    if upload_method == "Data Import Tool":
        return evaluate_data_import_download_readiness(
            template_context,
            mapping_rows,
            picklist_validation,
            load_action_validation,
            preparation_result,
            row_correction_plan=row_correction_plan,
            validation_result=validation_result,
            record_existence_validation=record_existence_validation,
        )
    return evaluate_workbench_readiness(
        template_context,
        mapping_rows,
        type_confirmed,
        load_operation,
        picklist_validation,
        load_action_validation,
        preparation_result,
        row_correction_plan=row_correction_plan,
        preparation_only=preparation_only,
        record_existence_validation=record_existence_validation,
        validation_result=validation_result,
    )
