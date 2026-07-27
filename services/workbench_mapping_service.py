"""Workbench column-to-API mapping proposals, confirmations, and conflict detection."""

from __future__ import annotations

from typing import Any

from core.csv_loader import is_blank_header
from adapters.sfdx_metadata.standard_field_supplements import supplement_object_fields
from services.constants import (
    FORBIDDEN_CSV_HEADERS,
    MAPPING_ACTION_EXCLUDE,
    MAPPING_ACTION_KEEP,
    MAPPING_ACTION_MAP,
    MAPPING_SOURCE_FALLBACK,
    MAPPING_SOURCE_SALESFORCE,
    MAPPING_SOURCE_UNMAPPED,
    MAPPING_SOURCE_USER,
    MAPPING_STATUS_CONFIRMED,
    MAPPING_STATUS_EXACT_API,
    MAPPING_STATUS_EXCLUDED,
    MAPPING_STATUS_INVALID,
    MAPPING_STATUS_NEEDS_CONFIRMATION,
    MAPPING_STATUS_UNMAPPED,
    MAPPING_STATUS_UNRESOLVED,
)
from services.template_service import TemplateContext, get_adapter, resolve_template
from services.workbench_field_catalog_service import get_workbench_field_catalog
from services.workbench_field_matcher import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    FieldMatchCandidate,
    rank_field_candidates,
    select_best_candidate,
)


def is_valid_mapping_row(row: dict[str, Any]) -> bool:
    column = _row_column(row)
    return bool(column) and not is_blank_header(column)


def filter_valid_mapping_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if is_valid_mapping_row(row)]


def build_workbench_mapping_rows(
    uploaded_headers: list[str],
    template_name: str,
    load_operation: str | None = None,
) -> tuple[list[dict[str, Any]], TemplateContext]:
    context = resolve_template(template_name)
    if context is None:
        raise ValueError("No template selected.")

    object_name = context.salesforce_object
    if not object_name:
        raise ValueError(context.metadata_message or "Salesforce object could not be resolved.")

    _options, object_fields, _ = get_workbench_field_catalog(template_name, load_operation)
    api_options = sorted(object_fields.keys())
    rows: list[dict[str, Any]] = []

    seen: set[str] = set()
    for header in uploaded_headers:
        display_header = str(header).strip()
        if is_blank_header(display_header) or display_header in seen:
            continue
        seen.add(display_header)
        rows.append(
            _build_mapping_row(
                display_header,
                object_name,
                object_fields,
                api_options,
                context,
            )
        )

    _attach_collision_flags(rows)
    return rows, context


def _row_column(row: dict) -> str:
    return str(row.get("uploaded_column") or row.get("dit_column") or "").strip()


def apply_mapping_action(
    rows: list[dict],
    uploaded_column: str,
    action: str,
    target_api_field: str | None = None,
) -> None:
    for row in rows:
        if _row_column(row) != uploaded_column:
            continue
        row["action"] = action
        if action == MAPPING_ACTION_EXCLUDE:
            row["confirmed_api_field"] = None
            row["status"] = MAPPING_STATUS_EXCLUDED
            row["resolved"] = True
            row["mapping_source"] = MAPPING_SOURCE_USER
        elif action == MAPPING_ACTION_KEEP:
            exists, error = verify_mapping_field(row.get("salesforce_object"), uploaded_column)
            row["confirmed_api_field"] = uploaded_column if exists else None
            row["exists_on_object"] = exists
            row["validation_error"] = error
            row["status"] = MAPPING_STATUS_EXACT_API if exists else MAPPING_STATUS_INVALID
            row["resolved"] = exists
            row["mapping_source"] = MAPPING_SOURCE_USER
        elif action == MAPPING_ACTION_MAP:
            exists, error = verify_mapping_field(row.get("salesforce_object"), target_api_field)
            row["confirmed_api_field"] = target_api_field
            row["exists_on_object"] = exists
            row["validation_error"] = error
            row["status"] = MAPPING_STATUS_CONFIRMED if exists else MAPPING_STATUS_INVALID
            row["resolved"] = exists
            row["mapping_source"] = MAPPING_SOURCE_USER
        else:
            row["status"] = MAPPING_STATUS_UNRESOLVED
            row["resolved"] = False
        _attach_collision_flags(rows)
        return


