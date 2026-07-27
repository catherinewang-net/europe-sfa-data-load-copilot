"""Metadata and live Salesforce lookup validation."""

from __future__ import annotations

from typing import Any

import pandas as pd

from clients.salesforce_client import SalesforceQueryClient, get_salesforce_client
from services.constants import (
    LOOKUP_METHOD_SALESFORCE_ID,
    LOOKUP_METHOD_UNKNOWN,
    LOOKUP_STATUS_MULTIPLE,
    LOOKUP_STATUS_NEEDS_REVIEW,
    LOOKUP_STATUS_NOT_CHECKED,
    LOOKUP_STATUS_NOT_FOUND,
    LOOKUP_STATUS_PARENT_FIRST,
    LOOKUP_STATUS_VALID,
    MAPPING_SOURCE_SALESFORCE,
)
from services.lookup_field_detection_service import (
    discover_mapped_lookup_fields,
    infer_matching_method,
    is_plausible_lookup_value,
    resolve_lookup_column,
)
from services.salesforce_record_lookup_service import lookup_records_by_field
from services.template_service import TemplateContext, get_adapter


def validate_lookups(
    df: pd.DataFrame,
    mapping_rows: list[dict[str, Any]],
    template_context: TemplateContext,
    *,
    use_mapped_columns: bool = False,
    skip_live_check: bool = False,
    client: SalesforceQueryClient | None = None,
    dependency_rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate lookup/reference fields using metadata and optional live Salesforce checks."""
    object_name = template_context.salesforce_object or ""
    if not object_name or not mapping_rows:
        return _empty_result(object_name, template_context.template_name)

    adapter = get_adapter()
    lookup_fields = discover_mapped_lookup_fields(
        object_name,
        mapping_rows,
        adapter=adapter,
        metadata_source=MAPPING_SOURCE_SALESFORCE,
    )
    dependency_rules = dependency_rules or []
    dependency_hints = _dependency_field_hints(
        template_context.template_name,
        dependency_rules,
        mapping_rows,
    )

    client = client or get_salesforce_client()
    connection = client.test_connection()
    live_available = bool(connection.get("available")) and not skip_live_check

    field_summaries: list[dict[str, Any]] = []
    row_results: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    manual_review: list[dict[str, Any]] = []
    summary = {
        "lookup_fields_checked": len(lookup_fields),
        "rows_checked": 0,
        "valid_count": 0,
        "needs_review_count": 0,
        "not_found_count": 0,
        "multiple_match_count": 0,
        "not_checked_count": 0,
        "parent_first_count": 0,
    }

    live_lookups: dict[tuple[str, str], dict[str, Any]] = {}
    if live_available:
        live_lookups = _prepare_live_lookups(
            df,
            mapping_rows,
            lookup_fields,
            dependency_hints,
            client,
            use_mapped_columns=use_mapped_columns,
        )

    for field_info in lookup_fields:
        api_field = field_info["field_api_name"]
        column_name = resolve_lookup_column(
            api_field,
            mapping_rows,
            use_mapped_columns=use_mapped_columns,
            df_columns=list(df.columns),
        )
        if not column_name or column_name not in df.columns:
            continue

        referenced_object = field_info["referenced_object"]
        if referenced_object == "Unknown":
            field_summaries.append(_field_summary(field_info, column_name, checked_rows=0, status=LOOKUP_STATUS_NOT_CHECKED))
            continue

        checked_rows = 0
        field_valid = 0
        field_review = 0
        field_not_found = 0
        field_multiple = 0
        field_not_checked = 0
        field_parent_first = 0

        for idx, raw_value in df[column_name].items():
            row_number = idx + 2
            if _is_blank(raw_value):
                if field_info["required"]:
                    status = LOOKUP_STATUS_NEEDS_REVIEW
                    reason = f"Required lookup `{field_info['field_label']}` is blank."
                    parent_action = "Populate the lookup value or exclude the row."
                    matching_method = LOOKUP_METHOD_UNKNOWN
                    summary["rows_checked"] += 1
                    checked_rows += 1
                    field_review += 1
                    summary["needs_review_count"] += 1
                    row_results.append(_row_result(
                        row_number, field_info, column_name, "", referenced_object,
                        matching_method, status, reason, parent_action,
                    ))
                    issues.append(_issue(row_number, api_field, reason, blocking=True))
                    manual_review.append(_manual_review(row_number, api_field, reason))
                continue

            uploaded_value = str(raw_value).strip()
            summary["rows_checked"] += 1
            checked_rows += 1
            hint = dependency_hints.get(api_field)
            matching_method, identifier_field = infer_matching_method(
                lookup_field=api_field,
                uploaded_value=uploaded_value,
                referenced_object=referenced_object,
                adapter=adapter,
                dependency_hint=hint,
            )

            if not is_plausible_lookup_value(uploaded_value, matching_method):
                status = LOOKUP_STATUS_NEEDS_REVIEW
                reason = (
                    f"Value `{uploaded_value}` is not a plausible {matching_method} "
                    f"for `{field_info['field_label']}`."
                )
                parent_action = "Confirm matching method or correct the uploaded value."
                field_review += 1
                summary["needs_review_count"] += 1
                row_results.append(_row_result(
                    row_number, field_info, column_name, uploaded_value, referenced_object,
                    matching_method, status, reason, parent_action,
                ))
                issues.append(_issue(row_number, api_field, reason, blocking=True))
                manual_review.append(_manual_review(row_number, api_field, reason))
                continue

            if live_available and identifier_field:
                lookup_key = (referenced_object, identifier_field)
                matches = live_lookups.get(lookup_key, {}).get("matches_by_value", {}).get(
                    uploaded_value.casefold(), []
                )
                if len(matches) == 1:
                    status = LOOKUP_STATUS_VALID
                    reason = "Referenced record confirmed in Salesforce."
                    parent_action = "None"
                    field_valid += 1
                    summary["valid_count"] += 1
                elif len(matches) > 1:
                    status = LOOKUP_STATUS_MULTIPLE
                    reason = f"Multiple Salesforce records matched `{uploaded_value}`."
                    parent_action = "Resolve duplicate matches before upload."
                    field_multiple += 1
                    summary["multiple_match_count"] += 1
                    issues.append(_issue(row_number, api_field, reason, blocking=True))
                    manual_review.append(_manual_review(row_number, api_field, reason))
                else:
                    status = LOOKUP_STATUS_NOT_FOUND
                    reason = f"No Salesforce record found for `{uploaded_value}` on {referenced_object}."
                    parent_action = "Load the parent record first or correct the reference."
                    field_not_found += 1
                    summary["not_found_count"] += 1
                    issues.append(_issue(row_number, api_field, reason, blocking=True))
                    manual_review.append(_manual_review(row_number, api_field, reason))
            elif hint and not live_available:
                status = LOOKUP_STATUS_PARENT_FIRST
                reason = (
                    f"`{uploaded_value}` references {referenced_object}. "
                    f"Parent data ({rule_parent_template(dependency_rules, api_field, template_context.template_name) or 'parent template'}) must be loaded first."
                )
                parent_action = f"Load parent template data before {template_context.template_name}."
                field_parent_first += 1
                summary["parent_first_count"] += 1
                issues.append(_issue(row_number, api_field, reason, blocking=True))
                manual_review.append(_manual_review(row_number, api_field, reason))
            else:
                status = LOOKUP_STATUS_NEEDS_REVIEW
                reason = (
                    "Lookup field identified; live existence was not checked "
                    "or matching method is not confirmed."
                )
                parent_action = "Confirm matching method or connect Salesforce for live lookup."
                field_review += 1
                summary["needs_review_count"] += 1
                if matching_method == LOOKUP_METHOD_UNKNOWN:
                    summary["not_checked_count"] += 1
                    field_not_checked += 1

            row_results.append(_row_result(
                row_number, field_info, column_name, uploaded_value, referenced_object,
                matching_method, status, reason, parent_action,
            ))

        field_summaries.append(_field_summary(
            field_info,
            column_name,
            checked_rows=checked_rows,
            valid_count=field_valid,
            needs_review_count=field_review,
            not_found_count=field_not_found,
            multiple_match_count=field_multiple,
            not_checked_count=field_not_checked,
            parent_first_count=field_parent_first,
        ))

    has_blocking_issues = any(
        row.get("status") in {
            LOOKUP_STATUS_NOT_FOUND,
            LOOKUP_STATUS_MULTIPLE,
            LOOKUP_STATUS_PARENT_FIRST,
        }
        for row in row_results
    ) or any(issue.get("blocking") for issue in issues)
    metadata_only = not live_available
    blocks_download = has_blocking_issues and (
        not metadata_only or summary.get("parent_first_count", 0) > 0
    )

    return {
        "evaluated": True,
        "metadata_only": metadata_only,
        "connection": connection,
        "template": template_context.template_name,
        "object_name": object_name,
        "lookup_fields": lookup_fields,
        "field_summaries": field_summaries,
        "row_results": row_results,
        "summary": summary,
        "issues": issues,
        "manual_review": manual_review,
        "has_blocking_issues": has_blocking_issues,
        "blocks_download": blocks_download,
        "message": _build_message(summary, metadata_only),
    }


def build_lookup_validation_report_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten lookup validation results for CSV download."""
    return [
        {
            "Row": row.get("row"),
            "Source Object": row.get("source_object"),
            "Lookup Field": row.get("lookup_field"),
            "Uploaded Value": row.get("uploaded_value"),
            "Referenced Object": row.get("referenced_object"),
            "Matching Method": row.get("matching_method"),
            "Status": row.get("status"),
            "Reason": row.get("reason"),
            "Parent Action": row.get("parent_action"),
        }
        for row in result.get("row_results", [])
    ]


def _prepare_live_lookups(
    df: pd.DataFrame,
    mapping_rows: list[dict[str, Any]],
    lookup_fields: list[dict[str, Any]],
    dependency_hints: dict[str, str],
    client: SalesforceQueryClient,
    *,
    use_mapped_columns: bool,
) -> dict[tuple[str, str], dict[str, Any]]:
    grouped_values: dict[tuple[str, str], set[str]] = {}
    adapter = get_adapter()

    for field_info in lookup_fields:
        api_field = field_info["field_api_name"]
        referenced_object = field_info["referenced_object"]
        if referenced_object == "Unknown":
            continue
        column_name = resolve_lookup_column(
            api_field,
            mapping_rows,
            use_mapped_columns=use_mapped_columns,
            df_columns=list(df.columns),
        )
        if not column_name or column_name not in df.columns:
            continue

        for raw_value in df[column_name].tolist():
            if _is_blank(raw_value):
                continue
            uploaded_value = str(raw_value).strip()
            _, identifier_field = infer_matching_method(
                lookup_field=api_field,
                uploaded_value=uploaded_value,
                referenced_object=referenced_object,
                adapter=adapter,
                dependency_hint=dependency_hints.get(api_field),
            )
            if not identifier_field:
                continue
            grouped_values.setdefault((referenced_object, identifier_field), set()).add(uploaded_value)

    results: dict[tuple[str, str], dict[str, Any]] = {}
    for (referenced_object, identifier_field), values in grouped_values.items():
        results[(referenced_object, identifier_field)] = lookup_records_by_field(
            client,
            referenced_object,
            identifier_field,
            sorted(values),
            include_salesforce_id=True,
        )
    return results


def rule_parent_template(
    rules: list[dict[str, Any]],
    api_field: str,
    template: str,
) -> str | None:
    for rule in rules:
        if rule.get("template") != template:
            continue
        field = rule.get("field")
        if not field:
            continue
        if str(field).lstrip("*") == api_field or field == api_field:
            return rule.get("parent_template")
    return None


def _dependency_field_hints(
    template: str,
    rules: list[dict[str, Any]],
    mapping_rows: list[dict[str, Any]],
) -> dict[str, str]:
    hints: dict[str, str] = {}
    uploaded_to_api = {
        str(row.get("uploaded_column") or row.get("dit_column") or ""): row.get("confirmed_api_field")
        for row in mapping_rows
        if row.get("confirmed_api_field")
    }
    for rule in rules:
        if rule.get("template") != template:
            continue
        field = rule.get("field")
        parent_field = rule.get("parent_field")
        if not field or not parent_field:
            continue
        api_field = uploaded_to_api.get(str(field)) or str(field).lstrip("*")
        for row in mapping_rows:
            if row.get("confirmed_api_field") and (
                row.get("uploaded_column") == field
                or row.get("dit_column") == field
            ):
                api_field = row["confirmed_api_field"]
                break
        hints[str(api_field)] = str(parent_field).lstrip("*")
    return hints


def _empty_result(object_name: str, template: str | None) -> dict[str, Any]:
    return {
        "evaluated": False,
        "metadata_only": True,
        "connection": {"available": False, "status": "not_evaluated"},
        "template": template,
        "object_name": object_name,
        "lookup_fields": [],
        "field_summaries": [],
        "row_results": [],
        "summary": {
            "lookup_fields_checked": 0,
            "rows_checked": 0,
            "valid_count": 0,
            "needs_review_count": 0,
            "not_found_count": 0,
            "multiple_match_count": 0,
            "not_checked_count": 0,
            "parent_first_count": 0,
        },
        "issues": [],
        "manual_review": [],
        "has_blocking_issues": False,
        "blocks_download": False,
        "message": "No lookup fields were evaluated.",
    }


def _field_summary(field_info: dict[str, Any], column_name: str, **counts: Any) -> dict[str, Any]:
    return {
        "source_object": field_info["source_object"],
        "lookup_field": field_info["field_api_name"],
        "field_label": field_info["field_label"],
        "uploaded_column": column_name,
        "referenced_object": field_info["referenced_object"],
        "relationship_type": field_info["relationship_type"],
        "required": field_info["required"],
        "metadata_source": field_info["metadata_source"],
        **counts,
    }


def _row_result(
    row_number: int,
    field_info: dict[str, Any],
    column_name: str,
    uploaded_value: str,
    referenced_object: str,
    matching_method: str,
    status: str,
    reason: str,
    parent_action: str,
) -> dict[str, Any]:
    return {
        "row": row_number,
        "source_object": field_info["source_object"],
        "source_record_name": uploaded_value,
        "lookup_field": field_info["field_api_name"],
        "field_label": field_info["field_label"],
        "uploaded_column": column_name,
        "uploaded_value": uploaded_value,
        "referenced_object": referenced_object,
        "matching_method": matching_method,
        "status": status,
        "reason": reason,
        "parent_action": parent_action,
    }


def _issue(row_number: int, field: str, message: str, *, blocking: bool) -> dict[str, Any]:
    return {
        "validator": "lookup",
        "severity": "error" if blocking else "warning",
        "row": row_number,
        "field": field,
        "message": message,
        "blocking": blocking,
    }


def _manual_review(row_number: int, field: str, reason: str) -> dict[str, Any]:
    return {"row": row_number, "field": field, "reason": reason}


def _build_message(summary: dict[str, int], metadata_only: bool) -> str:
    if metadata_only:
        return (
            f"Metadata lookup check complete: {summary.get('needs_review_count', 0)} need review, "
            f"{summary.get('parent_first_count', 0)} require parent loads first."
        )
    return (
        f"Lookup check complete: {summary.get('valid_count', 0)} valid, "
        f"{summary.get('not_found_count', 0)} not found, "
        f"{summary.get('multiple_match_count', 0)} multiple matches."
    )


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, float) and pd.isna(value)) or not str(value).strip()
