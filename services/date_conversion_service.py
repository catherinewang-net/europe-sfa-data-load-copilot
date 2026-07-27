"""Strict date detection and conversion — no silent day/month guessing."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from validators.common import is_blank, normalize_text

# Internal analysis statuses (mapped to user-facing categories below)
STATUS_VALID = "already_correct"
STATUS_CONVERTED = "convertible"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_INVALID_CALENDAR = "invalid_calendar"
STATUS_UNSUPPORTED_TEXT = "unsupported_text"
STATUS_EXCEL_SERIAL = "excel_serial"
STATUS_BLANK = "blank"
STATUS_INVALID = "invalid"

DISPLAY_STATUS_VALID = "Valid"
DISPLAY_STATUS_CONVERTED = "Converted"
DISPLAY_STATUS_AMBIGUOUS = "Ambiguous"
DISPLAY_STATUS_INVALID_CALENDAR = "Invalid Calendar Date"
DISPLAY_STATUS_UNSUPPORTED_TEXT = "Unsupported Text Date"
DISPLAY_STATUS_EXCEL_SERIAL = "Possible Excel Serial Date"
DISPLAY_STATUS_BLANK = "Blank"

BLOCKING_STATUSES = {
    STATUS_AMBIGUOUS,
    STATUS_INVALID_CALENDAR,
    STATUS_UNSUPPORTED_TEXT,
    STATUS_EXCEL_SERIAL,
    STATUS_INVALID,
}

EXCEL_SERIAL_ORIGIN = date(1899, 12, 30)
EXCEL_SERIAL_MIN = 1
EXCEL_SERIAL_MAX = 80000

SOURCE_FORMAT_DIT = "DD/MM/YYYY"
SOURCE_FORMAT_WORKBENCH = "YYYY-MM-DD"
SOURCE_FORMAT_US = "MM/DD/YYYY"

TARGET_TOOL_WORKBENCH = "Workbench"
TARGET_TOOL_DIT = "Data Import Tool"

FIELD_TYPE_DATE = "date"
FIELD_TYPE_DATETIME = "datetime"

WORKBENCH_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DIT_DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
ISO_DATETIME_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$"
)
YMD_SLASH_RE = re.compile(r"^(\d{4})/(\d{2})/(\d{2})$")
SLASH_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
DASH_DMY_RE = re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{4})$")
EXCEL_SERIAL_RE = re.compile(r"^\d{4,6}$")
TEXT_DATE_RE = re.compile(
    r"^(\d{1,2})?\s*"
    r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s*(\d{1,2})?,?\s*(\d{4})$",
    re.IGNORECASE,
)
MONTH_NAME_TO_NUMBER = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

WORKBENCH_DATE_FMT = "%Y-%m-%d"
DIT_DATE_FMT = "%d/%m/%Y"
WORKBENCH_DATETIME_FMT = "%Y-%m-%dT%H:%M:%S"
DIT_DATETIME_FMT = "%d/%m/%Y %H:%M:%S"


def default_source_format(upload_method: str) -> str:
    if upload_method == TARGET_TOOL_DIT:
        return SOURCE_FORMAT_DIT
    return SOURCE_FORMAT_WORKBENCH


def target_date_format(upload_method: str, field_type: str = FIELD_TYPE_DATE) -> str:
    if field_type == FIELD_TYPE_DATETIME:
        return WORKBENCH_DATETIME_FMT if upload_method == TARGET_TOOL_WORKBENCH else DIT_DATETIME_FMT
    return WORKBENCH_DATE_FMT if upload_method == TARGET_TOOL_WORKBENCH else DIT_DATE_FMT


def resolve_date_field_columns(
    columns: list[str],
    rename_map: dict[str, str],
    context: Any | None,
    object_fields: dict[str, Any] | None = None,
) -> dict[str, str]:
    """
    Return {column_name: field_type} for every retained date/datetime field.

    Uses Salesforce metadata field type and DIT template date field metadata.
    Does not rely on column names containing 'date'.
    """
    field_types: dict[str, str] = {}
    template_date_labels: set[str] = set()

    if context and context.fallback_config:
        for label in context.fallback_config.get("date_fields", []):
            template_date_labels.add(label)
            template_date_labels.add(rename_map.get(label, label))

    date_types = {"date", "datetime"}
    for column in columns:
        api_name = rename_map.get(column, column)
        metadata = (object_fields or {}).get(api_name)
        metadata_type = getattr(metadata, "field_type", "").lower() if metadata else ""
        if metadata_type in date_types:
            field_types[column] = metadata_type
            continue
        if column in template_date_labels or api_name in template_date_labels:
            field_types[column] = FIELD_TYPE_DATE

    return field_types


def convert_date_column(
    series: pd.Series,
    source_format: str | None,
    target_tool: str,
    field_type: str = FIELD_TYPE_DATE,
) -> dict[str, Any]:
    """
    Convert every nonblank cell in a date column.

    Returns corrected values, per-row outcomes, and column summary counts.
    """
    corrected = series.copy()
    rows: list[dict[str, Any]] = []
    summary = {
        "detected": 0,
        "already_correct": 0,
        "can_convert": 0,
        "ambiguous": 0,
        "invalid": 0,
        "excel_serial": 0,
        "blank": 0,
    }

    for idx, raw_value in series.items():
        if is_blank(raw_value):
            summary["blank"] += 1
            continue

        summary["detected"] += 1
        row_number = idx + 2
        analysis = analyze_cell(raw_value, source_format, target_tool, field_type)
        status = analysis["status"]

        if status == STATUS_VALID:
            summary["already_correct"] += 1
            rows.append(_row_detail(row_number, raw_value, analysis["converted"], status, analysis["reason"]))
            continue

        if status == STATUS_CONVERTED:
            summary["can_convert"] += 1
            corrected.at[idx] = analysis["converted"]
            rows.append(_row_detail(row_number, raw_value, analysis["converted"], status, analysis["reason"]))
            continue

        if status == STATUS_AMBIGUOUS:
            summary["ambiguous"] += 1
            rows.append(_row_detail(row_number, raw_value, raw_value, status, analysis["reason"]))
            continue

        if status == STATUS_EXCEL_SERIAL:
            summary["excel_serial"] += 1
            rows.append(_row_detail(
                row_number,
                raw_value,
                analysis.get("converted", raw_value),
                status,
                analysis["reason"],
            ))
            continue

        if status == STATUS_INVALID_CALENDAR:
            summary["invalid"] += 1
            rows.append(_row_detail(row_number, raw_value, raw_value, status, analysis["reason"]))
            continue

        if status == STATUS_UNSUPPORTED_TEXT:
            summary["invalid"] += 1
            rows.append(_row_detail(
                row_number,
                raw_value,
                analysis.get("converted", raw_value),
                status,
                analysis["reason"],
            ))
            continue

        if status == STATUS_INVALID:
            summary["invalid"] += 1
            rows.append(_row_detail(row_number, raw_value, raw_value, status, analysis["reason"]))
            continue

    return {
        "corrected_series": corrected,
        "rows": rows,
        "summary": summary,
        "target_format": target_date_format(target_tool, field_type),
        "field_type": field_type,
    }


def build_date_conversion_plan(
    df: pd.DataFrame,
    date_field_types: dict[str, str],
    upload_method: str,
    source_format: str | None = None,
) -> dict[str, Any]:
    """Build a conversion plan for every mapped date/datetime column."""
    resolved_source = source_format or default_source_format(upload_method)
    columns: dict[str, Any] = {}
    has_ambiguous = False
    has_blocking = False

    for column, field_type in date_field_types.items():
        if column not in df.columns:
            continue
        result = convert_date_column(df[column], resolved_source, upload_method, field_type)
        columns[column] = result
        if result["summary"]["ambiguous"]:
            has_ambiguous = True
        if result["summary"]["invalid"] or result["summary"]["excel_serial"]:
            has_blocking = True

    return {
        "upload_method": upload_method,
        "source_format": resolved_source,
        "columns": columns,
        "has_ambiguous": has_ambiguous,
        "has_blocking": has_blocking,
        "requires_source_format_selection": has_ambiguous and not source_format,
    }


def apply_date_conversions(
    df: pd.DataFrame,
    plan: dict[str, Any],
    approved_columns: set[str] | None = None,
    *,
    approved_resolutions: list[dict[str, Any]] | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Apply approved date conversions to a copy of the dataframe."""
    working = df.copy()
    change_log: list[dict[str, Any]] = []
    approved_columns = approved_columns or set(plan.get("columns", {}).keys())

    for column in approved_columns:
        column_plan = plan.get("columns", {}).get(column)
        if not column_plan:
            continue
        for row in column_plan.get("rows", []):
            if row["status"] != STATUS_CONVERTED:
                continue
            idx = row["row"] - 2
            if idx not in working.index:
                continue
            original = normalize_text(working.at[idx, column])
            proposed = row["proposed_value"]
            if original == proposed:
                continue
            working.at[idx, column] = proposed
            change_log.append({
                "category": "convert_dates",
                "row": row["row"],
                "field": column,
                "original_value": row["original_value"],
                "new_value": proposed,
                "reason": row["reason"],
            })

    if approved_resolutions:
        for resolution in approved_resolutions:
            column = resolution.get("field")
            row_number = resolution.get("row")
            proposed = resolution.get("proposed_value")
            if not column or row_number is None or column not in working.columns:
                continue
            idx = row_number - 2
            if idx not in working.index:
                continue
            original = normalize_text(working.at[idx, column])
            if original == proposed:
                continue
            working.at[idx, column] = proposed
            change_log.append({
                "category": "convert_dates",
                "row": row_number,
                "field": column,
                "original_value": resolution.get("original_value", original),
                "new_value": proposed,
                "reason": resolution.get("reason", "Approved date resolution applied"),
            })

    return working, change_log