def confirm_mapping(rows: list[dict], uploaded_column: str, api_field: str | None) -> None:
    apply_mapping_action(rows, uploaded_column, MAPPING_ACTION_MAP, api_field)


def exclude_mapping(rows: list[dict], uploaded_column: str) -> None:
    apply_mapping_action(rows, uploaded_column, MAPPING_ACTION_EXCLUDE)


def keep_existing_header(rows: list[dict], uploaded_column: str) -> None:
    apply_mapping_action(rows, uploaded_column, MAPPING_ACTION_KEEP)


def confirm_all_high_confidence(rows: list[dict]) -> int:
    count = 0
    for row in rows:
        if row.get("confidence") != CONFIDENCE_HIGH:
            continue
        if row.get("is_ambiguous"):
            continue
        if not row.get("suggested_api_field"):
            continue
        apply_mapping_action(rows, _row_column(row), MAPPING_ACTION_MAP, row["suggested_api_field"])
        if row.get("resolved"):
            count += 1
    return count


def exclude_all_unmapped(rows: list[dict]) -> int:
    count = 0
    for row in rows:
        if row.get("resolved"):
            continue
        apply_mapping_action(rows, _row_column(row), MAPPING_ACTION_EXCLUDE)
        count += 1
    return count


def reset_mappings(
    uploaded_headers: list[str],
    template_name: str,
    load_operation: str | None = None,
) -> list[dict]:
    fresh_rows, _ = build_workbench_mapping_rows(uploaded_headers, template_name, load_operation)
    return fresh_rows


