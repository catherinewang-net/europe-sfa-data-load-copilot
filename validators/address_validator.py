"""Address field validation."""

from __future__ import annotations

import re
from typing import Any

from validators.common import (
    ADDRESS_FIELD_MARKERS,
    DECIMAL_SUFFIX_RE,
    build_issue,
    field_matches_markers,
    is_blank,
)

STREET_MARKERS = ("street", "shippingstreet", "billingstreet", "mailingstreet")
CITY_MARKERS = ("city", "shippingcity", "billingcity", "mailingcity")
STATE_MARKERS = ("state", "region", "province", "county", "shippingstate", "billingstate", "mailingstate")
POSTAL_MARKERS = ("postal", "post code", "zip", "postalcode")
COUNTRY_MARKERS = ("country", "shippingcountry", "billingcountry", "mailingcountry")

POSTAL_IN_TEXT_RE = re.compile(r"\b\d{4,6}(?:-\d{4})?\b")
STATE_ABBREV_RE = re.compile(r"\b[A-Z]{2}\b")
CITY_IN_STREET_RE = re.compile(
    r"(?:,\s*|\s+)(?:[A-Za-z .'-]+,\s*)?(?:[A-Z]{2}\s*)?\d{4,6}(?:-\d{4})?\b"
)


def validate_addresses(
    df,
    address_fields: list[str],
    *,
    structured_fields: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    structured = structured_fields or resolve_structured_address_fields(list(df.columns))

    street_fields = structured.get("street", [])
    city_fields = structured.get("city", [])
    state_fields = structured.get("state", [])
    postal_fields = structured.get("postal", [])
    country_fields = structured.get("country", [])
    has_separate_components = bool(city_fields or state_fields or postal_fields or country_fields)

    for field in address_fields:
        if field not in df.columns:
            continue
        for idx, raw_value in df[field].items():
            if is_blank(raw_value):
                continue
            text = str(raw_value)
            row_number = idx + 2

            if "\n" in text or "\r" in text:
                corrected = re.sub(r"[\r\n]+", " ", text).strip()
                corrected = re.sub(r"\s{2,}", " ", corrected)
                issues.append(_address_issue(
                    "break", field, row_number, text, corrected,
                    "Replace embedded line breaks in address text with a single space.",
                    safe=True,
                    confidence=0.95,
                    address_confidence="Needs Review",
                ))
                continue

            trimmed = text.strip()
            if trimmed != text:
                issues.append(_address_issue(
                    "trim", field, row_number, text, trimmed,
                    "Trim leading/trailing whitespace from address field.",
                    safe=True,
                    confidence=1.0,
                    address_confidence="Valid",
                ))
                text = trimmed

            normalized_spaces = re.sub(r"\s{2,}", " ", text)
            if normalized_spaces != text:
                issues.append(_address_issue(
                    "spaces", field, row_number, text, normalized_spaces,
                    "Normalize repeated spaces in address field.",
                    safe=True,
                    confidence=0.95,
                    address_confidence="Valid",
                ))
                text = normalized_spaces

            if field in postal_fields and DECIMAL_SUFFIX_RE.match(text):
                corrected = text.split(".", 1)[0]
                issues.append(_address_issue(
                    "postal", field, row_number, text, corrected,
                    "Preserve postal code as text and remove accidental decimal suffix.",
                    safe=True,
                    confidence=0.95,
                    address_confidence="Valid",
                ))

            if field in city_fields and re.search(r"\d", text):
                issues.append(_address_issue(
                    "city-digits", field, row_number, text, text,
                    "City contains unexpected digits.",
                    blocking=False,
                    requires_confirmation=True,
                    confidence=0.7,
                    address_confidence="Needs Review",
                ))

            if field in street_fields and has_separate_components and _street_contains_other_components(text):
                issues.append(_address_issue(
                    "street-mix", field, row_number, text, text,
                    "Street appears to contain city, state, or postal-code information. "
                    "Review the address fields.",
                    blocking=True,
                    confidence=0.9,
                    address_confidence="Needs Review",
                ))

            if field in street_fields and has_separate_components and _street_components_blank(row_number - 2, df, structured):
                issues.append(_address_issue(
                    "street-incomplete", field, row_number, text, text,
                    "Street is populated but city, state, or postal-code fields are blank.",
                    blocking=False,
                    requires_confirmation=True,
                    confidence=0.75,
                    address_confidence="Incomplete",
                ))

    return issues


def resolve_address_fields(columns: list[str]) -> list[str]:
    return [column for column in columns if field_matches_markers(column, ADDRESS_FIELD_MARKERS)]


def resolve_structured_address_fields(columns: list[str]) -> dict[str, list[str]]:
    return {
        "street": [column for column in columns if field_matches_markers(column, STREET_MARKERS)],
        "city": [column for column in columns if field_matches_markers(column, CITY_MARKERS)],
        "state": [column for column in columns if field_matches_markers(column, STATE_MARKERS)],
        "postal": [column for column in columns if field_matches_markers(column, POSTAL_MARKERS)],
        "country": [column for column in columns if field_matches_markers(column, COUNTRY_MARKERS)],
    }


def _street_contains_other_components(text: str) -> bool:
    if POSTAL_IN_TEXT_RE.search(text):
        return True
    if CITY_IN_STREET_RE.search(text):
        return True
    if text.count(",") >= 2:
        return True
    if STATE_ABBREV_RE.search(text) and POSTAL_IN_TEXT_RE.search(text):
        return True
    return False


def _street_components_blank(row_index: int, df, structured: dict[str, list[str]]) -> bool:
    other_fields = (
        structured.get("city", [])
        + structured.get("state", [])
        + structured.get("postal", [])
    )
    if not other_fields:
        return False
    return all(is_blank(df.at[row_index, field]) for field in other_fields if field in df.columns)


def _address_issue(
    suffix: str,
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
    address_confidence: str = "Valid",
) -> dict[str, Any]:
    issue = build_issue(
        issue_id=f"address:{suffix}:{field}:{row_number}",
        category="addresses",
        field=field,
        row=row_number,
        original_value=original[:120],
        proposed_value=proposed[:120],
        reason=reason,
        safe=safe,
        blocking=blocking,
        requires_confirmation=requires_confirmation,
        confidence=confidence,
    )
    issue["address_confidence"] = address_confidence
    return issue
