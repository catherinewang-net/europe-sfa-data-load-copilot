"""EAN / GLN identifier validation with optional live Salesforce lookup."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from core.config import PROJECT_ROOT
from services.constants import (
    RECORD_CHECK_DUPLICATE_MATCH,
    RECORD_CHECK_FOUND,
    RECORD_CHECK_NOT_FOUND,
    RECORD_CHECK_UNAVAILABLE,
)
from validators.common import (
    DECIMAL_SUFFIX_RE,
    SCIENTIFIC_NOTATION_RE,
    build_issue,
    is_blank,
    normalize_text,
)

RULES_PATH = PROJECT_ROOT / "rules" / "ean_rules.json"
NON_DIGIT_RE = re.compile(r"\D")


def load_ean_rules() -> dict[str, Any]:
    if not RULES_PATH.exists():
        return {"fields": [], "live_lookup": {"enabled": False, "objects": []}}
    with open(RULES_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def resolve_ean_fields(
    columns: list[str],
    mapped_api_fields: dict[str, str],
) -> list[str]:
    rules = load_ean_rules().get("fields", [])
    resolved: list[str] = []
    for column in columns:
        api_name = mapped_api_fields.get(column, column)
        if _match_ean_rule(column, api_name, rules):
            resolved.append(column)
    return list(dict.fromkeys(resolved))


def validate_eans(
    df,
    ean_fields: list[str],
    *,
    live_lookup_result: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    rules = load_ean_rules().get("fields", [])
    live_lookup = live_lookup_result or {}

    for field in ean_fields:
        if field not in df.columns:
            continue
        rule = _match_ean_rule(field, field, rules)
        if not rule:
            continue

        allowed_lengths = [int(length) for length in rule.get("allowed_lengths", [])]
        optional_checksum = bool(rule.get("optional_checksum", False))
        value_rows: dict[str, list[int]] = defaultdict(list)
        lookup_unavailable = (
            live_lookup.get("query_errors")
            or (
                live_lookup.get("enabled") is False
                and live_lookup.get("attempted")
            )
        )
        if live_lookup and not live_lookup.get("available") and live_lookup.get("status_by_field"):
            lookup_unavailable = True

        for idx, raw_value in df[field].items():
            if is_blank(raw_value):
                continue
            text = normalize_text(raw_value)
            row_number = idx + 2
            value_rows[text].append(row_number)

            if SCIENTIFIC_NOTATION_RE.match(text):
                issues.append(_build_ean_issue(
                    field, row_number, text, text,
                    "EAN contains scientific notation and must remain text.",
                    blocking=True,
                    suffix="sci",
                ))
                continue

            if DECIMAL_SUFFIX_RE.match(text):
                corrected = text.split(".", 1)[0]
                issues.append(_build_ean_issue(
                    field, row_number, text, corrected,
                    "Remove accidental decimal suffix from EAN value.",
                    safe=True,
                    suffix="decimal",
                ))
                continue

            if rule.get("leading_zero_rule") and allowed_lengths and text.isdigit():
                padded = _propose_ean_leading_zero(text, allowed_lengths)
                if padded:
                    issues.append(_build_ean_issue(
                        field, row_number, text, padded,
                        rule.get(
                            "reason",
                            f"Restore leading zeroes to reach configured EAN length {len(padded)}.",
                        ),
                        safe=True,
                        confidence=0.9,
                        suffix="leading-zero",
                    ))
                    continue

            if NON_DIGIT_RE.search(text):
                issues.append(_build_ean_issue(
                    field, row_number, text, text,
                    "EAN contains non-digit characters.",
                    blocking=True,
                    suffix="non-digit",
                ))
                continue

            if allowed_lengths and len(text) not in allowed_lengths:
                issues.append(_build_ean_issue(
                    field, row_number, text, text,
                    f"EAN length {len(text)} is not one of the configured lengths "
                    f"({', '.join(map(str, allowed_lengths))}).",
                    blocking=True,
                    confidence=0.85,
                    suffix="length",
                ))
                continue

            if optional_checksum and not _checksum_valid(text):
                issues.append(_build_ean_issue(
                    field, row_number, text, text,
                    "EAN checksum validation failed.",
                    blocking=False,
                    requires_confirmation=True,
                    confidence=0.75,
                    suffix="checksum",
                ))

            lookup_status = _lookup_status_for_value(field, text, live_lookup)
            if lookup_status == RECORD_CHECK_FOUND:
                issues.append(_build_ean_issue(
                    field, row_number, text, text,
                    "EAN already exists in Salesforce.",
                    blocking=False,
                    requires_confirmation=True,
                    confidence=0.9,
                    suffix="exists",
                    category="salesforce_record_check",
                ))
            elif lookup_status == RECORD_CHECK_DUPLICATE_MATCH:
                issues.append(_build_ean_issue(
                    field, row_number, text, text,
                    "Multiple Salesforce records matched this EAN.",
                    blocking=True,
                    suffix="multiple",
                    category="salesforce_record_check",
                ))
            elif lookup_status == RECORD_CHECK_UNAVAILABLE or (
                lookup_unavailable and lookup_status is None
            ):
                issues.append(_build_ean_issue(
                    field, row_number, text, text,
                    "EAN format was checked, but existence in Salesforce was not verified.",
                    blocking=False,
                    requires_confirmation=False,
                    confidence=0.5,
                    suffix="unavailable",
                    category="salesforce_record_check",
                ))

        for value, rows in value_rows.items():
            if len(rows) <= 1:
                continue
            issues.append(_build_ean_issue(
                field, rows[0], value, value,
                f"Duplicate EAN `{value}` appears on rows {', '.join(map(str, rows))}.",
                blocking=True,
                suffix=f"dup:{value}",
            ))

    return issues


def run_ean_live_lookup(
    df,
    ean_fields: list[str],
    mapped_api_fields: dict[str, str],
) -> dict[str, Any]:
    """Batch EAN existence checks against Salesforce when configured."""
    rules = load_ean_rules()
    live_config = rules.get("live_lookup", {})
    if not live_config.get("enabled"):
        return {"available": False, "status_by_field": {}, "message": RECORD_CHECK_UNAVAILABLE, "attempted": False}

    try:
        from clients.salesforce_client import get_salesforce_client
        from services.salesforce_record_lookup_service import lookup_records_by_field
    except ImportError:
        return {
            "available": False,
            "status_by_field": {},
            "message": RECORD_CHECK_UNAVAILABLE,
            "attempted": True,
        }

    client = get_salesforce_client()
    if not client.is_configured():
        return {
            "available": False,
            "status_by_field": {},
            "message": RECORD_CHECK_UNAVAILABLE,
            "attempted": True,
        }

    status_by_field: dict[str, dict[str, str]] = {}
    query_errors: list[str] = []

    for field in ean_fields:
        if field not in df.columns:
            continue
        lookup_target = _resolve_live_lookup_target(field, mapped_api_fields.get(field, field), live_config)
        if not lookup_target:
            continue

        values = [
            normalize_text(value)
            for value in df[field].tolist()
            if not is_blank(value)
        ]
        result = lookup_records_by_field(
            client,
            lookup_target["object_api_name"],
            lookup_target["identifier_field"],
            values,
        )
        query_errors.extend(result.get("query_errors", []))
        field_status: dict[str, str] = {}
        for value in set(values):
            matches = result.get("matches_by_value", {}).get(value.casefold(), [])
            if len(matches) > 1:
                field_status[value] = RECORD_CHECK_DUPLICATE_MATCH
            elif len(matches) == 1:
                field_status[value] = RECORD_CHECK_FOUND
            else:
                field_status[value] = RECORD_CHECK_NOT_FOUND
        status_by_field[field] = field_status

    available = bool(status_by_field) and not query_errors
    message = (
        "Live Salesforce EAN lookup completed."
        if available
        else RECORD_CHECK_UNAVAILABLE
    )
    return {
        "available": available,
        "status_by_field": status_by_field,
        "query_errors": query_errors,
        "message": message,
        "attempted": True,
    }


def _lookup_status_for_value(
    field: str,
    value: str,
    live_lookup: dict[str, Any],
) -> str | None:
    if not live_lookup:
        return None
    if live_lookup.get("query_errors"):
        return RECORD_CHECK_UNAVAILABLE
    if live_lookup.get("attempted") and not live_lookup.get("available"):
        return RECORD_CHECK_UNAVAILABLE
    if not live_lookup.get("status_by_field"):
        return None
    field_status = live_lookup["status_by_field"].get(field, {})
    return field_status.get(value)


def _resolve_live_lookup_target(
    column: str,
    api_name: str,
    live_config: dict[str, Any],
) -> dict[str, str] | None:
    for entry in live_config.get("objects", []):
        patterns = [pattern.lower() for pattern in entry.get("match_patterns", [])]
        api_names = [name.lower() for name in entry.get("api_names", [])]
        normalized = column.lstrip("*").lower()
        if any(pattern in normalized for pattern in patterns):
            return {
                "object_api_name": entry["object_api_name"],
                "identifier_field": entry["identifier_field"],
            }
        if api_name.lower() in api_names:
            return {
                "object_api_name": entry["object_api_name"],
                "identifier_field": entry["identifier_field"],
            }
    return None


def _propose_ean_leading_zero(text: str, allowed_lengths: list[int]) -> str | None:
    """Suggest zero-padding only when one configured length is exactly one digit longer."""
    for target_length in sorted(allowed_lengths):
        if len(text) == target_length - 1:
            return text.zfill(target_length)
    return None


def _match_ean_rule(column: str, api_name: str, rules: list[dict[str, Any]]) -> dict[str, Any] | None:
    normalized = column.lstrip("*").lower()
    api_lower = api_name.lower()
    for rule in rules:
        patterns = [pattern.lower() for pattern in rule.get("match_patterns", [])]
        api_names = [name.lower() for name in rule.get("api_names", [])]
        if any(pattern in normalized for pattern in patterns):
            return rule
        if api_lower in api_names:
            return rule
    return None


def _checksum_valid(value: str) -> bool:
    if not value.isdigit():
        return False
    if len(value) not in {8, 13}:
        return True
    digits = [int(char) for char in value[:-1]]
    if len(value) == 13:
        digits = digits[-12:]
        value = value[-13:]
    total = 0
    for index, digit in enumerate(reversed(digits)):
        multiplier = 3 if index % 2 == 0 else 1
        total += digit * multiplier
    check = (10 - (total % 10)) % 10
    return check == int(value[-1])


def _build_ean_issue(
    field: str,
    row_number: int,
    original: str,
    proposed: str,
    reason: str,
    *,
    safe: bool = False,
    blocking: bool = False,
    requires_confirmation: bool = False,
    confidence: float = 1.0,
    suffix: str,
    category: str = "eans",
) -> dict[str, Any]:
    return build_issue(
        issue_id=f"{category}:{suffix}:{field}:{row_number}",
        category=category,
        field=field,
        row=row_number,
        original_value=original,
        proposed_value=proposed,
        reason=reason,
        safe=safe,
        blocking=blocking,
        requires_confirmation=requires_confirmation,
        confidence=confidence,
    )
