"""Salesforce field mapping confirmation — delegates to metadata-backed services."""

from __future__ import annotations

from typing import Any

from services.constants import (
    FORBIDDEN_CSV_HEADERS,
    MAPPING_STATUS_CONFIRMED,
    MAPPING_STATUS_EXCLUDED,
    MAPPING_STATUS_INVALID,
    MAPPING_STATUS_NEEDS_CONFIRMATION,
    MAPPING_STATUS_UNMAPPED,
)
from services.field_mapping_service import (
    build_mapping_report,
    build_mapping_rows,
    confirm_all_suggested,
    confirm_mapping,
    exclude_mapping,
    get_confirmed_rename_map,
    get_excluded_columns,
    get_invalid_rows,
    get_unresolved_rows,
    is_valid_api_header,
)
from services.download_readiness_service import evaluate_download_readiness


def initialize_mapping_rows(
    uploaded_headers: list[str],
    template_name: str,
) -> list[dict[str, Any]]:
    rows, _context = build_mapping_rows(uploaded_headers, template_name)
    return rows


def can_download_workbench_csv(
    rows: list[dict],
    type_confirmed: bool,
    is_account_template: bool,
    load_operation: str,
    preparation_result: dict | None = None,
    template_name: str | None = None,
    picklist_validation: dict | None = None,
    load_action_validation: dict | None = None,
) -> tuple[bool, str]:
    from services.template_service import resolve_template

    template_context = resolve_template(template_name)
    allowed, message, _details = evaluate_download_readiness(
        template_context,
        rows,
        type_confirmed,
        load_operation,
        picklist_validation,
        load_action_validation,
        preparation_result,
    )
    return allowed, message


def build_column_order(
    confirmed_api_fields: list[str],
    salesforce_object: str,
) -> list[str]:
    priority = ["Id", "Name", "Type"]
    ordered: list[str] = []
    for field in priority:
        if field in confirmed_api_fields and field not in ordered:
            ordered.append(field)
    for field in confirmed_api_fields:
        if field not in ordered:
            ordered.append(field)
    return ordered
