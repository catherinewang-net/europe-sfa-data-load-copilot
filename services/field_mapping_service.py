"""Field mapping proposals and Salesforce object verification."""

from __future__ import annotations

from typing import Any

from adapters.sfdx_metadata.adapter import SfdxMetadataAdapter
from adapters.sfdx_metadata.standard_field_supplements import supplement_object_fields
from services.constants import (
    FORBIDDEN_CSV_HEADERS,
    MAPPING_STATUS_CONFIRMED,
    MAPPING_STATUS_EXCLUDED,
    MAPPING_STATUS_INVALID,
    MAPPING_STATUS_NEEDS_CONFIRMATION,
    MAPPING_STATUS_UNMAPPED,
)
from services.template_service import TemplateContext, get_adapter, resolve_template
from services.workbench_field_catalog_service import (
    WorkbenchFieldOption,
    get_workbench_field_catalog,
    get_workbench_field_options,
)
from services.workbench_mapping_service import (
    build_mapping_report as build_workbench_mapping_report,
    build_workbench_mapping_rows,
    confirm_all_high_confidence,
    confirm_mapping as confirm_workbench_mapping,
    exclude_mapping as exclude_workbench_mapping,
    get_confirmed_rename_map as get_workbench_confirmed_rename_map,
    get_excluded_columns as get_workbench_excluded_columns,
    get_invalid_rows as get_workbench_invalid_rows,
    get_unresolved_rows as get_workbench_unresolved_rows,
)


def build_mapping_rows(
    uploaded_headers: list[str],
    template_name: str,
    load_operation: str | None = None,
) -> tuple[list[dict[str, Any]], TemplateContext]:
    return build_workbench_mapping_rows(uploaded_headers, template_name, load_operation)


def verify_mapping_field(
    object_name: str,
    api_field: str | None,
    adapter: SfdxMetadataAdapter | None = None,
) -> tuple[bool, str | None]:
    if not api_field:
        return False, None
    adapter = adapter or get_adapter()
    object_fields = supplement_object_fields(object_name, adapter.get_object_fields(object_name))
    if api_field not in object_fields:
        return False, f"Field '{api_field}' was not found on Salesforce object '{object_name}'."
    return True, None


def get_api_field_options(template_name: str, load_operation: str | None = None) -> list[str]:
    return [option.api_name for option in get_workbench_field_options(template_name, load_operation)]


def get_workbench_field_catalog_for_template(
    template_name: str,
    load_operation: str | None = None,
) -> tuple[list[WorkbenchFieldOption], dict[str, Any], str | None]:
    return get_workbench_field_catalog(template_name, load_operation)


def confirm_mapping(rows: list[dict], dit_column: str, api_field: str | None) -> None:
    confirm_workbench_mapping(rows, dit_column, api_field)


def exclude_mapping(rows: list[dict], dit_column: str) -> None:
    exclude_workbench_mapping(rows, dit_column)


def confirm_all_suggested(rows: list[dict]) -> int:
    return confirm_all_high_confidence(rows)


def get_confirmed_rename_map(rows: list[dict]) -> dict[str, str]:
    return get_workbench_confirmed_rename_map(rows)


def get_excluded_columns(rows: list[dict]) -> set[str]:
    return get_workbench_excluded_columns(rows)


def get_unresolved_rows(rows: list[dict]) -> list[dict]:
    return get_workbench_unresolved_rows(rows)


def get_invalid_rows(rows: list[dict]) -> list[dict]:
    return get_workbench_invalid_rows(rows)


def is_valid_api_header(name: str) -> bool:
    if not name or not name.strip():
        return False
    upper = name.upper()
    if upper in FORBIDDEN_CSV_HEADERS:
        return False
    if name.startswith("UNCONFIRMED"):
        return False
    return True


def build_mapping_report(rows: list[dict]) -> dict[str, Any]:
    return build_workbench_mapping_report(rows)
