"""Excel and copy/paste punctuation validation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from core.config import PROJECT_ROOT
from validators.common import (
    NBSP,
    build_issue,
    field_matches_markers,
    is_blank,
)

PUNCTUATION_RULES_PATH = PROJECT_ROOT / "rules" / "punctuation_rules.json"

SMART_QUOTE_CHARS = {
    "\u201c": '"',
    "\u201d": '"',
    "\u2018": "'",
    "\u2019": "'",
    "\u00ab": '"',
    "\u00bb": '"',
}
DASH_CHARS = {
    "\u2013": "-",
    "\u2014": "-",
    "\u2212": "-",
}
CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def load_punctuation_rules() -> dict[str, Any]:
    if PUNCTUATION_RULES_PATH.exists():
        with open(PUNCTUATION_RULES_PATH, encoding="utf-8") as handle:
            return json.load(handle)
    return {"skip_patterns": ["password", "iban"]}


def _normalize_punctuation(text: str) -> str:
    corrected = text.replace(NBSP, " ").replace("\t", " ")
    for source, target in {**SMART_QUOTE_CHARS, **DASH_CHARS}.items():
        corrected = corrected.replace(source, target)
    corrected = CONTROL_CHAR_RE.sub("", corrected)
    return corrected


def _detect_punctuation_issues(text: str) -> list[str]:
    findings: list[str] = []
    if NBSP in text or "\t" in text:
        findings.append("non-breaking space or tab")
    if any(char in text for char in SMART_QUOTE_CHARS):
        findings.append("smart quote")
    if any(char in text for char in DASH_CHARS):
        findings.append("en/em dash")
    if CONTROL_CHAR_RE.search(text):
        findings.append("control character")
    return findings


def validate_text_sanitization(
    df,
    text_fields: list[str],
) -> list[dict[str, Any]]:
    """Detect Excel/paste punctuation issues and propose normalization with approval."""
    issues: list[dict[str, Any]] = []
    skip_patterns = [
        pattern.lower()
        for pattern in load_punctuation_rules().get("skip_patterns", [])
    ]

    for field in text_fields:
        if field not in df.columns:
            continue
        normalized_field = field.lstrip("*").lower()
        if any(pattern in normalized_field for pattern in skip_patterns):
            continue

        for idx, raw_value in df[field].items():
            if is_blank(raw_value):
                continue
            text = str(raw_value)
            findings = _detect_punctuation_issues(text)
            if not findings:
                continue

            row_number = idx + 2
            corrected = _normalize_punctuation(text)
            issues.append(build_issue(
                issue_id=f"punctuation:cleanup:{field}:{row_number}",
                category="punctuation",
                field=field,
                row=row_number,
                original_value=text[:120],
                proposed_value=corrected[:120],
                reason=(
                    f"Detected {', '.join(findings)}. "
                    "Review before normalizing punctuation in business values."
                ),
                safe=False,
                requires_confirmation=True,
                confidence=0.85,
            ))

    return issues


def resolve_punctuation_fields(
    columns: list[str],
    mapped_api_fields: dict[str, str],
    *,
    excluded_fields: set[str] | None = None,
) -> list[str]:
    excluded = excluded_fields or set()
    resolved: list[str] = []
    for column in columns:
        if column in excluded:
            continue
        api_name = mapped_api_fields.get(column, column)
        normalized = f"{column} {api_name}".lower()
        if field_matches_markers(column, ("date",)) or "date" in normalized:
            continue
        resolved.append(column)
    return list(dict.fromkeys(resolved))
