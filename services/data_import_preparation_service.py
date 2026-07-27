"""Data Import Tool preparation — exact template structure enforcement."""

from __future__ import annotations

from typing import Any

import pandas as pd

from engines.template_comparison import compare_to_reference
from services.correction_plan_service import (
    build_correction_plan,
    get_fixable_change_ids,
    get_header_rename_change_ids,
    get_safe_change_ids,
)
from services.file_preparation_service import apply_correction_changes, prepare_file


def build_data_import_correction_plan(
    original_df: pd.DataFrame,
    uploaded_headers: list[str],
    template: str,
    comparison_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a correction plan against the selected Data Import Tool template."""
    if comparison_result is None:
        comparison_result = compare_to_reference(
            uploaded_headers,
            "Data Import Tool",
            template,
            load_operation=None,
        )
    return build_correction_plan(
        original_df,
        uploaded_headers,
        "Data Import Tool",
        template,
        load_operation=None,
        comparison_result=comparison_result,
    )


def apply_data_import_preparation(
    original_df: pd.DataFrame,
    uploaded_headers: list[str],
    template: str,
    correction_plan: dict[str, Any],
    enabled_change_ids: set[str],
    row_correction_plan: dict[str, Any] | None = None,
    enabled_row_issue_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Apply approved Data Import Tool structural corrections to a copy of the upload."""
    return prepare_file(
        original_df,
        uploaded_headers,
        "Data Import Tool",
        template,
        load_operation=None,
        correction_plan=correction_plan,
        enabled_change_ids=enabled_change_ids,
        row_correction_plan=row_correction_plan,
        enabled_row_issue_ids=enabled_row_issue_ids,
    )


def compare_data_import_headers(
    uploaded_headers: list[str],
    template: str,
) -> dict[str, Any]:
    """Compare uploaded headers against the selected DIT reference template."""
    return compare_to_reference(
        uploaded_headers,
        "Data Import Tool",
        template,
        load_operation=None,
    )


__all__ = [
    "apply_data_import_preparation",
    "apply_correction_changes",
    "build_data_import_correction_plan",
    "compare_data_import_headers",
    "get_fixable_change_ids",
    "get_header_rename_change_ids",
    "get_safe_change_ids",
]