def analyze_cell(
    raw_value: Any,
    source_format: str | None,
    target_tool: str,
    field_type: str = FIELD_TYPE_DATE,
) -> dict[str, Any]:
    """Analyze a single cell without silent day/month guessing."""
    if isinstance(raw_value, (datetime, pd.Timestamp)):
        parsed = raw_value.to_pydatetime() if isinstance(raw_value, pd.Timestamp) else raw_value
        converted = _format_datetime(parsed, target_tool, field_type)
        return {
            "status": STATUS_CONVERTED,
            "converted": converted,
            "reason": DISPLAY_STATUS_CONVERTED,
        }

    text = normalize_text(raw_value)
    if not text:
        return {"status": STATUS_BLANK, "converted": "", "reason": DISPLAY_STATUS_BLANK}

    target_fmt = target_date_format(target_tool, field_type)
    if _matches_target(text, target_tool, field_type):
        if _validate_target_value(text, target_tool, field_type):
            return {"status": STATUS_VALID, "converted": text, "reason": DISPLAY_STATUS_VALID}
        return {
            "status": STATUS_INVALID_CALENDAR,
            "converted": text,
            "reason": DISPLAY_STATUS_INVALID_CALENDAR,
        }

    iso_dt = ISO_DATETIME_RE.fullmatch(text)
    if iso_dt:
        year, month, day, hour, minute, second = map(int, iso_dt.groups())
        if not _valid_ymd(year, month, day):
            return {
                "status": STATUS_INVALID_CALENDAR,
                "converted": text,
                "reason": DISPLAY_STATUS_INVALID_CALENDAR,
            }
        parsed = datetime(year, month, day, hour, minute, second)
        converted = _format_datetime(parsed, target_tool, field_type)
        if converted == text:
            return {"status": STATUS_VALID, "converted": converted, "reason": DISPLAY_STATUS_VALID}
        return {
            "status": STATUS_CONVERTED,
            "converted": converted,
            "reason": DISPLAY_STATUS_CONVERTED,
        }

    iso_match = ISO_DATE_RE.fullmatch(text)
    if iso_match:
        year, month, day = map(int, iso_match.groups())
        if not _valid_ymd(year, month, day):
            return {
                "status": STATUS_INVALID_CALENDAR,
                "converted": text,
                "reason": DISPLAY_STATUS_INVALID_CALENDAR,
            }
        parsed = datetime(year, month, day)
        converted = _format_datetime(parsed, target_tool, field_type)
        if converted == text:
            return {"status": STATUS_VALID, "converted": converted, "reason": DISPLAY_STATUS_VALID}
        return {
            "status": STATUS_CONVERTED,
            "converted": converted,
            "reason": DISPLAY_STATUS_CONVERTED,
        }

    ymd_slash = YMD_SLASH_RE.fullmatch(text)
    if ymd_slash:
        year, month, day = map(int, ymd_slash.groups())
        if not _valid_ymd(year, month, day):
            return {
                "status": STATUS_INVALID_CALENDAR,
                "converted": text,
                "reason": DISPLAY_STATUS_INVALID_CALENDAR,
            }
        parsed = datetime(year, month, day)
        converted = _format_datetime(parsed, target_tool, field_type)
        return {
            "status": STATUS_CONVERTED,
            "converted": converted,
            "reason": DISPLAY_STATUS_CONVERTED,
        }

    if EXCEL_SERIAL_RE.fullmatch(text) and text.isdigit():
        serial = int(text)
        if _is_plausible_excel_serial(serial):
            suggested = _format_parsed_date(_excel_serial_to_date(serial), target_tool, field_type)
            return {
                "status": STATUS_EXCEL_SERIAL,
                "converted": suggested,
                "reason": DISPLAY_STATUS_EXCEL_SERIAL,
            }
        return {
            "status": STATUS_INVALID,
            "converted": text,
            "reason": DISPLAY_STATUS_INVALID_CALENDAR,
        }

    slash_match = SLASH_DATE_RE.fullmatch(text)
    if slash_match:
        return _parse_slash_date(
            slash_match.groups(),
            source_format,
            target_tool,
            field_type,
            text,
        )

    dash_match = DASH_DMY_RE.fullmatch(text)
    if dash_match:
        return _parse_dash_dmy(
            dash_match.groups(),
            source_format,
            target_tool,
            field_type,
            text,
        )

    text_date = _try_parse_text_date(text)
    if text_date is not None:
        suggested = _format_parsed_date(text_date, target_tool, field_type)
        return {
            "status": STATUS_UNSUPPORTED_TEXT,
            "converted": suggested,
            "reason": DISPLAY_STATUS_UNSUPPORTED_TEXT,
        }

    if _looks_like_text_date(text):
        return {
            "status": STATUS_UNSUPPORTED_TEXT,
            "converted": text,
            "reason": DISPLAY_STATUS_UNSUPPORTED_TEXT,
        }

    return {
        "status": STATUS_INVALID,
        "converted": text,
        "reason": DISPLAY_STATUS_INVALID_CALENDAR,
    }


