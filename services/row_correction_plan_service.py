"""Build row-level data quality correction plans."""

from __future__ import annotations

from typing import Any

import pandas as pd

from services.metadata_provider_factory import get_metadata_adapter
from adapters.sfdx_metadata.standard_field_supplements import supplement_object_fields
from services.field_mapping_service import get_confirmed_rename_map, get_excluded_columns
from services.template_service import TemplateContext, resolve_template
from validators.address_validator import resolve_address_fields, resolve_structured_address_fields, validate_addresses
from validators.blank_row_validator import is_row_blank, validate_blank_rows
from validators.boolean_validator import resolve_boolean_fields, validate_boolean_fields
from validators.csv_structure_validator import validate_csv_structure
from services.date_conversion_service import resolve_date_field_columns
from validators.date_validator import validate_dates
from validators.duplicate_key_validator import resolve_external_id_fields, validate_duplicate_keys
from validators.ean_validator import resolve_ean_fields, run_ean_live_lookup, validate_eans
from validators.federation_id_validator import resolve_federation_id_fields, validate_federation_ids
from validators.identifier_validator import resolve_identifier_fields, validate_identifiers
from validators.numeric_validator import resolve_numeric_fields, validate_numeric_fields
from validators.phone_validator import resolve_phone_fields, validate_phones
from validators.text_sanitization_validator import resolve_punctuation_fields, validate_text_sanitization
from validators.whitespace_validator import resolve_whitespace_fields, validate_whitespace


def build_row_correction_plan(
    df: pd.DataFrame,
    upload_method: str,
    template: str,
    mapping_rows: list[dict[str, Any]] | None = None,
    raw_csv_content: str | None = None,
    template_context: TemplateContext | None = None,
    source_date_format: str | None = None,
    post_conversion: bool = False,
) -> dict[str, Any]:
    """Inspect every row and build an approvable data-quality correction plan."""
    context = template_context or resolve_template(template)
    mapping_rows = mapping_rows or []
    rename_map = get_confirmed_rename_map(mapping_rows)
    active_columns = _active_columns(df, mapping_rows)

    object_fields = {}
    if context and context.salesforce_object:
        raw_fields = get_metadata_adapter().get_object_fields(context.salesforce_object)
        object_fields = supplement_object_fields(context.salesforce_object, raw_fields)

    mapped_api_fields = {
        column: rename_map.get(column, column)
        for column in active_columns
    }
    date_field_types = resolve_date_field_columns(
        active_columns,
        rename_map,
        context,
        object_fields,
    )
    identifier_fields = resolve_identifier_fields(active_columns, mapped_api_fields, object_fields)
    ean_fields = resolve_ean_fields(active_columns, mapped_api_fields)
    federation_fields = resolve_federation_id_fields(active_columns, mapped_api_fields)
    phone_fields = resolve_phone_fields(active_columns, mapped_api_fields, object_fields)
    address_fields = resolve_address_fields(active_columns)
    structured_address_fields = resolve_structured_address_fields(active_columns)
    numeric_fields = resolve_numeric_fields(
        [mapped_api_fields.get(column, column) for column in active_columns],
        object_fields,
    )
    numeric_columns = [
        column
        for column in active_columns
        if mapped_api_fields.get(column, column) in numeric_fields
    ]
    boolean_columns = [
        column
        for column in active_columns
        if mapped_api_fields.get(column, column) in resolve_boolean_fields(list(object_fields.keys()), object_fields)
    ]
    duplicate_fields = resolve_external_id_fields(active_columns, mapped_api_fields, object_fields)
    whitespace_fields = resolve_whitespace_fields(
        active_columns,
        mapped_api_fields,
        object_fields,
        phone_fields=phone_fields,
        address_fields=address_fields,
        numeric_fields=numeric_columns,
        date_fields=list(date_field_types.keys()),
        boolean_fields=boolean_columns,
    )
    punctuation_fields = resolve_punctuation_fields(
        active_columns,
        mapped_api_fields,
        excluded_fields=set(phone_fields + address_fields + ean_fields + federation_fields),
    )

    issues: list[dict[str, Any]] = []
    issues.extend(validate_csv_structure(raw_csv_content, len(df.columns)))
    issues.extend(validate_blank_rows(df))
    issues.extend(validate_whitespace(df, whitespace_fields))
    issues.extend(validate_text_sanitization(df, punctuation_fields))
    issues.extend(validate_dates(
        df,
        date_field_types,
        upload_method,
        source_format=source_date_format,
        post_conversion=post_conversion,
    ))
    issues.extend(validate_identifiers(df, identifier_fields))
    live_ean_lookup = run_ean_live_lookup(df, ean_fields, mapped_api_fields)
    issues.extend(validate_eans(df, ean_fields, live_lookup_result=live_ean_lookup))
    issues.extend(validate_federation_ids(df, federation_fields))
    issues.extend(validate_phones(df, phone_fields))
    issues.extend(validate_addresses(
        df,
        address_fields,
        structured_fields=structured_address_fields,
    ))
    issues.extend(validate_numeric_fields(df, numeric_columns))
    issues.extend(validate_boolean_fields(df, boolean_columns))
    issues.extend(validate_duplicate_keys(df, duplicate_fields))

    safe_issues = [issue for issue in issues if issue.get("safe")]
    confirmation_issues = [
        issue for issue in issues
        if issue.get("requires_confirmation") and not issue.get("safe")
    ]
    manual_review = [issue for issue in issues if issue.get("blocking")]

    return {
        "upload_method": upload_method,
        "template": template,
        "issues": issues,
        "safe_issues": safe_issues,
        "confirmation_issues": confirmation_issues,
        "manual_review": manual_review,
        "summary": _build_summary(issues),
        "has_fixable_issues": bool(safe_issues or confirmation_issues),
        "has_blocking_manual_review": bool(manual_review),
        "has_blocking_issues": bool(manual_review),
        "corrections_applied": False,
        "corrections_declined": False,
        "date_field_types": date_field_types,
        "live_ean_lookup": live_ean_lookup,
    }


