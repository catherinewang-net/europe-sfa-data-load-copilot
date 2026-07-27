"""Picklist validation using Salesforce metadata from the adapter."""

from __future__ import annotations

from typing import Any

import pandas as pd

from services.constants import (
    MAPPING_ACTION_EXCLUDE,
    MAPPING_STATUS_EXCLUDED,
    PICKLIST_METADATA_SOURCE_LOCAL,
    PICKLIST_STATUS_BLANK_REQUIRED,
    PICKLIST_STATUS_INVALID,
    PICKLIST_STATUS_METADATA_UNAVAILABLE,
    PICKLIST_STATUS_MULTI_INVALID,
    PICKLIST_STATUS_NEEDS_REVIEW,
    PICKLIST_STATUS_NEEDS_USER_ACTION,
    PICKLIST_STATUS_RECORD_TYPE_FALLBACK,
    PICKLIST_STATUS_VALID,
)
from services.field_mapping_service import get_confirmed_rename_map
from services.template_service import TemplateContext, get_adapter
from services.workbench_mapping_service import (
    filter_valid_mapping_rows,
    get_excluded_columns,
)


def validate_picklists(
    df: pd.DataFrame,
    mapping_rows: list[dict[str, Any]],
    template_context: TemplateContext,
    *,
    use_mapped_columns: bool = False,
) -> dict[str, Any]:
    """
    Validate picklist values for retained mapped columns.

    When use_mapped_columns is True, df is expected to be mapped_df whose columns
    are confirmed Salesforce API field names.
    """
    adapter = get_adapter()
    object_name = template_context.salesforce_object
    if not object_name:
        return _empty_result()

    record_type_name = template_context.record_type_name
    use_record_type_fallback = _should_use_record_type_fallback(template_context)
    columns_to_validate = _columns_to_validate(
        df,
        mapping_rows,
        use_mapped_columns=use_mapped_columns,
    )
    if not columns_to_validate:
        return _empty_result()

    object_fields = adapter.get_object_fields(object_name)

    field_summaries: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []
    valid_count = 0
    invalid_count = 0

    for uploaded_column, api_field in columns_to_validate:
        field_def = object_fields.get(api_field)
        if field_def is None or not field_def.is_picklist:
            continue

        column_name = api_field if use_mapped_columns else uploaded_column
        if column_name not in df.columns:
            continue

        picklist_details = adapter.get_picklist_value_details(object_name, api_field)
        if not picklist_details:
            field_summaries[api_field] = _summary(
                uploaded_column=uploaded_column,
                api_field=api_field,
                object_name=object_name,
                field_type=field_def.field_type,
                record_type_name=record_type_name,
                allowed_value_count=0,
                valid_row_count=0,
                invalid_row_count=0,
                blank_required_row_count=0,
                validation_source=PICKLIST_STATUS_METADATA_UNAVAILABLE,
                fallback_warning=None,
            )
            issues.append(_issue(
                issue_id=f"picklist:{api_field}:metadata",
                status=PICKLIST_STATUS_METADATA_UNAVAILABLE,
                row=None,
                uploaded_column=uploaded_column,
                api_field=api_field,
                object_name=object_name,
                uploaded_value="",
                allowed_values=[],
                record_type_used=record_type_name,
                validation_source=PICKLIST_STATUS_METADATA_UNAVAILABLE,
                reason=f"Picklist metadata unavailable for {object_name}.{api_field}.",
            ))
            continue

        validation_source, fallback_warning, allowed_values, allowed_details = _resolve_allowed_values(
            adapter,
            object_name,
            api_field,
            record_type_name,
            use_record_type_fallback,
            picklist_details,
        )
        is_required = _is_required_field(uploaded_column, api_field, field_def, template_context)
        is_multipicklist = field_def.field_type.lower() == "multipicklist"

        field_valid = 0
        field_invalid = 0
        field_blank_required = 0

        for idx, raw_value in df[column_name].items():
            row_issues, row_valid, row_invalid, row_blank_required = _validate_cell(
                raw_value=raw_value,
                row_number=idx + 2,
                uploaded_column=uploaded_column,
                api_field=api_field,
                object_name=object_name,
                allowed_values=allowed_values,
                allowed_details=allowed_details,
                all_picklist_details=picklist_details,
                record_type_used=record_type_name,
                validation_source=validation_source,
                is_required=is_required,
                is_multipicklist=is_multipicklist,
            )
            issues.extend(row_issues)
            field_valid += row_valid
            field_invalid += row_invalid
            field_blank_required += row_blank_required
            valid_count += row_valid
            invalid_count += row_invalid

        field_summaries[api_field] = _summary(
            uploaded_column=uploaded_column,
            api_field=api_field,
            object_name=object_name,
            field_type=field_def.field_type,
            record_type_name=record_type_name,
            allowed_value_count=len(allowed_values),
            valid_row_count=field_valid,
            invalid_row_count=field_invalid,
            blank_required_row_count=field_blank_required,
            validation_source=validation_source,
            fallback_warning=fallback_warning,
            check_type="field_identification",
        )

    blocking = [
        issue for issue in issues
        if issue["status"] in (
            PICKLIST_STATUS_NEEDS_USER_ACTION,
            PICKLIST_STATUS_INVALID,
            PICKLIST_STATUS_BLANK_REQUIRED,
            PICKLIST_STATUS_MULTI_INVALID,
            PICKLIST_STATUS_NEEDS_REVIEW,
        )
    ]

    return {
        "object_name": object_name,
        "record_type_name": record_type_name,
        "use_mapped_columns": use_mapped_columns,
        "field_summaries": list(field_summaries.values()),
        "issues": issues,
        "valid_count": valid_count,
        "invalid_count": invalid_count,
        "blocking_issue_count": len(blocking),
        "has_blocking_issues": bool(blocking),
    }