def _parse_day_first_slash(text: str) -> date | None:
    """Parse D/M/YYYY slash dates without requiring leading zeroes."""
    parts = text.strip().split("/")
    if len(parts) != 3:
        return None
    try:
        day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None
    if not _valid_ymd(year, month, day):
        return None
    return date(year, month, day)


def _parse_slash_date(
    groups: tuple[str, ...],
    source_format: str | None,
    target_tool: str,
    field_type: str,
    original: str,
) -> dict[str, Any]:
    first, second, year = map(int, groups)
    ambiguity = _slash_ambiguity(first, second)

    if ambiguity == "unambiguous_dmy":
        day, month = first, second
    elif ambiguity == "unambiguous_mdy":
        month, day = first, second
    elif source_format == SOURCE_FORMAT_US:
        month, day = first, second
    else:
        # DIT, WORKBENCH, and unset source: slash dates are day-first (D/M/YYYY).
        # WORKBENCH source means ISO-native files; slash cells are imported D/M/YYYY.
        day, month = first, second

    if not _valid_ymd(year, month, day):
        return {
            "status": STATUS_INVALID_CALENDAR,
            "converted": original,
            "reason": DISPLAY_STATUS_INVALID_CALENDAR,
        }

    converted = _format_parsed_date(date(year, month, day), target_tool, field_type)
    if converted == original:
        return {"status": STATUS_VALID, "converted": converted, "reason": DISPLAY_STATUS_VALID}
    return {
        "status": STATUS_CONVERTED,
        "converted": converted,
        "reason": DISPLAY_STATUS_CONVERTED,
    }


