"""Live Salesforce record existence validation for Insert and Update."""

from __future__ import annotations

from typing import Any

import pandas as pd

from clients.salesforce_client import SalesforceQueryClient, get_salesforce_client
from core.config import LOAD_ACTION_NOT_EVALUATED
from services.constants import (
    RECORD_CHECK_DUPLICATE_MATCH,
    RECORD_CHECK_FOUND,
    RECORD_CHECK_NEW_IDENTIFIER,
    RECORD_CHECK_NOT_EVALUATED,
    RECORD_CHECK_NOT_FOUND,
    RECORD_CHECK_POSSIBLE_EXISTING,
    RECORD_CHECK_SKIPPED,
    RECORD_CHECK_UNAVAILABLE,
)
from services.external_id_discovery_service import (
    default_identifier_field,
    discover_identifier_fields,
    resolve_identifier_column,
)
from services.salesforce_record_lookup_service import lookup_records_by_field
from services.template_service import TemplateContext


def validate_record_existence(
    df: pd.DataFrame,
    mapping_rows: list[dict[str, Any]],
    load_operation: str | None,
    template_context: TemplateContext,
    *,
    identifier_field: str | None = None,
    skip_live_check: bool = False,
    use_mapped_columns: bool = False,
    client: SalesforceQueryClient | None = None,
) -> dict[str, Any]:
    """Validate uploaded identifiers against live Salesforce for Insert/Update."""
    if not load_operation:
        return not_evaluated_record_existence_result()

    object_name = template_context.salesforce_object or ""
    mapped_api_fields = {
        row.get("confirmed_api_field")
        for row in mapping_rows
        if row.get("confirmed_api_field")
    }

    identifier_candidates = discover_identifier_fields(
        object_name,
        mapped_api_fields=mapped_api_fields,
    )
    selected_field = identifier_field or default_identifier_field(
        object_name,
        mapped_api_fields=mapped_api_fields,
    )

    if skip_live_check:
        return _skipped_result(
            load_operation,
            object_name,
            selected_field,
            identifier_candidates,
        )

    client = client or get_salesforce_client()
    connection = client.test_connection()
    if not connection.get("available"):
        return _unavailable_result(
            load_operation,
            object_name,
            selected_field,
            identifier_candidates,
            connection,
        )

    if not selected_field:
        return {
            "load_operation": load_operation,
            "status": load_operation,
            "evaluated": True,
            "connection": connection,
            "object_name": object_name,
            "identifier_field": None,
            "identifier_candidates": identifier_candidates,
            "row_results": [],
            "summary": {
                "total_rows": len(df),
                "checked_rows": 0,
                "existing_count": 0,
                "missing_count": 0,
                "duplicate_match_count": 0,
                "new_identifier_count": 0,
                "possible_existing_count": 0,
            },
            "issues": [{
                "severity": "error",
                "field": None,
                "message": (
                    "No reliable identifier field was discovered in metadata. "
                    "Map an External ID or unique business key before running live checks."
                ),
            }],
            "manual_review": [],
            "blocks_download": load_operation == "Update",
            "allows_id_population": False,
            "message": "Reliable identifier field is required for live record checks.",
        }

    column_name = resolve_identifier_column(
        selected_field,
        mapping_rows,
        use_mapped_columns=use_mapped_columns,
        df_columns=list(df.columns),
    )
    if not column_name or column_name not in df.columns:
        return {
            "load_operation": load_operation,
            "status": load_operation,
            "evaluated": True,
            "connection": connection,
            "object_name": object_name,
            "identifier_field": selected_field,
            "identifier_candidates": identifier_candidates,
            "row_results": [],
            "summary": {
                "total_rows": len(df),
                "checked_rows": 0,
                "existing_count": 0,
                "missing_count": 0,
                "duplicate_match_count": 0,
                "new_identifier_count": 0,
                "possible_existing_count": 0,
            },
            "issues": [{
                "severity": "error",
                "field": selected_field,
                "message": f"Mapped identifier column for `{selected_field}` was not found in the file.",
            }],
            "manual_review": [],
            "blocks_download": True,
            "allows_id_population": False,
            "message": "Identifier column mapping is required.",
        }

    values = [
        str(value).strip()
        for value in df[column_name].tolist()
        if value is not None and str(value).strip()
    ]
    lookup = lookup_records_by_field(
        client,
        object_name,
        selected_field,
        values,
        include_salesforce_id=True,
    )

    row_results: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    manual_review: list[dict[str, Any]] = []
    summary = {
        "total_rows": len(df),
        "checked_rows": 0,
        "existing_count": 0,
        "missing_count": 0,
        "duplicate_match_count": 0,
        "new_identifier_count": 0,
        "possible_existing_count": 0,
    }

    for idx, raw_value in df[column_name].items():
        row_number = idx + 2
        if _is_blank(raw_value):
            if load_operation == "Update":
                manual_review.append({
                    "row": row_number,
                    "field": selected_field,
                    "value": "",
                    "reason": "Update requires a populated identifier value.",
                })
            continue

        summary["checked_rows"] += 1
        normalized = str(raw_value).strip().casefold()
        matches = lookup["matches_by_value"].get(normalized, [])
        row_status, row_issue = _evaluate_row(
            load_operation=load_operation,
            row_number=row_number,
            identifier_field=selected_field,
            uploaded_value=str(raw_value).strip(),
            matches=matches,
        )
        row_results.append({
            "row": row_number,
            "uploaded_column": column_name,
            "identifier_field": selected_field,
            "uploaded_value": str(raw_value).strip(),
            "status": row_status,
            "match_count": len(matches),
            "salesforce_ids": [match.get("Id", "") for match in matches if match.get("Id")],
            "matches": matches,
        })

        if row_status == RECORD_CHECK_POSSIBLE_EXISTING:
            summary["possible_existing_count"] += 1
            summary["existing_count"] += 1
            issues.append({
                "severity": "warning",
                "field": selected_field,
                "row": row_number,
                "message": (
                    f"Possible existing record for `{raw_value}` on {object_name}."
                ),
            })
        elif row_status == RECORD_CHECK_NEW_IDENTIFIER:
            summary["new_identifier_count"] += 1
        elif row_status == RECORD_CHECK_FOUND:
            summary["existing_count"] += 1
        elif row_status == RECORD_CHECK_NOT_FOUND:
            summary["missing_count"] += 1
            issues.append({
                "severity": "error",
                "field": selected_field,
                "row": row_number,
                "message": f"No existing Salesforce record found for `{raw_value}`.",
            })
        elif row_status == RECORD_CHECK_DUPLICATE_MATCH:
            summary["duplicate_match_count"] += 1
            summary["existing_count"] += 1
            issues.append({
                "severity": "error",
                "field": selected_field,
                "row": row_number,
                "message": (
                    f"Duplicate Salesforce matches found for `{raw_value}` "
                    f"({len(matches)} records)."
                ),
            })

        if row_issue:
            manual_review.append(row_issue)

    blocks_download = any(issue["severity"] == "error" for issue in issues) or bool(
        manual_review
    )
    if load_operation == "Update" and summary["missing_count"]:
        blocks_download = True

    return {
        "load_operation": load_operation,
        "status": load_operation,
        "evaluated": True,
        "connection": connection,
        "object_name": object_name,
        "identifier_field": selected_field,
        "identifier_candidates": identifier_candidates,
        "lookup": lookup,
        "row_results": row_results,
        "summary": summary,
        "issues": issues,
        "manual_review": manual_review,
        "blocks_download": blocks_download,
        "allows_id_population": False,
        "message": _build_message(load_operation, summary, connection),
    }


