"""Date parsing and validation with upload-tool-specific target formats."""



from __future__ import annotations



import re

from typing import Any



from services.date_conversion_service import (

    DISPLAY_STATUS_AMBIGUOUS,

    DISPLAY_STATUS_CONVERTED,

    DISPLAY_STATUS_EXCEL_SERIAL,

    DISPLAY_STATUS_INVALID_CALENDAR,

    DISPLAY_STATUS_UNSUPPORTED_TEXT,

    FIELD_TYPE_DATE,

    FIELD_TYPE_DATETIME,

    SOURCE_FORMAT_DIT,

    SOURCE_FORMAT_US,

    SOURCE_FORMAT_WORKBENCH,

    STATUS_AMBIGUOUS,

    STATUS_CONVERTED,

    STATUS_EXCEL_SERIAL,

    STATUS_INVALID,

    STATUS_INVALID_CALENDAR,

    STATUS_UNSUPPORTED_TEXT,

    STATUS_VALID,

    TARGET_TOOL_DIT,

    TARGET_TOOL_WORKBENCH,

    analyze_cell,

    default_source_format,

    display_status,

    target_date_format,

    _validate_target_value,

)

from validators.common import build_issue, is_blank, normalize_text



DIT_TARGET_FORMAT = "%d/%m/%Y"

WORKBENCH_TARGET_FORMAT = "%Y-%m-%d"



WORKBENCH_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

DIT_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")

WORKBENCH_DATETIME_RE = re.compile(

    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$"

)





def target_format_for_upload_method(upload_method: str) -> str:

    if upload_method == TARGET_TOOL_DIT:

        return DIT_TARGET_FORMAT

    return WORKBENCH_TARGET_FORMAT





def validate_dates(

    df,

    date_fields: list[str] | dict[str, str],

    upload_method: str,

    source_format: str | None = None,

    *,

    post_conversion: bool = False,

) -> list[dict[str, Any]]:

    issues: list[dict[str, Any]] = []

    target_fmt = target_format_for_upload_method(upload_method)

    field_types = _normalize_field_types(date_fields)

    resolved_source = source_format or default_source_format(upload_method)



    for field, field_type in field_types.items():

        if field not in df.columns:

            continue

        for idx, raw_value in df[field].items():

            if is_blank(raw_value):

                continue

            text = normalize_text(raw_value)

            row_number = idx + 2



            if post_conversion:

                if _is_valid_post_conversion(text, upload_method, field_type):

                    continue

                analysis = analyze_cell(raw_value, resolved_source, upload_method, field_type)

                reason = (

                    f"{display_status(analysis['status'])} — "

                    f"value does not match required format "

                    f"{target_fmt.replace('%d', 'DD').replace('%m', 'MM').replace('%Y', 'YYYY')}"

                )

                issues.append(build_issue(

                    issue_id=f"date:{field}:{row_number}",

                    category="dates",

                    field=field,

                    row=row_number,

                    original_value=text,

                    proposed_value=text,

                    reason=reason,

                    safe=False,

                    blocking=True,

                    confidence=0.0,

                ))

                continue



            analysis = analyze_cell(raw_value, resolved_source, upload_method, field_type)

            status = analysis["status"]



            if status in {STATUS_VALID, "already_correct", "blank"}:

                continue



            if status in {STATUS_CONVERTED, "convertible"}:

                issues.append(build_issue(

                    issue_id=f"date:{field}:{row_number}",

                    category="dates",

                    field=field,

                    row=row_number,

                    original_value=text,

                    proposed_value=analysis["converted"],

                    reason=(

                        f"{DISPLAY_STATUS_CONVERTED}: convert to "

                        f"{target_fmt.replace('%d', 'DD').replace('%m', 'MM').replace('%Y', 'YYYY')} "

                        f"for {upload_method}"

                    ),

                    safe=True,

                    confidence=1.0,

                ))

                continue



            if status in {STATUS_AMBIGUOUS, "ambiguous"}:

                issues.append(build_issue(

                    issue_id=f"date:{field}:{row_number}",

                    category="dates",

                    field=field,

                    row=row_number,

                    original_value=text,

                    proposed_value=text,

                    reason=f"{DISPLAY_STATUS_AMBIGUOUS} — user confirmation required.",

                    safe=False,

                    blocking=True,

                    confidence=0.4,

                ))

                continue



            if status in {STATUS_EXCEL_SERIAL, "excel_serial"}:

                issues.append(build_issue(

                    issue_id=f"date:{field}:{row_number}",

                    category="dates",

                    field=field,

                    row=row_number,

                    original_value=text,

                    proposed_value=analysis.get("converted", text),

                    reason=f"{DISPLAY_STATUS_EXCEL_SERIAL} — Confirmation Required",

                    safe=False,

                    blocking=True,

                    requires_confirmation=True,

                    confidence=0.5,

                ))

                continue



            if status in {STATUS_UNSUPPORTED_TEXT, "unsupported_text"}:

                issues.append(build_issue(

                    issue_id=f"date:{field}:{row_number}",

                    category="dates",

                    field=field,

                    row=row_number,

                    original_value=text,

                    proposed_value=analysis.get("converted", text),

                    reason=f"{DISPLAY_STATUS_UNSUPPORTED_TEXT} — approval required",

                    safe=False,

                    blocking=True,

                    requires_confirmation=True,

                    confidence=0.3,

                ))

                continue



            if status in {STATUS_INVALID_CALENDAR, STATUS_INVALID, "invalid"}:

                issues.append(build_issue(

                    issue_id=f"date:{field}:{row_number}",

                    category="dates",

                    field=field,

                    row=row_number,

                    original_value=text,

                    proposed_value=text,

                    reason=f"{DISPLAY_STATUS_INVALID_CALENDAR} — Manual Review Required",

                    safe=False,

                    blocking=True,

                    confidence=0.0,

                ))

                continue



            issues.append(build_issue(

                issue_id=f"date:{field}:{row_number}",

                category="dates",

                field=field,

                row=row_number,

                original_value=text,

                proposed_value=text,

                reason=f"{DISPLAY_STATUS_INVALID_CALENDAR} — Manual Review Required",

                safe=False,

                blocking=True,

                confidence=0.0,

            ))



    return issues