def rows_to_session(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    session: dict[str, dict[str, Any]] = {}
    for row in filter_valid_mapping_rows(rows):
        session[_row_column(row)] = {
            "action": row.get("action"),
            "target": row.get("confirmed_api_field") or row.get("suggested_api_field"),
            "confirmed": bool(row.get("resolved")),
            "status": row.get("status"),
        }
    return session


def apply_session_to_rows(rows: list[dict[str, Any]], session: dict[str, dict[str, Any]]) -> None:
    for row in rows:
        column = _row_column(row)
        saved = session.get(column)
        if not saved:
            continue
        action = saved.get("action")
        target = saved.get("target")
        if action == MAPPING_ACTION_EXCLUDE:
            apply_mapping_action(rows, column, MAPPING_ACTION_EXCLUDE)
        elif action == MAPPING_ACTION_KEEP:
            apply_mapping_action(rows, column, MAPPING_ACTION_KEEP)
        elif action == MAPPING_ACTION_MAP and target:
            apply_mapping_action(rows, column, MAPPING_ACTION_MAP, target)


def detect_target_collisions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    api_to_columns: dict[str, list[str]] = {}
    for row in filter_valid_mapping_rows(rows):
        if row.get("status") == MAPPING_STATUS_EXCLUDED or row.get("action") == MAPPING_ACTION_EXCLUDE:
            continue
        if not _row_is_resolved(row):
            continue
        target = row.get("confirmed_api_field") or (
            _row_column(row) if row.get("action") == MAPPING_ACTION_KEEP else None
        )
        if not target:
            continue
        api_to_columns.setdefault(target, []).append(_row_column(row))

    collisions: list[dict[str, Any]] = []
    for api_field, columns in api_to_columns.items():
        if len(columns) > 1:
            collisions.append({
                "type": "duplicate_api_assignment",
                "api_field": api_field,
                "uploaded_columns": columns,
                "message": (
                    f"Two columns map to {api_field}. Keep one, exclude one, or choose a different field."
                ),
            })
    return collisions


def detect_mapping_collisions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    collisions = detect_target_collisions(rows)
    for row in filter_valid_mapping_rows(rows):
        if row.get("is_ambiguous") and not row.get("resolved"):
            collisions.append({
                "type": "ambiguous_mapping",
                "uploaded_column": _row_column(row),
                "candidate_api_fields": [
                    candidate["api_field"]
                    for candidate in row.get("ranked_candidates", [])
                ],
                "message": (
                    f"Uploaded column `{_row_column(row)}` has multiple equally likely targets."
                ),
            })
    return collisions


def _row_is_resolved(row: dict[str, Any]) -> bool:
    if "resolved" in row:
        return bool(row.get("resolved"))
    return row.get("status") in (
        MAPPING_STATUS_CONFIRMED,
        MAPPING_STATUS_EXACT_API,
        MAPPING_STATUS_EXCLUDED,
    )


def get_mapping_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    valid_rows = filter_valid_mapping_rows(rows)
    resolved = sum(1 for row in valid_rows if _row_is_resolved(row))
    excluded = sum(1 for row in valid_rows if row.get("status") == MAPPING_STATUS_EXCLUDED)
    unresolved = sum(1 for row in valid_rows if not _row_is_resolved(row))
    return {
        "total": len(valid_rows),
        "resolved": resolved,
        "excluded": excluded,
        "unresolved": unresolved,
    }


def mappings_ready_for_preparation(
    rows: list[dict],
    type_confirmed: bool,
    is_account_template: bool,
    template_context: TemplateContext | None = None,
) -> tuple[bool, str]:
    valid_rows = filter_valid_mapping_rows(rows)
    summary = get_mapping_summary(valid_rows)
    if summary["unresolved"]:
        return False, (
            f"{summary['unresolved']} column(s) still unresolved. "
            "Map, keep, or exclude each uploaded column before continuing."
        )

    collisions = detect_mapping_collisions(valid_rows)
    if collisions:
        return False, collisions[0]["message"]

    if is_account_template and not type_confirmed:
        return False, "Confirm the Account Type column before preparing the Workbench file."

    if template_context and not template_context.account_type_valid:
        return False, template_context.account_type_error or "Account.Type metadata error."

    return True, ""


def get_confirmed_rename_map(rows: list[dict]) -> dict[str, str]:
    rename_map: dict[str, str] = {}
    for row in filter_valid_mapping_rows(rows):
        if row.get("status") == MAPPING_STATUS_EXCLUDED or row.get("action") == MAPPING_ACTION_EXCLUDE:
            continue
        if not _row_is_resolved(row):
            continue
        column = _row_column(row)
        if row.get("action") == MAPPING_ACTION_KEEP or row.get("status") == MAPPING_STATUS_EXACT_API:
            if is_valid_api_header(column):
                rename_map[column] = column
            continue
        api_field = row.get("confirmed_api_field")
        if api_field and is_valid_api_header(api_field):
            rename_map[column] = api_field
    return rename_map


def get_excluded_columns(rows: list[dict]) -> set[str]:
    return {
        _row_column(row)
        for row in filter_valid_mapping_rows(rows)
        if row.get("status") == MAPPING_STATUS_EXCLUDED or row.get("action") == MAPPING_ACTION_EXCLUDE
    }


def get_unresolved_rows(rows: list[dict]) -> list[dict]:
    return [row for row in filter_valid_mapping_rows(rows) if not _row_is_resolved(row)]


def get_invalid_rows(rows: list[dict]) -> list[dict]:
    return [row for row in filter_valid_mapping_rows(rows) if row.get("status") == MAPPING_STATUS_INVALID]


def verify_mapping_field(object_name: str, api_field: str | None) -> tuple[bool, str | None]:
    if not api_field:
        return False, None
    if api_field not in supplement_object_fields(object_name, get_adapter().get_object_fields(object_name)):
        return False, f"Field '{api_field}' was not found on Salesforce object '{object_name}'."
    return True, None


def is_valid_api_header(name: str) -> bool:
    if not name or not str(name).strip():
        return False
    upper = str(name).upper()
    if upper in FORBIDDEN_CSV_HEADERS:
        return False
    if str(name).startswith("UNCONFIRMED"):
        return False
    return True


def can_keep_existing_header(header: str, object_name: str) -> bool:
    return verify_mapping_field(object_name, header.strip())[0]


def build_mapping_report(rows: list[dict]) -> dict[str, Any]:
    valid_rows = filter_valid_mapping_rows(rows)
    return {
        "confirmed": [
            {
                "uploaded_column": _row_column(row),
                "api_field": row.get("confirmed_api_field"),
                "action": row.get("action"),
            }
            for row in valid_rows
            if row.get("status") in (MAPPING_STATUS_CONFIRMED, MAPPING_STATUS_EXACT_API)
        ],
        "excluded": [_row_column(row) for row in valid_rows if row.get("status") == MAPPING_STATUS_EXCLUDED],
        "unresolved": [
            {
                "uploaded_column": _row_column(row),
                "status": row.get("status"),
                "action": row.get("action"),
            }
            for row in valid_rows
            if not _row_is_resolved(row)
        ],
    }


def _build_mapping_row(
    header: str,
    object_name: str,
    object_fields: dict[str, Any],
    api_options: list[str],
    context: TemplateContext,
) -> dict[str, Any]:
    ranked = rank_field_candidates(header, object_fields, context)
    best, is_ambiguous = select_best_candidate(ranked, header)
    suggested = best.api_field if best and not is_ambiguous else None
    exact_api_match = header in object_fields and verify_mapping_field(object_name, header)[0]

    if exact_api_match:
        default_action = MAPPING_ACTION_KEEP
        status = MAPPING_STATUS_EXACT_API
        resolved = False
        confirmed_api_field = header
    elif suggested and best and best.confidence == CONFIDENCE_HIGH and not is_ambiguous:
        default_action = MAPPING_ACTION_MAP
        status = MAPPING_STATUS_NEEDS_CONFIRMATION
        resolved = False
        confirmed_api_field = None
    elif suggested and best and best.confidence == CONFIDENCE_MEDIUM and not is_ambiguous:
        default_action = MAPPING_ACTION_MAP
        status = MAPPING_STATUS_NEEDS_CONFIRMATION
        resolved = False
        confirmed_api_field = None
    else:
        default_action = MAPPING_ACTION_EXCLUDE
        status = MAPPING_STATUS_UNRESOLVED
        resolved = False
        confirmed_api_field = None
        suggested = None

    if best and best.match_type == "template_config":
        mapping_source = MAPPING_SOURCE_SALESFORCE
    elif best and best.match_type == "alias":
        mapping_source = MAPPING_SOURCE_FALLBACK
    elif suggested:
        mapping_source = MAPPING_SOURCE_SALESFORCE
    else:
        mapping_source = MAPPING_SOURCE_UNMAPPED

    exists, error = verify_mapping_field(object_name, suggested or (header if exact_api_match else None))
    if suggested and not exists:
        status = MAPPING_STATUS_INVALID
        resolved = False

    return {
        "uploaded_column": header,
        "dit_column": header,
        "display_header": header,
        "action": default_action,
        "suggested_api_field": suggested,
        "confirmed_api_field": confirmed_api_field,
        "field_label": best.field_label if best else (object_fields.get(header).label if exact_api_match else None),
        "field_type": best.field_type if best else (object_fields.get(header).field_type if exact_api_match else None),
        "confidence": best.confidence if best else (CONFIDENCE_HIGH if exact_api_match else None),
        "reason": best.reason if best else ("Exact API field name match" if exact_api_match else None),
        "status": status,
        "resolved": resolved,
        "mapping_source": mapping_source,
        "exists_on_object": exists if (suggested or exact_api_match) else False,
        "validation_error": error,
        "salesforce_object": object_name,
        "api_field_candidates": _candidate_options(ranked, api_options),
        "ranked_candidates": [_candidate_dict(item) for item in ranked[:8]],
        "is_ambiguous": is_ambiguous,
        "can_keep_existing_header": exact_api_match,
        "is_external_id_style": "external id" in header.lstrip("*").lower(),
    }


def _candidate_options(
    ranked: list[FieldMatchCandidate],
    api_options: list[str],
) -> list[str]:
    ordered = [candidate.api_field for candidate in ranked]
    for option in api_options:
        if option not in ordered:
            ordered.append(option)
    return ordered


def _candidate_dict(candidate: FieldMatchCandidate) -> dict[str, Any]:
    return {
        "api_field": candidate.api_field,
        "field_label": candidate.field_label,
        "field_type": candidate.field_type,
        "confidence": candidate.confidence,
        "reason": candidate.reason,
        "score": candidate.score,
    }


def _attach_collision_flags(rows: list[dict]) -> None:
    collisions = detect_mapping_collisions(rows)
    duplicate_columns = {
        column
        for collision in collisions
        if collision["type"] == "duplicate_api_assignment"
        for column in collision["uploaded_columns"]
    }
    ambiguous_columns = {
        collision["uploaded_column"]
        for collision in collisions
        if collision["type"] == "ambiguous_mapping"
    }
    for row in rows:
        column = _row_column(row)
        row["has_duplicate_assignment"] = column in duplicate_columns
        row["is_ambiguous"] = column in ambiguous_columns or row.get("is_ambiguous", False)
