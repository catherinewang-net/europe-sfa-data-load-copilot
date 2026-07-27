"""Unified preparation flow helpers for header and data phases."""

from __future__ import annotations

from typing import Any

from core.config import READINESS_STATUS
from services.preparation_task_service import is_preparation_only


def build_data_preparation_summary(
    *,
    mapping_rows: list[dict] | None = None,
    row_correction_plan: dict[str, Any] | None = None,
    workbench_plan: dict[str, Any] | None = None,
    picklist_validation: dict[str, Any] | None = None,
) -> dict[str, int]:
    """Aggregate header and row-level preparation counts for the review UI."""
    mapping_rows = mapping_rows or []
    row_summary = (row_correction_plan or {}).get("summary", {})
    prep_summary = (workbench_plan or {}).get("summary", {})
    picklist_validation = picklist_validation or {}

    headers_renamed = prep_summary.get("rename", 0)
    columns_excluded = prep_summary.get("exclude_extra_column", 0)
    if not columns_excluded:
        columns_excluded = sum(
            1 for row in mapping_rows
            if row.get("status") == "Do Not Include" or row.get("action") == "exclude"
        )

    dates = row_summary.get("dates", {})
    identifiers = row_summary.get("identifiers", {})
    csv_structure = row_summary.get("csv_structure", {})
    punctuation = row_summary.get("punctuation", {})
    eans = row_summary.get("eans", {})
    federation_ids = row_summary.get("federation_ids", {})
    salesforce_record_check = row_summary.get("salesforce_record_check", {})
    phones = row_summary.get("phones", {})
    addresses = row_summary.get("addresses", {})
    whitespace = row_summary.get("whitespace", {})
    blank_rows = row_summary.get("blank_rows", {})
    numeric = row_summary.get("numeric", {})

    invalid_picklist = picklist_validation.get("invalid_count", 0)
    if not invalid_picklist:
        invalid_picklist = sum(
            1 for issue in picklist_validation.get("issues", [])
            if issue.get("status") in {
                "Needs User Action",
                "Invalid Picklist Value",
                "Multipicklist Value Invalid",
            }
        )

    picklist_rows = len({
        issue.get("row")
        for issue in picklist_validation.get("issues", [])
        if issue.get("row") is not None
        and issue.get("status") in {
            "Needs User Action",
            "Invalid Picklist Value",
            "Multipicklist Value Invalid",
            "Blank Required Value",
            "Needs Review",
        }
    })

    return {
        "headers_renamed": headers_renamed,
        "columns_excluded": columns_excluded,
        "dates_converted": dates.get("convertible", 0) + prep_summary.get("convert_dates", 0),
        "whitespace_issues": whitespace.get("issues", 0),
        "whitespace_rows": whitespace.get("rows_affected", 0),
        "blank_row_count": blank_rows.get("count", 0),
        "blank_row_rows": blank_rows.get("rows_affected", blank_rows.get("count", 0)),
        "date_issues": (
            dates.get("convertible", 0)
            + dates.get("ambiguous", 0)
            + dates.get("invalid", 0)
        ),
        "date_rows": dates.get("rows_affected", 0),
        "picklist_issues": invalid_picklist,
        "picklist_rows": picklist_rows,
        "phone_issues": phones.get("formatting", 0),
        "phone_rows": phones.get("rows_affected", 0),
        "address_issues": addresses.get("whitespace", 0),
        "address_rows": addresses.get("rows_affected", 0),
        "numeric_issues": numeric.get("issues", 0),
        "numeric_convertible": numeric.get("convertible", 0),
        "numeric_rows": numeric.get("rows_affected", 0),
        "identifier_issues": (
            identifiers.get("leading_zeroes", 0)
            + identifiers.get("scientific_notation", 0)
            + identifiers.get("manual", 0)
        ),
        "identifier_rows": identifiers.get("rows_affected", 0),
        "whitespace_fixes": whitespace.get("issues", 0) + addresses.get("whitespace", 0),
        "leading_zero_issues": (
            eans.get("leading_zeroes", 0)
            + federation_ids.get("leading_zeroes", 0)
            + identifiers.get("scientific_notation", 0)
        ),
        "malformed_rows": csv_structure.get("malformed_rows", 0),
        "punctuation_issues": punctuation.get("issues", 0),
        "ean_issues": eans.get("issues", 0),
        "federation_id_issues": federation_ids.get("issues", 0),
        "salesforce_record_issues": salesforce_record_check.get("issues", 0),
        "invalid_picklist_values": invalid_picklist,
        "phone_warnings": phones.get("formatting", 0),
        "address_warnings": addresses.get("whitespace", 0),
    }


