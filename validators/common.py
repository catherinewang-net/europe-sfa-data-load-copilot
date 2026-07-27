"""Shared helpers for row-level validators."""

from __future__ import annotations

import csv
import io
import re
from typing import Any


def is_blank(value: Any) -> bool:
    try:
        import pandas as pd
        if pd.isna(value):
            return True
    except ImportError:
        pass
    return value is None or (isinstance(value, str) and not value.strip())


def normalize_text(value: Any) -> str:
    if is_blank(value):
        return ""
    return str(value).strip()


NBSP = "\u00a0"


def is_whitespace_only(value: Any) -> bool:
    if value is None or (isinstance(value, float) and str(value) == "nan"):
        return False
    if not isinstance(value, str):
        value = str(value)
    return bool(value) and not value.strip()


def clean_text_whitespace(value: Any) -> str:
    """Trim, normalize NBSP/tabs, collapse spaces, and flatten line breaks."""
    if value is None or (isinstance(value, float) and str(value) == "nan"):
        return ""
    text = str(value)
    text = text.replace(NBSP, " ").replace("\t", " ")
    text = re.sub(r"[\r\n]+", " ", text)
    text = text.strip()
    text = re.sub(r" {2,}", " ", text)
    return text


def text_needs_whitespace_cleanup(value: Any) -> bool:
    if not isinstance(value, str):
        if is_blank(value):
            return False
        value = str(value)
    if is_whitespace_only(value):
        return True
    return clean_text_whitespace(value) != value


def build_issue(
    *,
    issue_id: str,
    category: str,
    field: str | None,
    row: int | None,
    original_value: str,
    proposed_value: str,
    reason: str,
    safe: bool,
    requires_confirmation: bool = False,
    confidence: float = 1.0,
    blocking: bool = False,
) -> dict[str, Any]:
    return {
        "issue_id": issue_id,
        "category": category,
        "field": field,
        "row": row,
        "original_value": original_value,
        "proposed_value": proposed_value,
        "reason": reason,
        "safe": safe,
        "requires_confirmation": requires_confirmation or (not safe and bool(proposed_value)),
        "confidence": confidence,
        "blocking": blocking,
    }


SCIENTIFIC_NOTATION_RE = re.compile(r"^\d+(?:\.\d+)?[eE][+-]?\d+$")
DECIMAL_SUFFIX_RE = re.compile(r"^\d+\.0+$")
EXCEL_SERIAL_RE = re.compile(r"^\d{4,6}$")

ADDRESS_FIELD_MARKERS = (
    "street",
    "city",
    "country",
    "postal",
    "post code",
    "zip",
    "shipping",
    "billing",
)

PHONE_FIELD_MARKERS = ("phone", "fax", "mobile")
IDENTIFIER_FIELD_MARKERS = (
    "id",
    "external",
    "gln",
    "ean",
    "sku",
    "code",
    "routing",
)


def field_matches_markers(field_name: str, markers: tuple[str, ...]) -> bool:
    normalized = field_name.lstrip("*").lower()
    return any(marker in normalized for marker in markers)


def export_csv_with_quoting(df) -> str:
    """Export a dataframe to CSV with standard quoting for embedded commas."""
    buffer = io.StringIO()
    df.to_csv(buffer, index=False, quoting=csv.QUOTE_MINIMAL)
    return buffer.getvalue()