def get_safe_issue_ids(plan: dict[str, Any]) -> set[str]:
    return {issue["issue_id"] for issue in plan.get("safe_issues", [])}


def get_fixable_issue_ids(plan: dict[str, Any]) -> set[str]:
    return {
        issue["issue_id"]
        for issue in plan.get("issues", [])
        if issue.get("safe") or issue.get("requires_confirmation")
    }


def apply_row_corrections(
    df: pd.DataFrame,
    plan: dict[str, Any],
    enabled_issue_ids: set[str],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Apply approved row-level corrections to a copy of the dataframe."""
    working = df.copy()
    change_log: list[dict[str, Any]] = []
    issue_map = {issue["issue_id"]: issue for issue in plan.get("issues", [])}

    blank_row_ids = [
        issue_id for issue_id in enabled_issue_ids
        if issue_map.get(issue_id, {}).get("category") == "blank_rows"
    ]
    if blank_row_ids:
        working, blank_log = _apply_blank_row_removals(working, blank_row_ids, issue_map)
        change_log.extend(blank_log)

    cell_issue_ids = enabled_issue_ids - set(blank_row_ids)
    for issue_id in cell_issue_ids:
        issue = issue_map.get(issue_id)
        if not issue:
            continue
        if issue.get("blocking") and not issue.get("safe"):
            continue
        if issue.get("category") == "blank_rows":
            continue

        field = issue.get("field")
        if not field or field not in working.columns:
            continue

        row_number = issue.get("row")
        original = issue.get("original_value", "")
        corrected = issue.get("proposed_value", "")
        if corrected == original:
            continue

        applied = False
        if row_number is not None:
            idx = row_number - 2
            if idx in working.index and str(working.at[idx, field]) == original:
                working.at[idx, field] = corrected
                applied = True

        if not applied:
            for idx, current in working[field].items():
                if str(current) == original:
                    working.at[idx, field] = corrected
                    applied = True
                    row_number = idx + 2
                    break

        if applied:
            change_log.append({
                "category": issue["category"],
                "row": row_number,
                "field": field,
                "original_value": original,
                "new_value": corrected,
                "reason": issue.get("reason", "Row correction applied"),
            })

    return working, change_log


def _apply_blank_row_removals(
    df: pd.DataFrame,
    blank_row_ids: set[str],
    issue_map: dict[str, dict[str, Any]],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    target_rows = {
        issue_map[issue_id]["row"] - 2
        for issue_id in blank_row_ids
        if issue_id in issue_map and issue_map[issue_id].get("row") is not None
    }
    change_log: list[dict[str, Any]] = []
    blank_indices = [
        idx for idx in df.index
        if is_row_blank(df.loc[idx]) and idx in target_rows
    ]
    for idx in blank_indices:
        change_log.append({
            "category": "blank_rows",
            "row": idx + 2,
            "field": None,
            "original_value": "(entire row blank)",
            "new_value": "(row removed)",
            "reason": "Blank row removed",
        })
    if blank_indices:
        df = df.drop(index=blank_indices).reset_index(drop=True)
    return df, change_log


def _active_columns(df: pd.DataFrame, mapping_rows: list[dict[str, Any]]) -> list[str]:
    excluded = get_excluded_columns(mapping_rows)
    return [column for column in df.columns if column not in excluded]


def _build_summary(issues: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "whitespace": {"issues": 0, "rows_affected": set()},
        "blank_rows": {"count": 0, "rows_affected": set()},
        "dates": {"convertible": 0, "ambiguous": 0, "invalid": 0, "rows_affected": set()},
        "identifiers": {"scientific_notation": 0, "leading_zeroes": 0, "manual": 0, "rows_affected": set()},
        "addresses": {"malformed_csv": 0, "whitespace": 0, "rows_affected": set()},
        "phones": {"formatting": 0, "rows_affected": set()},
        "numeric": {"issues": 0, "convertible": 0, "blocking": 0, "rows_affected": set()},
        "booleans": {"convertible": 0, "rows_affected": set()},
        "duplicates": {"duplicate_keys": 0, "rows_affected": set()},
        "csv_structure": {"malformed_rows": 0, "rows_affected": set()},
        "punctuation": {"issues": 0, "rows_affected": set()},
        "eans": {"issues": 0, "leading_zeroes": 0, "rows_affected": set()},
        "federation_ids": {"issues": 0, "leading_zeroes": 0, "rows_affected": set()},
        "salesforce_record_check": {"issues": 0, "rows_affected": set()},
        "manual_review": 0,
    }

    for issue in issues:
        category = issue["category"]
        reason = issue.get("reason", "").lower()
        row = issue.get("row")

        if category == "whitespace":
            summary["whitespace"]["issues"] += 1
            if row:
                summary["whitespace"]["rows_affected"].add(row)
        elif category == "blank_rows":
            summary["blank_rows"]["count"] += 1
            if row:
                summary["blank_rows"]["rows_affected"].add(row)
        elif category == "dates":
            if row:
                summary["dates"]["rows_affected"].add(row)
            if "ambiguous" in reason:
                summary["dates"]["ambiguous"] += 1
            elif issue.get("requires_confirmation"):
                summary["dates"]["invalid"] += 1
            elif issue.get("safe"):
                summary["dates"]["convertible"] += 1
            else:
                summary["dates"]["invalid"] += 1
        elif category == "identifiers":
            if row:
                summary["identifiers"]["rows_affected"].add(row)
            if "scientific notation" in reason:
                summary["identifiers"]["scientific_notation"] += 1
            elif issue.get("safe"):
                summary["identifiers"]["leading_zeroes"] += 1
            else:
                summary["identifiers"]["manual"] += 1
        elif category == "addresses":
            if row:
                summary["addresses"]["rows_affected"].add(row)
            if issue.get("safe"):
                summary["addresses"]["whitespace"] += 1
        elif category == "phones":
            summary["phones"]["formatting"] += 1
            if row:
                summary["phones"]["rows_affected"].add(row)
        elif category == "numeric":
            summary["numeric"]["issues"] += 1
            if row:
                summary["numeric"]["rows_affected"].add(row)
            if issue.get("safe"):
                summary["numeric"]["convertible"] += 1
            elif issue.get("blocking"):
                summary["numeric"]["blocking"] += 1
        elif category == "booleans" and issue.get("requires_confirmation"):
            summary["booleans"]["convertible"] += 1
            if row:
                summary["booleans"]["rows_affected"].add(row)
        elif category == "duplicates":
            summary["duplicates"]["duplicate_keys"] += 1
            if row:
                summary["duplicates"]["rows_affected"].add(row)
        elif category == "csv_structure":
            summary["csv_structure"]["malformed_rows"] += 1
            if row:
                summary["csv_structure"]["rows_affected"].add(row)
        elif category == "punctuation":
            summary["punctuation"]["issues"] += 1
            if row:
                summary["punctuation"]["rows_affected"].add(row)
        elif category == "eans":
            summary["eans"]["issues"] += 1
            if "leading zero" in reason or issue.get("issue_id", "").startswith("eans:leading-zero"):
                summary["eans"]["leading_zeroes"] += 1
            if row:
                summary["eans"]["rows_affected"].add(row)
        elif category == "federation_ids":
            summary["federation_ids"]["issues"] += 1
            if "leading zero" in reason or issue.get("issue_id", "").startswith("federation_id:leading-zero"):
                summary["federation_ids"]["leading_zeroes"] += 1
            if row:
                summary["federation_ids"]["rows_affected"].add(row)
        elif category == "salesforce_record_check":
            summary["salesforce_record_check"]["issues"] += 1
            if row:
                summary["salesforce_record_check"]["rows_affected"].add(row)
        if issue.get("blocking"):
            summary["manual_review"] += 1

    for section in summary.values():
        if isinstance(section, dict) and "rows_affected" in section:
            section["rows_affected"] = len(section["rows_affected"])

    return summary