def _parse_dash_dmy(
    groups: tuple[str, ...],
    source_format: str | None,
    target_tool: str,
    field_type: str,
    original: str,
) -> dict[str, Any]:
    first, second, year = map(int, groups)
    ambiguity = _slash_ambiguity(first, second)

    if ambiguity == "unambiguous_dmy":
        day, month = first, second
    elif ambiguity == "unambiguous_mdy":
        if source_format == SOURCE_FORMAT_US:
            month, day = first, second
        else:
            day, month = first, second
    elif source_format == SOURCE_FORMAT_US:
        month, day = first, second
    else:
        day, month = first, second

    if not _valid_ymd(year, month, day):
        return {
            "status": STATUS_INVALID_CALENDAR,
            "converted": original,
            "reason": DISPLAY_STATUS_INVALID_CALENDAR,
        }

    converted = _format_parsed_date(date(year, month, day), target_tool, field_type)
    if converted == original:
        return {"status": STATUS_VALID, "converted": converted, "reason": DISPLAY_STATUS_VALID}
    return {
        "status": STATUS_CONVERTED,
        "converted": converted,
        "reason": DISPLAY_STATUS_CONVERTED,
    }


def _slash_ambiguity(first: int, second: int) -> str:
    if first > 12 and second <= 12:
        return "unambiguous_dmy"
    if second > 12 and first <= 12:
        return "unambiguous_mdy"
    if first > 12 and second > 12:
        return "invalid"
    return "ambiguous"