def _columns_to_validate(
    df: pd.DataFrame,
    mapping_rows: list[dict[str, Any]],
    *,
    use_mapped_columns: bool,
) -> list[tuple[str, str]]:
    excluded = get_excluded_columns(mapping_rows)
    columns: list[tuple[str, str]] = []

    if use_mapped_columns:
        uploaded_by_api = _uploaded_column_lookup(mapping_rows)
        for api_field in df.columns:
            uploaded_column = uploaded_by_api.get(api_field, api_field)
            if uploaded_column in excluded:
                continue
            columns.append((uploaded_column, api_field))
        return columns

    rename_map = get_confirmed_rename_map(mapping_rows)
    for uploaded_column, api_field in rename_map.items():
        if uploaded_column in excluded:
            continue
        columns.append((uploaded_column, api_field))

    if not columns:
        for row in filter_valid_mapping_rows(mapping_rows):
            if row.get("status") == MAPPING_STATUS_EXCLUDED or row.get("action") == MAPPING_ACTION_EXCLUDE:
                continue
            uploaded = str(row.get("uploaded_column") or row.get("dit_column") or "").strip()
            api_field = row.get("confirmed_api_field")
            if uploaded and api_field and uploaded in df.columns and uploaded not in excluded:
                columns.append((uploaded, api_field))
    return columns


