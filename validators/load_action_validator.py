"""Insert and Update validation rules."""

from __future__ import annotations

from typing import Any

import pandas as pd

from core.config import LOAD_ACTION_NOT_EVALUATED
from services.field_mapping_service import get_confirmed_rename_map, verify_mapping_field
from services.template_service import TemplateContext, get_adapter


def validate_load_action(
    df: pd.DataFrame,
    mapping_rows: list[dict[str, Any]],
    load_operation: str | None,
    template_context: TemplateContext,
) -> dict[str, Any]:
    if not load_operation:
        return not_evaluated_load_action_result()

    object_name = template_context.salesforce_object or ""
    adapter = get_adapter()
    rename_map = get_confirmed_rename_map(mapping_rows)
    issues: list[dict[str, Any]] = []
    manual_review: list[dict[str, Any]] = []

    id_exists_on_object, id_object_error = verify_mapping_field(object_name, "Id", adapter)
    if load_operation == "Update":
        if not id_exists_on_object:
            issues.append({
                "severity": "error",
                "field": "Id",
                "message": id_object_error or "Id field is required for Update but was not found on the object.",
            })
        else:
            id_column = _find_source_column(rename_map, "Id")
            if not id_column:
                issues.append({
                    "severity": "error",
                    "field": "Id",
                    "message": "Update requires a confirmed Id column mapping.",
                })
            elif id_column in df.columns:
                for idx, value in df[id_column].items():
                    if _is_blank(value):
                        manual_review.append({
                            "row": idx + 2,
                            "field": "Id",
                            "value": "",
                            "reason": "Update operation requires Id to be populated manually",
                        })

    if load_operation == "Insert":
        id_column = _find_source_column(rename_map, "Id")
        if id_column and id_column in df.columns:
            populated = df[id_column].apply(lambda value: not _is_blank(value)).any()
            if populated:
                issues.append({
                    "severity": "warning",
                    "field": "Id",
                    "message": (
                        "Insert operation selected but Id column contains values. "
                        "These were left unchanged."
                    ),
                })

    return {
        "load_operation": load_operation,
        "status": load_operation,
        "evaluated": True,
        "issues": issues,
        "manual_review": manual_review,
        "requires_id": load_operation == "Update",
        "blocks_download": any(issue["severity"] == "error" for issue in issues) or bool(manual_review),
    }


def not_evaluated_load_action_result() -> dict[str, Any]:
    return {
        "load_operation": None,
        "status": LOAD_ACTION_NOT_EVALUATED,
        "evaluated": False,
        "issues": [],
        "manual_review": [],
        "requires_id": False,
        "blocks_download": False,
        "message": "Load-action-specific checks were not performed.",
    }


def _find_source_column(rename_map: dict[str, str], api_field: str) -> str | None:
    for dit_column, mapped_api in rename_map.items():
        if mapped_api == api_field:
            return dit_column
    return None


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())