def _format_parsed_date(parsed: date, target_tool: str, field_type: str) -> str:
    if field_type == FIELD_TYPE_DATETIME:
        fmt = WORKBENCH_DATETIME_FMT if target_tool == TARGET_TOOL_WORKBENCH else DIT_DATETIME_FMT
        return datetime(parsed.year, parsed.month, parsed.day).strftime(fmt)
    fmt = WORKBENCH_DATE_FMT if target_tool == TARGET_TOOL_WORKBENCH else DIT_DATE_FMT
    return parsed.strftime(fmt)


def _format_datetime(value: datetime, target_tool: str, field_type: str) -> str:
    if field_type == FIELD_TYPE_DATETIME:
        fmt = WORKBENCH_DATETIME_FMT if target_tool == TARGET_TOOL_WORKBENCH else DIT_DATETIME_FMT
        return value.strftime(fmt)
    return _format_parsed_date(value.date(), target_tool, field_type)


def _matches_target(text: str, target_tool: str, field_type: str) -> bool:
    if field_type == FIELD_TYPE_DATETIME:
        if target_tool == TARGET_TOOL_WORKBENCH:
            return bool(ISO_DATETIME_RE.fullmatch(text))
        return bool(DIT_DATE_RE.fullmatch(text.split()[0])) if " " in text else bool(DIT_DATE_RE.fullmatch(text))
    if target_tool == TARGET_TOOL_WORKBENCH:
        return bool(WORKBENCH_DATE_RE.fullmatch(text))
    return bool(DIT_DATE_RE.fullmatch(text))


