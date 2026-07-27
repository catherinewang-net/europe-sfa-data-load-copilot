"""Copilot workflow orchestration."""

from __future__ import annotations

from typing import Any

import pandas as pd

from engines.data_preparation import apply_preparation, build_formatting_review
from engines.field_mapping import get_template_mapping, load_tool_mappings
from engines.mapping_confirmation import (
    build_mapping_report,
    build_column_order,
    get_confirmed_rename_map,
    get_excluded_columns,
    get_unresolved_rows,
)
from engines.template_comparison import compare_to_reference, is_dit_format
from engines.upload_readiness import assess_readiness
from engines.validation_engine import run_validation
from services.download_readiness_service import evaluate_download_readiness
from services.correction_plan_service import build_correction_plan, detect_file_style
from services.data_import_preparation_service import (
    apply_data_import_preparation,
    build_data_import_correction_plan,
    compare_data_import_headers,
)
from services.file_preparation_service import prepare_file
from services.preparation_task_service import is_preparation_only
from services.revalidation_service import revalidate_prepared_file
from services.row_correction_plan_service import build_row_correction_plan
from services.date_conversion_service import (
    apply_date_conversions,
    build_date_conversion_plan,
    resolve_date_field_columns,
)
from services.metadata_provider_factory import get_metadata_adapter
from adapters.sfdx_metadata.standard_field_supplements import supplement_object_fields
from services.constants import MAPPING_ACTION_KEEP, MAPPING_ACTION_MAP, MAPPING_STATUS_CONFIRMED
from services.field_mapping_service import is_valid_api_header
from services.field_mapping_service import (
    build_mapping_rows,
    confirm_all_suggested,
    confirm_mapping,
    exclude_mapping,
    get_api_field_options,
    get_confirmed_rename_map,
    get_excluded_columns,
    get_workbench_field_catalog_for_template,
)
from services.workbench_mapping_service import (
    apply_session_to_rows,
    mappings_ready_for_preparation,
    rows_to_session,
)
from services.workbench_mapped_dataframe import build_mapped_df
from services.workbench_preparation_service import (
    apply_workbench_preparation,
    build_workbench_preparation_plan,
)
from services.template_service import (
    get_metadata_source_info,
    get_template_dropdown_options,
    get_template_dropdown_warning,
    resolve_template,
)
from validators.load_action_validator import validate_load_action
from validators.picklist_validator import validate_picklists


def get_workflow_context(
    upload_method: str | None,
    template: str | None,
    load_operation: str | None = None,
    preparation_task: str | None = None,
) -> dict[str, Any]:
    template_context = resolve_template(template)
    fallback_config = template_context.fallback_config if template_context else None

    supports_workbench = False
    if upload_method == "Workbench" and template_context:
        supports_workbench = bool(
            template_context.metadata_available or template_context.fallback_config
        )

    return {
        "upload_method": upload_method,
        "template": template,
        "load_operation": load_operation,
        "preparation_task": preparation_task,
        "preparation_only": is_preparation_only(preparation_task),
        "template_context": template_context,
        "template_mapping": _build_runtime_template_mapping(template_context, fallback_config),
        "is_account_template": bool(template_context and template_context.is_account_template),
        "has_mapping": bool(template_context and template_context.salesforce_object),
        "supports_workbench_prep": supports_workbench,
        "metadata_available": bool(template_context and template_context.metadata_available),
        "metadata_message": template_context.metadata_message if template_context else None,
    }


def init_field_mappings(
    uploaded_headers: list[str],
    template: str,
    load_operation: str | None = None,
    saved_mappings: dict[str, dict[str, Any]] | None = None,
) -> list[dict]:
    rows, context = build_mapping_rows(uploaded_headers, template, load_operation)
    if not context.metadata_available and context.metadata_message:
        if not context.fallback_config:
            raise ValueError(context.metadata_message)
    if saved_mappings:
        apply_session_to_rows(rows, saved_mappings)
    return rows


def build_mapped_dataframe(
    original_df: pd.DataFrame,
    mapping_rows: list[dict],
) -> pd.DataFrame:
    return build_mapped_df(original_df, mapping_rows)


def get_workbench_field_catalog_options(
    template: str,
    load_operation: str | None = None,
):
    return get_workbench_field_catalog_for_template(template, load_operation)


def get_api_field_dropdown_options(
    template: str,
    load_operation: str | None = None,
) -> list[str]:
    return get_api_field_options(template, load_operation)


def run_template_comparison(
    raw_headers: list[str],
    upload_method: str,
    template: str,
    load_operation: str | None = None,
) -> dict[str, Any]:
    if upload_method == "Data Import Tool":
        return compare_data_import_headers(raw_headers, template)
    return compare_to_reference(raw_headers, upload_method, template, load_operation)


