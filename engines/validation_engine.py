"""Validation engine — orchestrates metadata-backed validation checks."""

from __future__ import annotations

from typing import Any

import pandas as pd

from engines.dependency_checker import check_dependencies
from engines.template_comparison import compare_to_reference
from services.download_readiness_service import evaluate_download_readiness
from services.preparation_task_service import is_preparation_only
from services.field_mapping_service import build_mapping_report
from services.template_service import get_metadata_source_info, get_relevant_skipped_files, resolve_template
from validators.load_action_validator import validate_load_action
from validators.picklist_validator import validate_picklists
from validators.record_existence_validator import validate_record_existence


def run_validation(
    df: pd.DataFrame,
    raw_headers: list[str],
    upload_method: str,
    template: str,
    mapping_rows: list[dict[str, Any]] | None = None,
    load_operation: str | None = None,
    type_confirmed: bool = False,
    preparation_result: dict[str, Any] | None = None,
    correction_plan: dict[str, Any] | None = None,
    use_mapped_columns: bool = False,
    preparation_task: str | None = None,
) -> dict[str, Any]:
    """Run configured validation checks for the current context."""
    template_context = resolve_template(template)
    mapping_rows = mapping_rows or []

    validate_df = df
    validate_headers = raw_headers
    if preparation_result and preparation_result.get("corrected_df") is not None:
        validate_df = preparation_result["corrected_df"]
        validate_headers = list(validate_df.columns)

    results: dict[str, Any] = {
        "upload_method": upload_method,
        "template": template,
        "preparation_task": preparation_task,
        "preparation_only": is_preparation_only(preparation_task),
        "row_count": len(validate_df),
        "issues": [],
        "manual_review": [],
        "metadata_source": get_metadata_source_info(template),
        "mapping_rows": mapping_rows,
        "mapping_report": build_mapping_report(mapping_rows),
    }

    try:
        if upload_method == "Data Import Tool":
            comparison = compare_to_reference(
                validate_headers,
                upload_method,
                template,
                load_operation,
            )
            results["template_comparison"] = comparison

            comp = comparison["comparison"]
            if not comp["template_match"]:
                covered_missing = _covered_missing_columns(comp, correction_plan)
                for col in comp["missing_columns"]:
                    if col in covered_missing and not preparation_result:
                        results["issues"].append({
                            "validator": "template",
                            "severity": "info",
                            "field": col,
                            "message": f"Missing header can be corrected: {col}",
                        })
                        continue
                    results["issues"].append({
                        "validator": "template",
                        "severity": "error",
                        "field": col,
                        "message": f"Missing required header: {col}",
                    })
                for col in comp["extra_columns"]:
                    results["issues"].append({
                        "validator": "template",
                        "severity": "warning",
                        "field": col,
                        "message": f"Unexpected header: {col}",
                    })
                for col in comp["duplicate_columns"]:
                    results["issues"].append({
                        "validator": "template",
                        "severity": "error",
                        "field": col,
                        "message": f"Duplicate header: {col}",
                    })
                for diff in comp.get("order_differences", []):
                    if correction_plan and not preparation_result:
                        results["issues"].append({
                            "validator": "template",
                            "severity": "info",
                            "field": diff.get("header"),
                            "message": (
                                f"Header order can be corrected for `{diff.get('header')}`"
                            ),
                        })
        else:
            results["template_comparison"] = None
    except FileNotFoundError:
        results["template_comparison"] = None
        results["issues"].append({
            "validator": "template",
            "severity": "error",
            "field": None,
            "message": "Reference template not found.",
        })

    dependency_result = check_dependencies(validate_df, template, upload_method)
    results["dependencies"] = dependency_result
    results["manual_review"].extend(dependency_result.get("manual_review", []))
    results["issues"].extend(dependency_result.get("issues", []))

    if template_context and template_context.salesforce_object and mapping_rows:
        picklist_validation = validate_picklists(
            validate_df,
            mapping_rows,
            template_context,
            use_mapped_columns=use_mapped_columns,
        )
        results["picklist_validation"] = picklist_validation
        results["manual_review"].extend(
            issue for issue in picklist_validation.get("issues", [])
            if issue.get("status") in {"Invalid Picklist Value", "Blank Required Value", "Metadata Unavailable"}
        )

        lookup_validation = {
            "evaluated": False,
            "field_summaries": [],
            "row_results": [],
            "summary": {},
            "issues": [],
            "manual_review": [],
            "has_blocking_issues": False,
            "blocks_download": False,
            "metadata_only": True,
            "message": "Live lookup validation is disabled for this release.",
        }
        results["lookup_validation"] = lookup_validation
    else:
        results["picklist_validation"] = {
            "field_summaries": [],
            "issues": [],
            "valid_count": 0,
            "invalid_count": 0,
            "blocking_issue_count": 0,
            "has_blocking_issues": False,
        }
        results["lookup_validation"] = {
            "evaluated": False,
            "field_summaries": [],
            "row_results": [],
            "summary": {},
            "issues": [],
            "manual_review": [],
            "has_blocking_issues": False,
            "blocks_download": False,
            "metadata_only": True,
        }

    if template_context:
        load_action_validation = validate_load_action(
            validate_df,
            mapping_rows,
            load_operation,
            template_context,
        )
        results["load_action_validation"] = load_action_validation
        if load_action_validation.get("evaluated", True):
            results["manual_review"].extend(load_action_validation.get("manual_review", []))
            results["issues"].extend(load_action_validation.get("issues", []))

        record_existence_validation = validate_record_existence(
            validate_df,
            mapping_rows,
            load_operation,
            template_context,
            use_mapped_columns=use_mapped_columns,
            skip_live_check=False,
        )
        results["record_existence_validation"] = record_existence_validation
        if record_existence_validation.get("evaluated"):
            results["manual_review"].extend(record_existence_validation.get("manual_review", []))
            results["issues"].extend(record_existence_validation.get("issues", []))
    else:
        results["load_action_validation"] = None
        results["record_existence_validation"] = None

    mapped_api_fields = {
        row.get("confirmed_api_field")
        for row in mapping_rows
        if row.get("confirmed_api_field")
    }
    if template_context:
        for skipped in get_relevant_skipped_files(
            template_context,
            template_context.salesforce_object,
            mapped_api_fields,
        ):
            results["manual_review"].append({
                "row": None,
                "field": None,
                "value": skipped,
                "reason": "Skipped Salesforce metadata XML file relevant to this template",
            })

    can_download, download_message, download_details = evaluate_download_readiness(
        template_context,
        mapping_rows,
        type_confirmed,
        load_operation,
        results.get("picklist_validation"),
        results.get("load_action_validation"),
        preparation_result,
        preparation_only=is_preparation_only(preparation_task),
        record_existence_validation=results.get("record_existence_validation"),
        upload_method=upload_method,
        validation_result=results,
    )
    results["download_readiness"] = {
        "allowed": can_download,
        "message": download_message,
        **download_details,
    }

    blocking_issues = [
        issue for issue in results["issues"]
        if issue.get("severity") == "error" or issue.get("blocking")
    ]
    lookup_validation = results.get("lookup_validation", {})
    results["has_blocking_issues"] = bool(blocking_issues) or bool(
        results.get("picklist_validation", {}).get("has_blocking_issues")
    )

    return results


def _covered_missing_columns(
    comparison: dict[str, Any],
    correction_plan: dict[str, Any] | None,
) -> set[str]:
    if not correction_plan:
        return set()

    covered: set[str] = set()
    for rename in correction_plan.get("proposed_renames", []):
        target = rename.get("target_column")
        if target:
            covered.add(target)
    for change in correction_plan.get("changes", []):
        if change["category"] in {
            "rename",
            "add_generated_value",
            "add_empty_optional_column",
        }:
            target = change.get("target_column")
            if target:
                covered.add(target)
    return covered