def _validate_target_value(text: str, target_tool: str, field_type: str) -> bool:
    if field_type == FIELD_TYPE_DATETIME:
        iso_dt = ISO_DATETIME_RE.fullmatch(text)
        if iso_dt:
            year, month, day, hour, minute, second = map(int, iso_dt.groups())
            return _valid_ymd(year, month, day)
        dit_match = DIT_DATE_RE.fullmatch(text.split()[0])
        if dit_match:
            day, month, year = map(int, dit_match.groups())
            return _valid_ymd(year, month, day)
        return False

    if target_tool == TARGET_TOOL_WORKBENCH:
        iso_match = ISO_DATE_RE.fullmatch(text)
        if iso_match:
            year, month, day = map(int, iso_match.groups())
            return _valid_ymd(year, month, day)
        return False

    dit_match = DIT_DATE_RE.fullmatch(text)
    if dit_match:
        day, month, year = map(int, dit_match.groups())
        return _valid_ymd(year, month, day)
    return False


def _valid_ymd(year: int, month: int, day: int) -> bool:
    if month < 1 or month > 12 or day < 1 or day > 31:
        return False
    try:
        date(year, month, day)
        return True
    except ValueError:
        return False


def _looks_like_text_date(text: str) -> bool:
    lowered = text.lower()
    months = (
        "jan", "feb", "mar", "apr", "may", "jun",
        "jul", "aug", "sep", "oct", "nov", "dec",
    )
    return any(month in lowered for month in months)


def display_status(status: str) -> str:
    """Map internal status codes to user-facing category labels."""
    mapping = {
        STATUS_VALID: DISPLAY_STATUS_VALID,
        STATUS_CONVERTED: DISPLAY_STATUS_CONVERTED,
        STATUS_AMBIGUOUS: DISPLAY_STATUS_AMBIGUOUS,
        STATUS_INVALID_CALENDAR: DISPLAY_STATUS_INVALID_CALENDAR,
        STATUS_UNSUPPORTED_TEXT: DISPLAY_STATUS_UNSUPPORTED_TEXT,
        STATUS_EXCEL_SERIAL: DISPLAY_STATUS_EXCEL_SERIAL,
        STATUS_BLANK: DISPLAY_STATUS_BLANK,
        STATUS_INVALID: DISPLAY_STATUS_INVALID_CALENDAR,
        "already_correct": DISPLAY_STATUS_VALID,
        "convertible": DISPLAY_STATUS_CONVERTED,
        "ambiguous": DISPLAY_STATUS_AMBIGUOUS,
        "invalid": DISPLAY_STATUS_INVALID_CALENDAR,
        "excel_serial": DISPLAY_STATUS_EXCEL_SERIAL,
        "blank": DISPLAY_STATUS_BLANK,
    }
    return mapping.get(status, status)


def is_blocking_date_status(status: str) -> bool:
    return status in BLOCKING_STATUSES or status in {"ambiguous", "invalid", "excel_serial"}


def analyze_dataframe_dates(
    df: pd.DataFrame,
    date_field_types: dict[str, str],
    upload_method: str,
    source_format: str | None = None,
) -> list[dict[str, Any]]:
    """Analyze every nonblank date cell and return per-cell status records."""
    resolved_source = source_format or default_source_format(upload_method)
    records: list[dict[str, Any]] = []

    for column, field_type in date_field_types.items():
        if column not in df.columns:
            continue
        for idx, raw_value in df[column].items():
            if is_blank(raw_value):
                continue
            analysis = analyze_cell(raw_value, resolved_source, upload_method, field_type)
            records.append({
                "row": idx + 2,
                "field": column,
                "original_value": normalize_text(raw_value),
                "current_value": normalize_text(raw_value),
                "suggested_value": analysis.get("converted", ""),
                "status": analysis["status"],
                "display_status": display_status(analysis["status"]),
                "reason": analysis.get("reason", ""),
                "blocking": is_blocking_date_status(analysis["status"]),
            })

    return records


def build_date_status_preview(
    df: pd.DataFrame,
    date_field_types: dict[str, str],
    upload_method: str,
    source_format: str | None = None,
) -> pd.DataFrame:
    """Return preview dataframe with per-date-column status columns."""
    preview = df.copy()
    resolved_source = source_format or default_source_format(upload_method)

    for column, field_type in date_field_types.items():
        if column not in preview.columns:
            continue
        status_column = f"{column} Status"
        statuses: list[str] = []
        for raw_value in preview[column]:
            if is_blank(raw_value):
                statuses.append("")
                continue
            analysis = analyze_cell(raw_value, resolved_source, upload_method, field_type)
            statuses.append(display_status(analysis["status"]))
        preview[status_column] = statuses

    return preview