def _uploaded_column_lookup(mapping_rows: list[dict[str, Any]]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for row in filter_valid_mapping_rows(mapping_rows):
        if row.get("status") == MAPPING_STATUS_EXCLUDED or row.get("action") == MAPPING_ACTION_EXCLUDE:
            continue
        uploaded = str(row.get("uploaded_column") or row.get("dit_column") or "").strip()
        api_field = row.get("confirmed_api_field") or uploaded
        if api_field:
            lookup[api_field] = uploaded or api_field
    return lookup


def _should_use_record_type_fallback(template_context: TemplateContext) -> bool:
    if template_context.template_name == "Key Account":
        return True
    if template_context.record_type_name:
        return False
    return True


def _resolve_allowed_values(
    adapter,
    object_name: str,
    api_field: str,
    record_type_name: str | None,
    use_record_type_fallback: bool,
    picklist_details,
) -> tuple[str, str | None, list[str], list[Any]]:
    validation_source = "Object Metadata"
    fallback_warning = None
    allowed_values = [value.api_name for value in picklist_details if value.is_active]
    allowed_details = [value for value in picklist_details if value.is_active]

    if record_type_name and not use_record_type_fallback:
        if adapter.has_record_type_picklist_restriction(object_name, record_type_name, api_field):
            record_type_values = adapter.get_allowed_values_for_record_type(
                object_name,
                record_type_name,
                api_field,
            )
            if record_type_values:
                allowed_values = record_type_values
                active_lookup = {value.api_name.lower(): value for value in picklist_details}
                allowed_details = [
                    active_lookup[value.lower()]
                    for value in record_type_values
                    if value.lower() in active_lookup
                ]
                validation_source = "Record Type Metadata"
        else:
            fallback_warning = (
                "Object-level picklist values used because record-type restrictions were unavailable."
            )
            validation_source = PICKLIST_STATUS_RECORD_TYPE_FALLBACK
    elif use_record_type_fallback:
        fallback_warning = (
            "Object-level picklist values used because record-type restrictions were unavailable."
        )
        validation_source = PICKLIST_STATUS_RECORD_TYPE_FALLBACK

    return validation_source, fallback_warning, allowed_values, allowed_details


def _validate_cell(
    *,
    raw_value: Any,
    row_number: int,
    uploaded_column: str,
    api_field: str,
    object_name: str,
    allowed_values: list[str],
    allowed_details: list[Any],
    all_picklist_details: list[Any],
    record_type_used: str | None,
    validation_source: str,
    is_required: bool,
    is_multipicklist: bool,
) -> tuple[list[dict[str, Any]], int, int, int]:
    issues: list[dict[str, Any]] = []
    valid_count = 0
    invalid_count = 0
    blank_required_count = 0

    if _is_blank(raw_value):
        if is_required:
            blank_required_count = 1
            invalid_count = 1
            issues.append(_issue(
                issue_id=f"picklist:{api_field}:{row_number}:blank",
                status=PICKLIST_STATUS_BLANK_REQUIRED,
                row=row_number,
                uploaded_column=uploaded_column,
                api_field=api_field,
                object_name=object_name,
                uploaded_value="",
                allowed_values=allowed_values,
                record_type_used=record_type_used,
                validation_source=validation_source,
                reason="Required picklist value is blank.",
            ))
        else:
            valid_count = 1
            issues.append(_issue(
                issue_id=f"picklist:{api_field}:{row_number}:blank-optional",
                status=PICKLIST_STATUS_VALID,
                row=row_number,
                uploaded_column=uploaded_column,
                api_field=api_field,
                object_name=object_name,
                uploaded_value="",
                allowed_values=allowed_values,
                record_type_used=record_type_used,
                validation_source=validation_source,
                reason="Optional blank value.",
            ))
        return issues, valid_count, invalid_count, blank_required_count

    original_value = str(raw_value)
    entries = _split_multipicklist_value(original_value) if is_multipicklist else [original_value]

    for entry_index, entry in enumerate(entries):
        entry_issue_id = (
            f"picklist:{api_field}:{row_number}:{entry_index}"
            if is_multipicklist
            else f"picklist:{api_field}:{row_number}"
        )
        entry_status, suggested, matching_label, required_api_name, reason = _compare_picklist_entry(
            entry,
            allowed_values,
            allowed_details,
            all_picklist_details=all_picklist_details,
            is_multipicklist=is_multipicklist,
        )
        if entry_status == PICKLIST_STATUS_VALID:
            valid_count += 1
            issues.append(_issue(
                issue_id=entry_issue_id,
                status=PICKLIST_STATUS_VALID,
                row=row_number,
                uploaded_column=uploaded_column,
                api_field=api_field,
                object_name=object_name,
                uploaded_value=entry,
                allowed_values=allowed_values,
                record_type_used=record_type_used,
                validation_source=validation_source,
                reason=reason,
                matching_display_label=matching_label,
                required_api_name=required_api_name or entry,
                blocking=False,
            ))
        elif entry_status == PICKLIST_STATUS_NEEDS_REVIEW:
            issues.append(_issue(
                issue_id=entry_issue_id,
                status=PICKLIST_STATUS_NEEDS_REVIEW,
                row=row_number,
                uploaded_column=uploaded_column,
                api_field=api_field,
                object_name=object_name,
                uploaded_value=entry,
                allowed_values=allowed_values,
                record_type_used=record_type_used,
                validation_source=validation_source,
                reason=reason,
                suggested_replacement=suggested,
                matching_display_label=matching_label,
                required_api_name=required_api_name,
                requires_approval=True,
                blocking=False,
            ))
        else:
            invalid_count += 1
            issues.append(_issue(
                issue_id=entry_issue_id,
                status=entry_status,
                row=row_number,
                uploaded_column=uploaded_column,
                api_field=api_field,
                object_name=object_name,
                uploaded_value=entry,
                allowed_values=allowed_values,
                record_type_used=record_type_used,
                validation_source=validation_source,
                reason=reason,
                suggested_replacement=suggested,
                matching_display_label=matching_label,
                required_api_name=required_api_name,
                requires_approval=bool(suggested),
                blocking=True,
            ))

    return issues, valid_count, invalid_count, blank_required_count


_PICKLIST_NOT_CONFIGURED_REASON = "This value is not configured for this Salesforce picklist."


def _compare_picklist_entry(
    entry: str,
    allowed_values: list[str],
    allowed_details: list[Any],
    all_picklist_details: list[Any],
    *,
    is_multipicklist: bool,
) -> tuple[str, str | None, str | None, str | None, str]:
    trimmed = entry.strip()
    if not trimmed:
        return PICKLIST_STATUS_VALID, None, None, None, "Blank multipicklist entry ignored."

    inactive_details = [detail for detail in all_picklist_details if not detail.is_active]
    inactive_detail = _find_inactive_match(trimmed, inactive_details)
    if inactive_detail is not None:
        invalid_status = (
            PICKLIST_STATUS_MULTI_INVALID if is_multipicklist else PICKLIST_STATUS_NEEDS_USER_ACTION
        )
        return (
            invalid_status,
            None,
            inactive_detail.label,
            inactive_detail.api_name,
            f"Inactive picklist value `{inactive_detail.api_name}`.",
        )

    for detail in allowed_details:
        if entry == detail.api_name:
            return (
                PICKLIST_STATUS_VALID,
                None,
                detail.label,
                detail.api_name,
                "Valid stored picklist value.",
            )

    for detail in allowed_details:
        if trimmed == detail.api_name and entry != detail.api_name:
            return (
                PICKLIST_STATUS_NEEDS_REVIEW,
                detail.api_name,
                detail.label,
                detail.api_name,
                f"Valid after trimming whitespace; use stored value `{detail.api_name}`.",
            )

    invalid_status = (
        PICKLIST_STATUS_MULTI_INVALID if is_multipicklist else PICKLIST_STATUS_NEEDS_USER_ACTION
    )
    return invalid_status, None, None, None, _PICKLIST_NOT_CONFIGURED_REASON


def _find_inactive_match(trimmed: str, inactive_details: list[Any]) -> Any | None:
    for detail in inactive_details:
        if trimmed == detail.api_name:
            return detail
    return None


def _split_multipicklist_value(value: str) -> list[str]:
    return [part.strip() for part in value.split(";") if part.strip()]


def _is_required_field(
    uploaded_column: str,
    api_field: str,
    field_def,
    template_context: TemplateContext,
) -> bool:
    if field_def.required:
        return True
    if template_context.template_definition:
        required_labels = template_context.template_definition.required_csv_labels
        normalized_uploaded = uploaded_column.lstrip("*")
        for label in required_labels:
            if label.lstrip("*") == normalized_uploaded:
                return True
            mapped_api = template_context.template_definition.csv_label_to_api.get(label)
            if mapped_api == api_field:
                return True
    return False


def _summary(
    *,
    uploaded_column: str,
    api_field: str,
    object_name: str,
    field_type: str,
    record_type_name: str | None,
    allowed_value_count: int,
    valid_row_count: int,
    invalid_row_count: int,
    blank_required_row_count: int,
    validation_source: str,
    fallback_warning: str | None,
    check_type: str = "field_identification",
) -> dict[str, Any]:
    return {
        "uploaded_column": uploaded_column,
        "salesforce_field": api_field,
        "object": object_name,
        "field": api_field,
        "field_type": field_type,
        "record_type": record_type_name,
        "allowed_value_count": allowed_value_count,
        "valid_row_count": valid_row_count,
        "invalid_row_count": invalid_row_count,
        "blank_required_row_count": blank_required_row_count,
        "validation_source": validation_source,
        "metadata_source": PICKLIST_METADATA_SOURCE_LOCAL,
        "fallback_warning": fallback_warning,
        "check_type": check_type,
    }


def _issue(
    *,
    issue_id: str,
    status: str,
    row: int | None,
    uploaded_column: str,
    api_field: str,
    object_name: str,
    uploaded_value: str,
    allowed_values: list[str],
    record_type_used: str | None,
    validation_source: str,
    reason: str,
    suggested_replacement: str | None = None,
    matching_display_label: str | None = None,
    required_api_name: str | None = None,
    requires_approval: bool = False,
    blocking: bool | None = None,
) -> dict[str, Any]:
    if blocking is None:
        blocking = status in {
            PICKLIST_STATUS_NEEDS_USER_ACTION,
            PICKLIST_STATUS_INVALID,
            PICKLIST_STATUS_BLANK_REQUIRED,
            PICKLIST_STATUS_MULTI_INVALID,
            PICKLIST_STATUS_NEEDS_REVIEW,
            PICKLIST_STATUS_METADATA_UNAVAILABLE,
        }
    return {
        "issue_id": issue_id,
        "status": status,
        "row": row,
        "uploaded_column": uploaded_column,
        "salesforce_api_field": api_field,
        "salesforce_field": api_field,
        "object": object_name,
        "uploaded_value": uploaded_value,
        "allowed_values": allowed_values,
        "record_type_used": record_type_used,
        "validation_source": validation_source,
        "metadata_source": PICKLIST_METADATA_SOURCE_LOCAL,
        "reason": reason,
        "message": reason,
        "suggested_replacement": suggested_replacement,
        "matching_display_label": matching_display_label,
        "required_api_name": required_api_name,
        "requires_approval": requires_approval,
        "blocking": blocking,
        "check_type": "value_validation",
    }


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _empty_result() -> dict[str, Any]:
    return {
        "object_name": None,
        "record_type_name": None,
        "use_mapped_columns": False,
        "field_summaries": [],
        "issues": [],
        "valid_count": 0,
        "invalid_count": 0,
        "blocking_issue_count": 0,
        "has_blocking_issues": False,
    }