def build_preparation_review_sections(
    *,
    row_correction_plan: dict[str, Any] | None = None,
    picklist_validation: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build structured review sections for the data preparation UI."""
    row_summary = (row_correction_plan or {}).get("summary", {})
    picklist_validation = picklist_validation or {}
    row_plan = row_correction_plan or {"issues": []}

    def _proposed(category: str) -> int:
        return sum(
            1 for issue in row_plan.get("issues", [])
            if issue.get("category") == category and (issue.get("safe") or issue.get("requires_confirmation"))
        )

    whitespace = row_summary.get("whitespace", {})
    blank_rows = row_summary.get("blank_rows", {})
    dates = row_summary.get("dates", {})
    phones = row_summary.get("phones", {})
    addresses = row_summary.get("addresses", {})
    numeric = row_summary.get("numeric", {})
    identifiers = row_summary.get("identifiers", {})
    csv_structure = row_summary.get("csv_structure", {})
    punctuation = row_summary.get("punctuation", {})
    eans = row_summary.get("eans", {})
    federation_ids = row_summary.get("federation_ids", {})
    salesforce_record_check = row_summary.get("salesforce_record_check", {})

    return [
        {
            "title": "Whitespace Issues",
            "detected": whitespace.get("issues", 0),
            "rows_affected": whitespace.get("rows_affected", 0),
            "proposed_corrections": _proposed("whitespace"),
        },
        {
            "title": "Blank Rows",
            "detected": blank_rows.get("count", 0),
            "rows_affected": blank_rows.get("rows_affected", blank_rows.get("count", 0)),
            "proposed_corrections": _proposed("blank_rows"),
        },
        {
            "title": "Date Issues",
            "detected": dates.get("convertible", 0) + dates.get("ambiguous", 0) + dates.get("invalid", 0),
            "rows_affected": dates.get("rows_affected", 0),
            "proposed_corrections": _proposed("dates"),
        },
        {
            "title": "Picklist Issues",
            "detected": picklist_validation.get("invalid_count", 0),
            "rows_affected": len({
                issue.get("row") for issue in picklist_validation.get("issues", []) if issue.get("row") is not None
            }),
            "proposed_corrections": sum(
                1 for issue in picklist_validation.get("issues", [])
                if issue.get("proposed_replacement")
            ),
        },
        {
            "title": "Phone Issues",
            "detected": phones.get("formatting", 0),
            "rows_affected": phones.get("rows_affected", 0),
            "proposed_corrections": _proposed("phones"),
        },
        {
            "title": "Address Issues",
            "detected": addresses.get("whitespace", 0),
            "rows_affected": addresses.get("rows_affected", 0),
            "proposed_corrections": _proposed("addresses"),
        },
        {
            "title": "Numeric Issues",
            "detected": numeric.get("issues", 0),
            "rows_affected": numeric.get("rows_affected", 0),
            "proposed_corrections": _proposed("numeric"),
        },
        {
            "title": "Identifier Issues",
            "detected": (
                identifiers.get("leading_zeroes", 0)
                + identifiers.get("scientific_notation", 0)
                + identifiers.get("manual", 0)
            ),
            "rows_affected": identifiers.get("rows_affected", 0),
            "proposed_corrections": _proposed("identifiers"),
        },
        {
            "title": "CSV Structure",
            "detected": csv_structure.get("malformed_rows", 0),
            "rows_affected": csv_structure.get("rows_affected", 0),
            "proposed_corrections": _proposed("csv_structure"),
        },
        {
            "title": "Punctuation and Hidden Characters",
            "detected": punctuation.get("issues", 0),
            "rows_affected": punctuation.get("rows_affected", 0),
            "proposed_corrections": _proposed("punctuation"),
        },
        {
            "title": "EANs",
            "detected": eans.get("issues", 0),
            "rows_affected": eans.get("rows_affected", 0),
            "proposed_corrections": _proposed("eans"),
        },
        {
            "title": "User/Federation IDs",
            "detected": federation_ids.get("issues", 0),
            "rows_affected": federation_ids.get("rows_affected", 0),
            "proposed_corrections": _proposed("federation_ids"),
        },
        {
            "title": "Salesforce Record Check",
            "detected": salesforce_record_check.get("issues", 0),
            "rows_affected": salesforce_record_check.get("rows_affected", 0),
            "proposed_corrections": _proposed("salesforce_record_check"),
        },
    ]


def evaluate_preparation_readiness(
    *,
    header_review_complete: bool,
    preparation_result: dict[str, Any] | None,
    row_correction_plan: dict[str, Any] | None,
    workbench_plan: dict[str, Any] | None,
    validation_result: dict[str, Any] | None,
    preparation_task: str | None = None,
    upload_method: str | None = None,
    template: str | None = None,
    deployment_templates: list[str] | None = None,
    upload_prerequisites: dict[str, str] | None = None,
    preparation_warnings_acknowledged: dict[str, bool] | None = None,
    prerequisites_confirmed: bool = False,
) -> dict[str, Any]:
    """Return phase-aware readiness without blocking before approval opportunities."""
    if not header_review_complete:
        return {
            "status": READINESS_STATUS["NEEDS_HEADER_REVIEW"],
            "reasons": [],
            "warnings": [],
            "explanation": (
                "Upload readiness: NEEDS HEADER REVIEW\n\n"
                "Review and approve header changes before row-level validation begins."
            ),
        }

    pending_row_review = bool(
        row_correction_plan
        and row_correction_plan.get("has_fixable_issues")
        and not row_correction_plan.get("corrections_applied")
        and not row_correction_plan.get("corrections_declined")
    )
    pending_prep_review = bool(
        workbench_plan
        and workbench_plan.get("has_fixable_changes")
        and not workbench_plan.get("corrections_applied")
        and not workbench_plan.get("corrections_declined")
    )
    if pending_row_review or pending_prep_review:
        return {
            "status": READINESS_STATUS["NEEDS_USER_ACTION"],
            "reasons": [],
            "warnings": [],
            "explanation": (
                "Upload readiness: NEEDS USER ACTION\n\n"
                "Review proposed data corrections and approve the changes you want applied."
            ),
        }

    if preparation_result and preparation_result.get("corrected_df") is not None:
        manual_review = preparation_result.get("manual_review", [])
        date_unresolved = preparation_result.get("date_unresolved", [])
        picklist_validation = (validation_result or {}).get("picklist_validation", {})
        dependencies = (validation_result or {}).get("dependencies", {})
        blocking_dependencies = [
            item for item in dependencies.get("manual_review", [])
            if item.get("blocking")
        ]
        if (
            manual_review
            or date_unresolved
            or picklist_validation.get("has_blocking_issues")
            or blocking_dependencies
        ):
            reason_parts: list[str] = []
            if manual_review:
                reason_parts.append(f"{len(manual_review)} manual review item(s) remain")
            if date_unresolved:
                reason_parts.append(f"{len(date_unresolved)} unresolved date value(s) remain")
            if picklist_validation.get("has_blocking_issues"):
                reason_parts.append("Unresolved picklist validation issues remain")
            if blocking_dependencies:
                reason_parts.append(
                    f"{len(blocking_dependencies)} cross-template dependency issue(s) remain"
                )
            return {
                "status": READINESS_STATUS["NOT_READY"],
                "reasons": reason_parts[:1],
                "warnings": preparation_result.get("warnings", []),
                "explanation": (
                    "Upload readiness: NOT READY\n\n"
                    "Resolve blocking validation, dependency, and manual review items before download."
                ),
            }

        unresolved_prereqs: list[str] = []
        if template:
            from services.upload_order_service import (
                build_preparation_warnings,
                unacknowledged_preparation_warnings,
            )

            upload_order_plan = (validation_result or {}).get("upload_order_plan")
            warnings = build_preparation_warnings(
                template,
                deployment_templates=deployment_templates,
                prerequisite_status=upload_prerequisites,
                upload_order_plan=upload_order_plan,
            )
            pending = unacknowledged_preparation_warnings(
                warnings,
                prerequisite_status=upload_prerequisites or {},
                preparation_warnings_acknowledged=preparation_warnings_acknowledged or {},
            )
            unresolved_prereqs = [
                warning["required_prerequisite"] for warning in pending
            ]
            multi_file = deployment_templates and len(deployment_templates) > 1
            if multi_file and warnings and not prerequisites_confirmed:
                unresolved_prereqs = [
                    warning["required_prerequisite"] for warning in warnings
                ]

        if unresolved_prereqs:
            return {
                "status": READINESS_STATUS["NEEDS_USER_ACTION"],
                "reasons": [
                    "Confirm prerequisite upload status before continuing "
                    f"({', '.join(unresolved_prereqs)})."
                ],
                "warnings": preparation_result.get("warnings", []),
                "explanation": (
                    "Upload readiness: NEEDS USER ACTION\n\n"
                    "Review data preparation warnings and acknowledge required prerequisites."
                ),
            }

        warnings = list(preparation_result.get("warnings", []))
        if template:
            from services.upload_order_service import build_preparation_warnings

            prep_warnings = build_preparation_warnings(
                template,
                deployment_templates=deployment_templates,
                prerequisite_status=upload_prerequisites,
                upload_order_plan=(validation_result or {}).get("upload_order_plan"),
            )
            if prep_warnings:
                warnings.append(
                    "Upload dependency warnings were acknowledged; verify parent data is available "
                    "before loading into Salesforce."
                )
        if is_preparation_only(preparation_task):
            warnings.append(
                f"Prepared for {upload_method or 'the selected tool'}. "
                "Load-action-specific checks were not performed."
            )
        status = READINESS_STATUS["READY_WITH_WARNINGS"] if warnings else READINESS_STATUS["READY"]
        return {
            "status": status,
            "reasons": [],
            "warnings": warnings,
            "explanation": f"Upload readiness: {status}",
        }

    return {
        "status": READINESS_STATUS["NEEDS_USER_ACTION"],
        "reasons": [],
        "warnings": [],
        "explanation": (
            "Upload readiness: NEEDS USER ACTION\n\n"
            "Complete data preparation review to generate the corrected file."
        ),
    }