def analyze_date_value(

    text: str,

    upload_method: str,

    source_format: str | None = None,

    field_type: str = FIELD_TYPE_DATE,

) -> dict[str, Any]:

    """Backward-compatible wrapper around strict cell analysis."""

    resolved_source = source_format or default_source_format(upload_method)

    analysis = analyze_cell(text, resolved_source, upload_method, field_type)

    status = analysis["status"]

    if status in {STATUS_VALID, "already_correct"}:

        return {"status": "valid_target", "converted": analysis["converted"], "confidence": 1.0}

    if status in {STATUS_CONVERTED, "convertible"}:

        return {"status": "convertible", "converted": analysis["converted"], "confidence": 1.0}

    if status in {STATUS_AMBIGUOUS, "ambiguous"}:

        return {"status": "ambiguous", "confidence": 0.4}

    if status in {STATUS_EXCEL_SERIAL, "excel_serial"}:

        return {

            "status": "excel_serial",

            "converted": analysis.get("converted"),

            "confidence": 0.5,

        }

    if status in {STATUS_UNSUPPORTED_TEXT, "unsupported_text"}:

        return {

            "status": "unsupported_text",

            "converted": analysis.get("converted"),

            "confidence": 0.3,

        }

    return {"status": "invalid", "confidence": 0.0}





def format_date(value, upload_method: str, field_type: str = FIELD_TYPE_DATE) -> str:

    from datetime import datetime



    if not isinstance(value, datetime):

        raise TypeError("format_date expects a datetime value")

    return value.strftime(target_date_format(upload_method, field_type))





def _normalize_field_types(date_fields: list[str] | dict[str, str]) -> dict[str, str]:

    if isinstance(date_fields, dict):

        return date_fields

    return {field: FIELD_TYPE_DATE for field in date_fields}





def _is_valid_post_conversion(text: str, upload_method: str, field_type: str) -> bool:

    return _validate_target_value(text, upload_method, field_type)





__all__ = [

    "SOURCE_FORMAT_DIT",

    "SOURCE_FORMAT_US",

    "SOURCE_FORMAT_WORKBENCH",

    "analyze_date_value",

    "format_date",

    "target_format_for_upload_method",

    "validate_dates",

]

