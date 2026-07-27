"""Federation ID / User ID validation with configurable leading-zero rules."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from core.config import PROJECT_ROOT
from validators.common import (
    DECIMAL_SUFFIX_RE,
    SCIENTIFIC_NOTATION_RE,
    build_issue,
    is_blank,
    normalize_text,
)

RULES_PATH = PROJECT_ROOT / "rules" / "federation_id_rules.json"


def load_federation_id_rules() -> dict[str, Any]:
    if not RULES_PATH.exists():
        return {"fields": []}
    with open(RULES_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def resolve_federation_id_fields(
    columns: list[str],
    mapped_api_fields: dict[str, str],
) -> list[str]:
    rules = load_federation_id_rules().get("fields", [])
    resolved: list[str] = []
    for column in columns:
        api_name = mapped_api_fields.get(column, column)
        if _match_rule(column, api_name, rules):
            resolved.append(column)
    return list(dict.fromkeys(resolved))


def validate_federation_ids(
    df,
    federation_fields: list[str],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    rules = load_federation_id_rules().get("fields", [])

    for field in federation_fields:
        if field not in df.columns:
            continue
        rule = _match_rule(field, field, rules)
        if not rule:
            continue

        pattern = rule.get("missing_leading_zero_pattern")
        expected_length = int(rule.get("expected_length", 0) or 0)
        compiled = re.compile(pattern) if pattern else None

        for idx, raw_value in df[field].items():
            if is_blank(raw_value):
                continue
            text = normalize_text(raw_value)
            row_number = idx + 2

            if SCIENTIFIC_NOTATION_RE.match(text):
                issues.append(_build_federation_issue(
                    field, row_number, text, text,
                    "Federation ID contains scientific notation and must remain text.",
                    blocking=True,
                    confidence=1.0,
                    suffix="sci",
                ))
                continue

            if DECIMAL_SUFFIX_RE.match(text):
                corrected = text.split(".", 1)[0]
                issues.append(_build_federation_issue(
                    field, row_number, text, corrected,
                    "Remove accidental decimal suffix from Federation ID.",
                    safe=True,
                    confidence=0.95,
                    suffix="decimal",
                ))
                continue

            if not text.isdigit():
                issues.append(_build_federation_issue(
                    field, row_number, text, text,
                    "Federation ID contains invalid characters.",
                    blocking=True,
                    confidence=1.0,
                    suffix="invalid",
                ))
                continue

            if expected_length and len(text) < expected_length and compiled and compiled.match(text):
                corrected = text.zfill(expected_length)
                issues.append(_build_federation_issue(
                    field, row_number, text, corrected,
                    rule.get(
                        "reason",
                        "Federation ID appears too short and starts with 9. "
                        "Confirm whether a leading zero is missing.",
                    ),
                    blocking=False,
                    confidence=0.7,
                    suffix="leading-zero",
                ))
            elif expected_length and len(text) > expected_length:
                issues.append(_build_federation_issue(
                    field, row_number, text, text,
                    f"Federation ID exceeds expected length ({expected_length}).",
                    blocking=True,
                    confidence=0.8,
                    suffix="too-long",
                ))

    return issues


def _match_rule(column: str, api_name: str, rules: list[dict[str, Any]]) -> dict[str, Any] | None:
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


def _build_federation_issue(
    field: str,
    row_number: int,
    original: str,
    proposed: str,
    reason: str,
    *,
    safe: bool = False,
    blocking: bool = False,
    confidence: float = 1.0,
    suffix: str,
) -> dict[str, Any]:
    return build_issue(
        issue_id=f"federation_id:{suffix}:{field}:{row_number}",
        category="federation_ids",
        field=field,
        row=row_number,
        original_value=original,
        proposed_value=proposed,
        reason=reason,
        safe=safe,
        blocking=blocking,
        requires_confirmation=not safe,
        confidence=confidence,
    )