def not_evaluated_record_existence_result() -> dict[str, Any]:
    return {
        "load_operation": None,
        "status": RECORD_CHECK_NOT_EVALUATED,
        "evaluated": False,
        "connection": {"available": False, "status": "not_evaluated"},
        "object_name": None,
        "identifier_field": None,
        "identifier_candidates": [],
        "row_results": [],
        "summary": {},
        "issues": [],
        "manual_review": [],
        "blocks_download": False,
        "allows_id_population": False,
        "message": LOAD_ACTION_NOT_EVALUATED,
    }


def build_record_existence_report_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten row results for CSV download."""
    return [
        {
            "Row": row.get("row"),
            "Uploaded Column": row.get("uploaded_column"),
            "Identifier Field": row.get("identifier_field"),
            "Uploaded Value": row.get("uploaded_value"),
            "Status": row.get("status"),
            "Match Count": row.get("match_count"),
            "Salesforce Ids": ";".join(row.get("salesforce_ids") or []),
        }
        for row in result.get("row_results", [])
    ]


def _evaluate_row(
    *,
    load_operation: str,
    row_number: int,
    identifier_field: str,
    uploaded_value: str,
    matches: list[dict[str, str]],
) -> tuple[str, dict[str, Any] | None]:
    if load_operation == "Insert":
        if not matches:
            return RECORD_CHECK_NEW_IDENTIFIER, None
        return RECORD_CHECK_POSSIBLE_EXISTING, {
            "row": row_number,
            "field": identifier_field,
            "value": uploaded_value,
            "reason": "Identifier already exists in Salesforce. Review before Insert.",
        }

    if not matches:
        return RECORD_CHECK_NOT_FOUND, {
            "row": row_number,
            "field": identifier_field,
            "value": uploaded_value,
            "reason": "No matching Salesforce record found for Update.",
        }
    if len(matches) > 1:
        return RECORD_CHECK_DUPLICATE_MATCH, {
            "row": row_number,
            "field": identifier_field,
            "value": uploaded_value,
            "reason": "Multiple Salesforce records matched this identifier.",
        }
    return RECORD_CHECK_FOUND, None


def _skipped_result(
    load_operation: str,
    object_name: str,
    identifier_field: str | None,
    identifier_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "load_operation": load_operation,
        "status": RECORD_CHECK_SKIPPED,
        "evaluated": False,
        "connection": {"available": False, "status": "skipped"},
        "object_name": object_name,
        "identifier_field": identifier_field,
        "identifier_candidates": identifier_candidates,
        "row_results": [],
        "summary": {},
        "issues": [],
        "manual_review": [],
        "blocks_download": False,
        "allows_id_population": False,
        "message": "Live Salesforce record check was skipped by user choice.",
    }


def _unavailable_result(
    load_operation: str,
    object_name: str,
    identifier_field: str | None,
    identifier_candidates: list[dict[str, Any]],
    connection: dict[str, Any],
) -> dict[str, Any]:
    return {
        "load_operation": load_operation,
        "status": RECORD_CHECK_UNAVAILABLE,
        "evaluated": False,
        "connection": connection,
        "object_name": object_name,
        "identifier_field": identifier_field,
        "identifier_candidates": identifier_candidates,
        "row_results": [],
        "summary": {},
        "issues": [{
            "severity": "warning",
            "field": None,
            "message": RECORD_CHECK_UNAVAILABLE,
        }],
        "manual_review": [],
        "blocks_download": False,
        "allows_id_population": False,
        "message": (
            "Live Salesforce Check Unavailable. "
            "Preparation continued without marking records as missing."
        ),
    }


def _build_message(
    load_operation: str,
    summary: dict[str, int],
    connection: dict[str, Any],
) -> str:
    if not connection.get("available"):
        return RECORD_CHECK_UNAVAILABLE
    if load_operation == "Insert":
        return (
            f"Insert check complete: {summary.get('new_identifier_count', 0)} new identifiers, "
            f"{summary.get('possible_existing_count', 0)} possible existing records."
        )
    return (
        f"Update check complete: {summary.get('existing_count', 0)} matched, "
        f"{summary.get('missing_count', 0)} not found, "
        f"{summary.get('duplicate_match_count', 0)} duplicate matches."
    )


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())
