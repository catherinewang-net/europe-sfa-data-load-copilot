"""Dependency checker — flags issues for manual review, never auto-corrects."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from validators.routing_validator import validate_routing_rules

_RULES_PATH = Path(__file__).resolve().parent.parent / "rules" / "dependencies.json"


def _load_dependency_rules() -> list[dict[str, Any]]:
    if not _RULES_PATH.exists():
        return []
    with _RULES_PATH.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload.get("rules", [])


def check_dependencies(
    df: pd.DataFrame,
    template: str,
    upload_method: str,
    reference_catalogs: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    """
    Check cross-record and cross-template dependencies.

    Dependencies are flagged for manual review only — never automatically corrected.
    Optional reference_catalogs maps parent template names to known valid reference values.
    """
    issues: list[dict[str, Any]] = []
    manual_review: list[dict[str, Any]] = []
    reference_catalogs = reference_catalogs or {}

    for rule in _load_dependency_rules():
        if rule.get("template") != template:
            continue
        rule_type = rule.get("type")
        if rule_type == "cross_template_reference":
            _check_cross_template_reference(df, rule, reference_catalogs, issues, manual_review)
        elif rule_type == "load_order":
            _check_load_order(rule, issues)
        elif rule_type == "hierarchy_dependency":
            _check_hierarchy_dependency(df, rule, issues, manual_review)

    routing_result = validate_routing_rules(df, template)
    issues.extend(routing_result.get("issues", []))
    manual_review.extend(routing_result.get("manual_review", []))

    note = None
    if not issues and not manual_review:
        note = "No dependency issues detected for this template."

    return {
        "issues": issues,
        "manual_review": manual_review,
        "checked": True,
        "template": template,
        "upload_method": upload_method,
        "blocking_count": sum(1 for item in manual_review if item.get("blocking")),
        "note": note,
    }


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, float) and pd.isna(value)) or not str(value).strip()


def _check_cross_template_reference(
    df: pd.DataFrame,
    rule: dict[str, Any],
    reference_catalogs: dict[str, set[str]],
    issues: list[dict[str, Any]],
    manual_review: list[dict[str, Any]],
) -> None:
    field = rule.get("field")
    if not field or field not in df.columns:
        return

    parent_template = rule.get("parent_template", "")
    parent_field = rule.get("parent_field", "")
    parent_object = rule.get("parent_object", parent_template)
    upload_order = rule.get("upload_order")
    blocking = bool(rule.get("blocking", True))
    catalog = reference_catalogs.get(parent_template)

    for idx, raw_value in df[field].items():
        if _is_blank(raw_value):
            continue
        value = str(raw_value).strip()
        if catalog is not None and value not in catalog:
            reason = (
                f"Referenced value '{value}' in '{field}' was not found in the "
                f"{parent_template} load ({parent_field}). Load {parent_template} first."
            )
        else:
            reason = (
                f"Cross-template reference '{value}' in '{field}' requires "
                f"{parent_template} ({parent_field}) to be loaded first."
            )

        item = {
            "validator": "dependency",
            "severity": "error" if blocking else "warning",
            "row": idx + 2,
            "field": field,
            "referenced_value": value,
            "parent_object": parent_object,
            "parent_template": parent_template,
            "upload_order": upload_order,
            "reason": reason,
            "message": reason,
            "blocking": blocking,
            "category": rule.get("id", "cross_template_reference"),
        }
        issues.append(item)
        if blocking:
            manual_review.append(item)


def _check_load_order(rule: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    message = rule.get("message")
    if not message:
        return
    issues.append({
        "validator": "dependency",
        "severity": "warning",
        "field": None,
        "message": message,
        "blocking": bool(rule.get("blocking", False)),
        "category": rule.get("id", "load_order"),
        "upload_order": 1,
    })


def _check_hierarchy_dependency(
    df: pd.DataFrame,
    rule: dict[str, Any],
    issues: list[dict[str, Any]],
    manual_review: list[dict[str, Any]],
) -> None:
    level_field = rule.get("field")
    reference_field = rule.get("reference_field")
    parent_values = {str(value).strip().lower() for value in rule.get("parent_brand_values", [])}
    if not level_field or level_field not in df.columns:
        return

    for idx, row in df.iterrows():
        level = str(row.get(level_field, "")).strip().lower()
        if "competitor" not in level:
            continue
        reference = str(row.get(reference_field, "")).strip() if reference_field in df.columns else ""
        reason = rule.get(
            "message",
            "Competitor product hierarchy rows require parent Pepsi SKUs to be loaded first.",
        )
        if reference:
            reason = f"{reason} Referenced value: {reference}."
        item = {
            "validator": "dependency",
            "severity": "error",
            "row": idx + 2,
            "field": level_field,
            "referenced_value": reference,
            "parent_object": "Product2",
            "parent_template": rule.get("depends_on_template", "Products"),
            "upload_order": 1,
            "reason": reason,
            "message": reason,
            "blocking": bool(rule.get("blocking", True)),
            "category": rule.get("id", "hierarchy_dependency"),
        }
        issues.append(item)
        manual_review.append(item)