def collect_unresolved_date_rows(
    df: pd.DataFrame,
    date_field_types: dict[str, str],
    upload_method: str,
    source_format: str | None = None,
) -> list[dict[str, Any]]:
    """Collect blocking date issues for manual review and download gating."""
    return [
        record for record in analyze_dataframe_dates(df, date_field_types, upload_method, source_format)
        if record["blocking"]
    ]


def attach_date_validation_state(
    preparation_result: dict[str, Any],
    date_field_types: dict[str, str],
    upload_method: str,
    source_format: str | None = None,
) -> dict[str, Any]:
    """Annotate preparation result with unresolved dates and status preview."""
    if not preparation_result or preparation_result.get("corrected_df") is None:
        return preparation_result

    corrected_df = preparation_result["corrected_df"]
    unresolved = revalidate_dataframe_dates(
        corrected_df,
        date_field_types,
        upload_method,
        source_format,
    )
    preparation_result["date_unresolved"] = unresolved
    preparation_result["date_status_preview"] = build_date_status_preview(
        corrected_df,
        date_field_types,
        upload_method,
        source_format,
    )

    manual_review = list(preparation_result.get("manual_review", []))
    existing_keys = {
        (item.get("row"), item.get("field"), item.get("value"))
        for item in manual_review
    }
    for item in unresolved:
        key = (item.get("row"), item.get("field"), item.get("value"))
        if key in existing_keys:
            continue
        manual_review.append({
            "row": item.get("row"),
            "field": item.get("field"),
            "value": item.get("value"),
            "reason": item.get("reason"),
            "display_status": item.get("display_status"),
        })
        existing_keys.add(key)

    preparation_result["manual_review"] = manual_review
    return preparation_result


def revalidate_dataframe_dates(
    df: pd.DataFrame,
    date_field_types: dict[str, str],
    upload_method: str,
    source_format: str | None = None,
) -> list[dict[str, Any]]:
    """Post-conversion revalidation — format regex and calendar validity required."""
    unresolved: list[dict[str, Any]] = []

    for column, field_type in date_field_types.items():
        if column not in df.columns:
            continue
        for idx, raw_value in df[column].items():
            if is_blank(raw_value):
                continue
            text = normalize_text(raw_value)
            if _validate_target_value(text, upload_method, field_type):
                continue
            analysis = analyze_cell(raw_value, source_format, upload_method, field_type)
            unresolved.append({
                "row": idx + 2,
                "field": column,
                "value": text,
                "reason": (
                    f"{display_status(analysis['status'])} — "
                    f"value '{text}' is not a valid {target_date_format(upload_method, field_type)} date"
                ),
                "display_status": display_status(analysis["status"]),
                "blocking": True,
            })

    return unresolved


def _try_parse_text_date(text: str) -> date | None:
    match = TEXT_DATE_RE.fullmatch(text.strip())
    if not match:
        return None

    leading_day, month_name, trailing_day, year_text = match.groups()
    month = MONTH_NAME_TO_NUMBER.get(month_name.lower())
    if not month:
        return None

    day_text = leading_day or trailing_day
    if not day_text:
        return None

    day = int(day_text)
    year = int(year_text)
    if not _valid_ymd(year, month, day):
        return None
    return date(year, month, day)


def _is_plausible_excel_serial(serial: int) -> bool:
    return EXCEL_SERIAL_MIN <= serial <= EXCEL_SERIAL_MAX


def _excel_serial_to_date(serial: int) -> date:
    return EXCEL_SERIAL_ORIGIN + timedelta(days=serial)


def _row_detail(
    row_number: int,
    original_value: Any,
    proposed_value: Any,
    status: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "row": row_number,
        "original_value": normalize_text(original_value),
        "proposed_value": normalize_text(proposed_value),
        "status": status,
        "reason": reason,
    }
