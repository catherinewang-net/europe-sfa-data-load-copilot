"""Apply and validate in-app corrections for unresolved row-level issues."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from services.date_conversion_service import (
    DISPLAY_STATUS_AMBIGUOUS,
    DISPLAY_STATUS_EXCEL_SERIAL,
    DISPLAY_STATUS_INVALID_CALENDAR,
    DISPLAY_STATUS_UNSUPPORTED_TEXT,
    FIELD_TYPE_DATE,
    STATUS_AMBIGUOUS,
    STATUS_EXCEL_SERIAL,
    STATUS_INVALID,
    STATUS_INVALID_CALENDAR,
    STATUS_UNSUPPORTED_TEXT,
    TARGET_TOOL_DIT,
    _validate_target_value,
    analyze_cell,
    attach_date_validation_state,
    default_source_format,
    target_date_format,
)
from services.picklist_correction_service import revalidate_picklists_after_corrections
from services.row_correction_plan_service import build_row_correction_plan
from validators.common import normalize_text
from validators.duplicate_key_validator import validate_duplicate_keys
from validators.numeric_validator import _propose_numeric_conversion

ISSUE_EDITS_KEY = "issue_edits"
DUPLICATE_ROWS_RE = re.compile(r"rows?\s+([\d,\s]+)", re.IGNORECASE)

BLOCKING_PICKLIST_STATUSES = {
    "Needs User Action",
    "Invalid Picklist Value",
    "Multipicklist Value Invalid",
    "Blank Required Value",
}


def make_edit_key(row: int | None, field: str | None) -> str:
    safe_field = re.sub(r"[^\w]", "_", field or "field")
    return f"row_{row or 0}_{safe_field}"


def get_issue_edits(session_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if ISSUE_EDITS_KEY not in session_state:
        session_state[ISSUE_EDITS_KEY] = {}
    return session_state[ISSUE_EDITS_KEY]


def save_pending_edit(
    session_state: dict[str, Any],
    edit_key: str,
    *,
    original: str,
    proposed: str,
    validated: bool = False,
    extra: dict[str, Any] | None = None,
) -> None:
    edits = get_issue_edits(session_state)
    entry: dict[str, Any] = {
        "original": original,
        "proposed": proposed,
        "validated": validated,
    }
    if extra:
        entry.update(extra)
    edits[edit_key] = entry
    session_state[ISSUE_EDITS_KEY] = edits


def clear_edit(session_state: dict[str, Any], edit_key: str) -> None:
    edits = get_issue_edits(session_state)
    edits.pop(edit_key, None)
    session_state[ISSUE_EDITS_KEY] = edits


def expected_date_format_label(upload_method: str) -> str:
    if upload_method == TARGET_TOOL_DIT:
        return "DD/MM/YYYY"
    return "YYYY-MM-DD"


def classify_date_issue(reason: str, display_status: str | None = None) -> str:
    text = f"{display_status or ''} {reason}".lower()
    if DISPLAY_STATUS_EXCEL_SERIAL.lower() in text or "excel serial" in text:
        return "excel_serial"
    if DISPLAY_STATUS_UNSUPPORTED_TEXT.lower() in text or "unsupported text" in text:
        return "unsupported_text"
    if DISPLAY_STATUS_AMBIGUOUS.lower() in text or "ambiguous" in text:
        return "ambiguous"
    if DISPLAY_STATUS_INVALID_CALENDAR.lower() in text or "invalid calendar" in text:
        return "invalid_calendar"
    return "invalid_calendar"


def parse_duplicate_rows(reason: str) -> list[int]:
    match = DUPLICATE_ROWS_RE.search(reason or "")
    if not match:
        return []
    return [
        int(part.strip())
        for part in match.group(1).split(",")
        if part.strip().isdigit()
    ]


def expand_duplicate_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    for issue in issues:
        if issue.get("category") != "duplicates":
            expanded.append(issue)
            continue
        rows = parse_duplicate_rows(issue.get("reason", ""))
        if len(rows) <= 1:
            expanded.append(issue)
            continue
        for row in rows:
            expanded.append({
                **issue,
                "issue_id": f"{issue['issue_id']}:row:{row}",
                "row": row,
                "duplicate_group_id": issue["issue_id"],
                "duplicate_rows": rows,
                "duplicate_value": issue.get("original_value"),
            })
    return expanded


def _normalize_date_issue(
    item: dict[str, Any],
    *,
    upload_method: str,
    source_format: str | None,
    field_type: str = FIELD_TYPE_DATE,
) -> dict[str, Any]:
    row = item.get("row")
    field = item.get("field")
    current = normalize_text(item.get("value") or item.get("original_value", ""))
    reason = item.get("reason") or item.get("display_status") or "Invalid date"
    subtype = classify_date_issue(reason, item.get("display_status"))
    analysis = analyze_cell(current, source_format, upload_method, field_type)
    suggested = analysis.get("converted") if analysis.get("converted") != current else None
    if subtype == "unsupported_text" and analysis.get("status") == STATUS_UNSUPPORTED_TEXT:
        suggested = analysis.get("converted")
    if subtype == "excel_serial" and analysis.get("status") in {STATUS_EXCEL_SERIAL, "excel_serial"}:
        suggested = analysis.get("converted")

    return {
        "edit_key": make_edit_key(row, field),
        "issue_id": item.get("issue_id") or make_edit_key(row, field),
        "category": "dates",
        "issue_type": "date",
        "row": row,
        "field": field,
        "field_type": field_type,
        "current_value": current,
        "problem": reason,
        "date_subtype": subtype,
        "suggested_value": suggested,
        "allowed_values": [],
    }


def _normalize_picklist_issue(item: dict[str, Any], mapped_df: pd.DataFrame) -> dict[str, Any]:
    row = item.get("row")
    field = item.get("uploaded_column") or item.get("salesforce_api_field") or item.get("field")
    column_name = field
    if item.get("salesforce_api_field") and item["salesforce_api_field"] in mapped_df.columns:
        column_name = item["salesforce_api_field"]
    elif item.get("uploaded_column") and item["uploaded_column"] in mapped_df.columns:
        column_name = item["uploaded_column"]

    return {
        "edit_key": make_edit_key(row, column_name),
        "issue_id": item.get("issue_id") or make_edit_key(row, column_name),
        "category": "picklist",
        "issue_type": "picklist",
        "row": row,
        "field": column_name,
        "friendly_column": item.get("uploaded_column") or column_name,
        "salesforce_api_field": item.get("salesforce_api_field") or column_name,
        "current_value": normalize_text(item.get("uploaded_value", "")),
        "problem": item.get("reason") or item.get("status") or "Invalid picklist value",
        "allowed_values": list(item.get("allowed_values") or []),
        "field_type": item.get("field_type"),
    }


def _normalize_row_issue(item: dict[str, Any]) -> dict[str, Any]:
    category = item.get("category", "")
    row = item.get("row")
    field = item.get("field")
    issue_type = category
    if category == "identifiers":
        issue_type = "text"
    elif category == "numeric":
        issue_type = "numeric"
    elif category == "duplicates":
        issue_type = "duplicate"
    elif category == "dates":
        issue_type = "date"
    else:
        issue_type = "text"

    normalized = {
        "edit_key": make_edit_key(row, field),
        "issue_id": item.get("issue_id") or make_edit_key(row, field),
        "category": category,
        "issue_type": issue_type,
        "row": row,
        "field": field,
        "current_value": normalize_text(item.get("original_value", "")),
        "problem": item.get("reason") or "Manual review required",
        "allowed_values": list(item.get("allowed_values") or []),
        "duplicate_rows": item.get("duplicate_rows") or [],
        "duplicate_value": item.get("duplicate_value") or item.get("original_value"),
    }
    if issue_type == "date":
        normalized["date_subtype"] = classify_date_issue(normalized["problem"])
        normalized["suggested_value"] = item.get("proposed_value")
    return normalized


def collect_editable_issues(
    *,
    preparation_result: dict[str, Any] | None,
    row_correction_plan: dict[str, Any] | None,
    picklist_validation: dict[str, Any] | None,
    mapped_df: pd.DataFrame,
    upload_method: str,
    date_field_types: dict[str, str] | None = None,
    source_date_format: str | None = None,
) -> list[dict[str, Any]]:
    """Collect unresolved blocking issues suitable for in-app editing."""
    issues: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    date_field_types = date_field_types or {}
    resolved_source = source_date_format or default_source_format(upload_method)

    def _add(issue: dict[str, Any]) -> None:
        key = issue.get("edit_key")
        if not key or key in seen_keys:
            return
        seen_keys.add(key)
        issues.append(issue)

    prep = preparation_result or {}
    for item in prep.get("date_unresolved", []):
        field = item.get("field")
        field_type = date_field_types.get(field, FIELD_TYPE_DATE)
        _add(_normalize_date_issue(
            item,
            upload_method=upload_method,
            source_format=resolved_source,
            field_type=field_type,
        ))

    plan = row_correction_plan or {}
    blocking = [
        issue for issue in plan.get("issues", [])
        if issue.get("blocking") and not issue.get("safe")
    ]
    blocking.extend(plan.get("manual_review", []))
    blocking = expand_duplicate_issues(blocking)

    for item in blocking:
        if item.get("category") == "dates":
            field = item.get("field")
            field_type = date_field_types.get(field, FIELD_TYPE_DATE)
            _add(_normalize_date_issue(
                item,
                upload_method=upload_method,
                source_format=resolved_source,
                field_type=field_type,
            ))
        else:
            _add(_normalize_row_issue(item))

    picklist_validation = picklist_validation or {}
    for item in picklist_validation.get("issues", []):
        if item.get("status") not in BLOCKING_PICKLIST_STATUSES:
            continue
        if item.get("row") is None:
            continue
        _add(_normalize_picklist_issue(item, mapped_df))

    return sorted(issues, key=lambda issue: (issue.get("row") or 0, issue.get("field") or ""))


def validate_date_replacement(
    value: str,
    upload_method: str,
    field_type: str = FIELD_TYPE_DATE,
) -> dict[str, Any]:
    text = normalize_text(value)
    if not text:
        fmt = expected_date_format_label(upload_method)
        return {
            "valid": False,
            "message": f"❌ Enter a valid date in required format ({fmt})",
            "normalized_value": "",
        }
    if _validate_target_value(text, upload_method, field_type):
        return {
            "valid": True,
            "message": "✅ Date corrected",
            "normalized_value": text,
        }
    fmt = expected_date_format_label(upload_method)
    return {
        "valid": False,
        "message": f"❌ Enter a valid date in required format ({fmt})",
        "normalized_value": text,
    }


def validate_numeric_replacement(value: str) -> dict[str, Any]:
    text = normalize_text(value)
    if not text:
        return {"valid": False, "message": "❌ Enter a valid numeric value", "normalized_value": ""}
    converted = _propose_numeric_conversion(text)
    if converted is not None:
        return {"valid": True, "message": "✅ Numeric value accepted", "normalized_value": converted}
    if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        return {"valid": True, "message": "✅ Numeric value accepted", "normalized_value": text}
    return {"valid": False, "message": "❌ Enter a valid numeric value", "normalized_value": text}


def validate_text_replacement(value: str) -> dict[str, Any]:
    text = normalize_text(value)
    if not text:
        return {"valid": False, "message": "❌ Enter a replacement value", "normalized_value": ""}
    return {"valid": True, "message": "✅ Value accepted", "normalized_value": text}


def validate_picklist_replacement(value: str, allowed_values: list[str]) -> dict[str, Any]:
    text = normalize_text(value)
    if not text:
        return {"valid": False, "message": "❌ Select a valid API value", "normalized_value": ""}
    if text not in allowed_values:
        return {"valid": False, "message": "❌ Select a valid API value from the allowed list", "normalized_value": text}
    return {"valid": True, "message": "✅ Picklist value accepted", "normalized_value": text}


def validate_replacement(
    issue: dict[str, Any],
    value: str,
    upload_method: str,
) -> dict[str, Any]:
    issue_type = issue.get("issue_type")
    if issue_type == "date":
        return validate_date_replacement(
            value,
            upload_method,
            issue.get("field_type", FIELD_TYPE_DATE),
        )
    if issue_type == "numeric":
        return validate_numeric_replacement(value)
    if issue_type == "picklist":
        return validate_picklist_replacement(value, issue.get("allowed_values") or [])
    return validate_text_replacement(value)


def apply_cell_correction(
    df: pd.DataFrame,
    row_number: int,
    field: str,
    new_value: str,
) -> pd.DataFrame:
    working = df.copy()
    idx = row_number - 2
    if idx in working.index and field in working.columns:
        working.at[idx, field] = new_value
    return working


def build_change_log_entry(
    issue: dict[str, Any],
    *,
    original_value: str,
    new_value: str,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "category": issue.get("category", "manual_edit"),
        "row": issue.get("row"),
        "field": issue.get("field"),
        "original_value": original_value,
        "new_value": new_value,
        "reason": reason or f"In-app correction for {issue.get('problem', 'issue')}",
        "issue_id": issue.get("issue_id"),
        "correction_type": "issue_editor",
    }


def revalidate_after_issue_edit(
    *,
    preparation_result: dict[str, Any],
    original_df: pd.DataFrame,
    correction: dict[str, Any],
    upload_method: str,
    template: str,
    mapping_rows: list[dict[str, Any]] | None,
    validation_bundle: dict[str, Any] | None,
    row_correction_plan: dict[str, Any] | None,
    date_field_types: dict[str, str] | None,
    source_date_format: str | None,
    template_context: Any | None,
    raw_csv_content: str | None = None,
    use_mapped_columns: bool = False,
) -> dict[str, Any]:
    """Apply one approved correction, re-run validators, and refresh readiness inputs."""
    corrected_df = apply_cell_correction(
        preparation_result["corrected_df"],
        correction["row"],
        correction["field"],
        correction["proposed_value"],
    )
    updated_result = dict(preparation_result)
    updated_result["corrected_df"] = corrected_df
    change_log = list(updated_result.get("change_log", []))
    change_log.append(build_change_log_entry(
        correction,
        original_value=correction.get("original_value", ""),
        new_value=correction["proposed_value"],
    ))
    updated_result["change_log"] = change_log

    new_row_plan = build_row_correction_plan(
        corrected_df,
        upload_method,
        template,
        mapping_rows=mapping_rows,
        raw_csv_content=raw_csv_content,
        template_context=template_context,
        source_date_format=source_date_format,
        post_conversion=True,
    )

    updated_validation = dict(validation_bundle or {})
    if template_context is not None:
        picklist_validation = revalidate_picklists_after_corrections(
            corrected_df,
            mapping_rows or [],
            template_context,
        )
        updated_validation["picklist_validation"] = picklist_validation

    if date_field_types:
        updated_result = attach_date_validation_state(
            updated_result,
            date_field_types,
            upload_method,
            source_date_format,
        ) or updated_result

    manual_review = [
        issue for issue in new_row_plan.get("manual_review", [])
        if issue.get("blocking")
    ]
    updated_result["manual_review"] = manual_review

    return {
        "preparation_result": updated_result,
        "validation_bundle": updated_validation,
        "row_correction_plan": new_row_plan,
        "original_df": original_df,
    }


def duplicate_validation_cleared(
    corrected_df: pd.DataFrame,
    field: str,
    edited_row: int,
    new_value: str,
    key_fields: list[str] | None = None,
) -> bool:
    """Return True when duplicate validation no longer flags the edited row."""
    fields = key_fields or ([field] if field else [])
    issues = validate_duplicate_keys(corrected_df, fields)
    for issue in issues:
        rows = parse_duplicate_rows(issue.get("reason", ""))
        if edited_row in rows and normalize_text(issue.get("original_value")) == normalize_text(new_value):
            return False
        if edited_row in rows:
            return False
    return True


def analyze_date_suggestion(
    current_value: str,
    upload_method: str,
    source_format: str | None = None,
    field_type: str = FIELD_TYPE_DATE,
) -> dict[str, Any]:
    analysis = analyze_cell(current_value, source_format, upload_method, field_type)
    status = analysis.get("status")
    return {
        "status": status,
        "suggested_value": analysis.get("converted"),
        "requires_approval": status in {
            STATUS_UNSUPPORTED_TEXT,
            STATUS_EXCEL_SERIAL,
            STATUS_AMBIGUOUS,
            STATUS_INVALID_CALENDAR,
            STATUS_INVALID,
        },
        "target_format": target_date_format(upload_method, field_type),
        "display_status": analysis.get("reason"),
    }