def build_data_import_correction_plan_proposal(
    df: pd.DataFrame,
    uploaded_headers: list[str],
    template: str,
    comparison_result: dict | None = None,
) -> dict[str, Any]:
    return build_data_import_correction_plan(
        df,
        uploaded_headers,
        template,
        comparison_result,
    )


def build_workbench_preparation_plan_proposal(
    df: pd.DataFrame,
    mapping_rows: list[dict],
    template: str,
    load_operation: str | None,
    type_confirmed: bool,
    row_correction_plan: dict[str, Any] | None = None,
    mapping_applied: bool = False,
) -> dict[str, Any]:
    return build_workbench_preparation_plan(
        df,
        mapping_rows,
        template,
        load_operation,
        type_confirmed,
        row_correction_plan=row_correction_plan,
        mapping_applied=mapping_applied,
    )


def run_full_validation(
    df: pd.DataFrame,
    raw_headers: list[str],
    upload_method: str,
    template: str,
    mapping_rows: list[dict] | None = None,
    load_operation: str | None = None,
    type_confirmed: bool = False,
    preparation_result: dict | None = None,
    correction_plan: dict | None = None,
    use_mapped_columns: bool = False,
    preparation_task: str | None = None,
) -> dict[str, Any]:
    return run_validation(
        df,
        raw_headers,
        upload_method,
        template,
        mapping_rows=mapping_rows,
        load_operation=load_operation,
        type_confirmed=type_confirmed,
        preparation_result=preparation_result,
        correction_plan=correction_plan,
        use_mapped_columns=use_mapped_columns,
        preparation_task=preparation_task,
    )


def build_correction_plan_proposal(
    df: pd.DataFrame,
    uploaded_headers: list[str],
    upload_method: str,
    template: str,
    load_operation: str | None = None,
    comparison_result: dict | None = None,
) -> dict[str, Any]:
    if upload_method == "Data Import Tool":
        return build_data_import_correction_plan(
            df,
            uploaded_headers,
            template,
            comparison_result,
        )
    return build_correction_plan(
        df,
        uploaded_headers,
        upload_method,
        template,
        load_operation,
        comparison_result,
    )


def identify_upload_file_style(uploaded_headers: list[str], template: str) -> dict[str, Any]:
    return detect_file_style(uploaded_headers, template)


def apply_file_preparation(
    original_df: pd.DataFrame,
    uploaded_headers: list[str],
    upload_method: str,
    template: str,
    load_operation: str | None,
    correction_plan: dict[str, Any],
    enabled_change_ids: set[str],
    mapping_rows: list[dict] | None = None,
    type_confirmed: bool = False,
    enabled_formatting_issue_ids: set[str] | None = None,
    formatting_review: dict[str, Any] | None = None,
    row_correction_plan: dict[str, Any] | None = None,
    enabled_row_issue_ids: set[str] | None = None,
    preparation_plan: dict[str, Any] | None = None,
    mapped_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    if upload_method == "Workbench" and preparation_plan:
        return apply_workbench_preparation(
            original_df,
            preparation_plan,
            enabled_change_ids,
            mapping_rows or [],
            type_confirmed,
            row_correction_plan=row_correction_plan,
            enabled_row_issue_ids=enabled_row_issue_ids,
            mapped_df=mapped_df,
        )
    if upload_method == "Data Import Tool":
        return apply_data_import_preparation(
            original_df,
            uploaded_headers,
            template,
            correction_plan,
            enabled_change_ids,
            row_correction_plan=row_correction_plan,
            enabled_row_issue_ids=enabled_row_issue_ids,
        )
    return prepare_file(
        original_df,
        uploaded_headers,
        upload_method,
        template,
        load_operation,
        correction_plan,
        enabled_change_ids,
        mapping_rows=mapping_rows,
        type_confirmed=type_confirmed,
        enabled_formatting_issue_ids=enabled_formatting_issue_ids,
        formatting_review=formatting_review,
        row_correction_plan=row_correction_plan,
        enabled_row_issue_ids=enabled_row_issue_ids,
    )


def resolve_dit_api_field(column: str, template: str | None = None) -> str:
    """Resolve a friendly DIT header to its Salesforce API field name."""
    context = resolve_template(template) if template else None
    if not context or not context.template_definition:
        return column

    template_definition = context.template_definition
    if column in template_definition.csv_label_to_api:
        return template_definition.csv_label_to_api[column]

    normalized = column.lstrip("*").strip()
    for label, api_name in template_definition.csv_label_to_api.items():
        if label.lstrip("*").strip() == normalized:
            return api_name

    if column in template_definition.api_to_csv_label:
        return column

    return column


def build_dit_mapping_rows(columns: list[str], template: str | None = None) -> list[dict[str, Any]]:
    """Build synthetic mapping rows for DIT picklist validation after header prep."""
    rows: list[dict[str, Any]] = []
    for column in columns:
        api_field = resolve_dit_api_field(column, template)
        uses_friendly_header = api_field != column or not is_valid_api_header(column)
        rows.append({
            "uploaded_column": column,
            "dit_column": column,
            "confirmed_api_field": api_field,
            "status": MAPPING_STATUS_CONFIRMED,
            "action": MAPPING_ACTION_MAP if uses_friendly_header else MAPPING_ACTION_KEEP,
        })
    return rows


def build_row_correction_plan_proposal(
    df: pd.DataFrame,
    upload_method: str,
    template: str,
    mapping_rows: list[dict] | None = None,
    raw_csv_content: str | None = None,
    source_date_format: str | None = None,
    post_conversion: bool = False,
) -> dict[str, Any]:
    return build_row_correction_plan(
        df,
        upload_method,
        template,
        mapping_rows=mapping_rows,
        raw_csv_content=raw_csv_content,
        source_date_format=source_date_format,
        post_conversion=post_conversion,
    )


def build_date_field_types(
    df: pd.DataFrame,
    template: str,
    mapping_rows: list[dict] | None = None,
) -> dict[str, str]:
    """Resolve all retained date/datetime columns from metadata and template config."""
    context = resolve_template(template)
    mapping_rows = mapping_rows or []
    rename_map = get_confirmed_rename_map(mapping_rows)
    excluded = get_excluded_columns(mapping_rows)
    active_columns = [column for column in df.columns if column not in excluded]

    object_fields = {}
    if context and context.salesforce_object:
        raw_fields = get_metadata_adapter().get_object_fields(context.salesforce_object)
        object_fields = supplement_object_fields(context.salesforce_object, raw_fields)

    return resolve_date_field_columns(active_columns, rename_map, context, object_fields)


def apply_date_format_review(
    df: pd.DataFrame,
    approval: dict[str, Any],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Apply approved date conversions from the date format review step."""
    if approval.get("declined") or not approval.get("approved"):
        return df.copy(), []

    plan = approval.get("plan")
    if not plan:
        return df.copy(), []

    return apply_date_conversions(df, plan)


def attach_date_validation_to_preparation(
    preparation_result: dict[str, Any] | None,
    df: pd.DataFrame,
    date_field_types: dict[str, str],
    upload_method: str,
    source_format: str | None = None,
) -> dict[str, Any] | None:
    from services.date_conversion_service import attach_date_validation_state

    if not preparation_result:
        return preparation_result
    return attach_date_validation_state(
        preparation_result,
        date_field_types,
        upload_method,
        source_format,
    )


def build_date_conversion_review_plan(
    df: pd.DataFrame,
    date_field_types: dict[str, str],
    upload_method: str,
    source_format: str | None = None,
) -> dict[str, Any]:
    return build_date_conversion_plan(
        df,
        date_field_types,
        upload_method,
        source_format=source_format,
    )


def revalidate_after_corrections(
    original_df: pd.DataFrame,
    raw_headers: list[str],
    working_df: pd.DataFrame,
    upload_method: str,
    template: str,
    load_operation: str | None,
    mapping_rows: list[dict] | None,
    preparation_result: dict[str, Any] | None,
    correction_plan: dict[str, Any] | None,
    row_correction_plan: dict[str, Any] | None = None,
    raw_csv_content: str | None = None,
    use_mapped_columns: bool = False,
    source_date_format: str | None = None,
    post_conversion: bool = True,
) -> dict[str, Any]:
    return revalidate_prepared_file(
        original_df,
        raw_headers,
        working_df,
        upload_method,
        template,
        load_operation,
        mapping_rows,
        preparation_result,
        correction_plan,
        row_correction_plan=row_correction_plan,
        raw_csv_content=raw_csv_content,
        use_mapped_columns=use_mapped_columns,
        source_date_format=source_date_format,
        post_conversion=post_conversion,
    )


def mappings_ready_for_data_quality(
    mapping_rows: list[dict],
    type_confirmed: bool,
    is_account_template: bool,
    template_context: Any | None = None,
    preparation_result: dict | None = None,
) -> tuple[bool, str]:
    return mappings_ready_for_preparation(
        mapping_rows,
        type_confirmed,
        is_account_template,
        template_context,
    )


def mappings_ready_for_formatting(
    mapping_rows: list[dict],
    type_confirmed: bool,
    is_account_template: bool,
    template_context: Any | None = None,
    preparation_result: dict | None = None,
) -> tuple[bool, str]:
    unresolved = get_unresolved_rows(mapping_rows)
    if unresolved:
        return False, (
            "Confirm or exclude all field mappings before reviewing formatting changes."
        )
    type_ready = type_confirmed
    if is_account_template and not type_ready and preparation_result is not None:
        corrected_df = preparation_result.get("corrected_df")
        required_type = getattr(template_context, "required_type_value", None) if template_context else None
        if (
            corrected_df is not None
            and required_type
            and "Type" in corrected_df.columns
            and corrected_df["Type"].astype(str).str.strip().eq(required_type).all()
        ):
            type_ready = True
    if is_account_template and not type_ready:
        return False, "Confirm the Type column before reviewing formatting changes."
    if template_context and not getattr(template_context, "account_type_valid", True):
        return False, getattr(
            template_context,
            "account_type_error",
            "Account.Type metadata error.",
        )
    return True, ""


def build_formatting_review_proposal(
    df: pd.DataFrame,
    template: str,
    mapping_rows: list[dict],
    raw_csv_content: str | None = None,
) -> dict[str, Any]:
    context = resolve_template(template)
    template_mapping = _build_runtime_template_mapping(context, context.fallback_config if context else None)
    if not template_mapping:
        raise ValueError(f"No runtime template mapping available for: {template}")

    return build_formatting_review(
        df,
        template_mapping,
        confirmed_rename_map=get_confirmed_rename_map(mapping_rows),
        excluded_columns=get_excluded_columns(mapping_rows),
        raw_csv_content=raw_csv_content,
    )


def execute_preparation(
    df: pd.DataFrame,
    template: str,
    load_operation: str,
    mapping_rows: list[dict],
    type_confirmed: bool,
    enabled_formatting_issue_ids: set[str] | None = None,
    formatting_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = resolve_template(template)
    template_mapping = _build_runtime_template_mapping(context, context.fallback_config if context else None)
    if not template_mapping:
        raise ValueError(f"No runtime template mapping available for: {template}")

    result = apply_preparation(
        df,
        template_mapping,
        load_operation,
        template,
        confirmed_rename_map=get_confirmed_rename_map(mapping_rows),
        excluded_columns=get_excluded_columns(mapping_rows),
        type_confirmed=type_confirmed,
        enabled_formatting_issue_ids=enabled_formatting_issue_ids,
        formatting_review=formatting_review,
    )
    result["mapping_report"] = build_mapping_report(mapping_rows)
    return result


def check_download_allowed(
    mapping_rows: list[dict],
    type_confirmed: bool,
    is_account_template: bool,
    load_operation: str,
    template: str | None = None,
    preparation_result: dict | None = None,
    picklist_validation: dict | None = None,
    load_action_validation: dict | None = None,
    row_correction_plan: dict | None = None,
    record_existence_validation: dict | None = None,
    upload_method: str | None = None,
    validation_result: dict | None = None,
) -> tuple[bool, str]:
    template_context = resolve_template(template)
    allowed, message, _details = evaluate_download_readiness(
        template_context,
        mapping_rows,
        type_confirmed,
        load_operation,
        picklist_validation,
        load_action_validation,
        preparation_result,
        row_correction_plan=row_correction_plan,
        preparation_only=load_operation is None,
        record_existence_validation=record_existence_validation,
        upload_method=upload_method,
        validation_result=validation_result,
    )
    return allowed, message


def detect_dit_upload(raw_headers: list[str], template: str) -> bool:
    return is_dit_format(raw_headers, template)


def evaluate_readiness(
    validation_result: dict[str, Any] | None = None,
    preparation_result: dict[str, Any] | None = None,
    comparison_result: dict[str, Any] | None = None,
    correction_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return evaluate_upload_readiness(
        validation_result=validation_result,
        preparation_result=preparation_result,
        comparison_result=comparison_result,
        correction_plan=correction_plan,
    )


def _build_runtime_template_mapping(
    context: Any,
    fallback_config: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not context or not context.salesforce_object:
        return None

    runtime: dict[str, Any] = {
        "salesforce_object": context.salesforce_object,
        "required_type": context.required_type_value,
    }

    if context.template_definition:
        runtime["column_mappings"] = {
            csv_label: {"suggested_api_field": api_name, "default_status": "needs_confirmation"}
            for csv_label, api_name in context.template_definition.csv_label_to_api.items()
        }
        runtime["date_fields"] = _infer_date_fields(context.template_definition.api_to_csv_label)

    if fallback_config:
        runtime.setdefault("date_fields", fallback_config.get("date_fields", []))
        if "column_mappings" not in runtime:
            runtime["column_mappings"] = fallback_config.get("column_mappings", {})

    return runtime


def _infer_date_fields(api_to_csv: dict[str, str]) -> list[str]:
    return [
        csv_label
        for csv_label in api_to_csv.values()
        if "date" in csv_label.lower()
    ]
