"""Testable helpers for Data Import Tool UX improvements."""

from __future__ import annotations

from typing import Any

from core.config import REQUIREDNESS
from services.constants import (
    PICKLIST_STATUS_BLANK_REQUIRED,
    PICKLIST_STATUS_INVALID,
    PICKLIST_STATUS_METADATA_UNAVAILABLE,
    PICKLIST_STATUS_MULTI_INVALID,
    PICKLIST_STATUS_NEEDS_REVIEW,
    PICKLIST_STATUS_NEEDS_USER_ACTION,
    PICKLIST_STATUS_RECORD_TYPE_FALLBACK,
    PICKLIST_STATUS_VALID,
    PICKLIST_STATUS_WHITESPACE_CLEANUP,
    PREREQ_STATUS_ALREADY_LOADED,
    PREREQ_STATUS_INCLUDED,
    PREREQ_STATUS_NOT_LOADED,
    PREREQ_STATUS_UNKNOWN,
)
from services.picklist_correction_service import is_whitespace_only_picklist_issue
from services.correction_plan_service import get_header_rename_change_ids, get_safe_change_ids
from services.template_service import TemplateContext, resolve_template

SESSION_OPTIONAL_EXCLUSIONS = "dit_optional_exclusions"
SESSION_HEADER_DECISIONS = "dit_header_review_decisions"
SESSION_PICKLIST_FILTER = "picklist_filter_statuses"
SESSION_PICKLIST_BULK = "picklist_bulk_decisions"
SESSION_PICKLIST_INDIVIDUAL = "picklist_individual_mode"
SESSION_PICKLIST_REVIEW_EXPANDED_FIELD = "picklist_review_expanded_field"
SESSION_PREREQ_CONFIRMED = "upload_prerequisites_confirmed"

HEADER_ACTION_KEEP = "Keep Existing Header"
HEADER_ACTION_RENAME = "Accept Suggested Rename"
HEADER_ACTION_EXCLUDE = "Do Not Include"
HEADER_ACTION_ADD_EMPTY = "Add Empty Column"
HEADER_ACTION_SKIP_OPTIONAL = "Skip Optional Column"

REQUIRED_BADGE = "Required"
OPTIONAL_BADGE = "Optional"

DEFAULT_PICKLIST_FILTERS = (
    PICKLIST_STATUS_NEEDS_REVIEW,
    PICKLIST_STATUS_NEEDS_USER_ACTION,
    PICKLIST_STATUS_INVALID,
    PICKLIST_STATUS_MULTI_INVALID,
)

PICKLIST_SUMMARY_LABELS = {
    PICKLIST_STATUS_VALID: "Valid",
    PICKLIST_STATUS_NEEDS_REVIEW: "Needs Review",
    PICKLIST_STATUS_NEEDS_USER_ACTION: "Needs User Action",
    PICKLIST_STATUS_INVALID: "Needs User Action",
    PICKLIST_STATUS_MULTI_INVALID: "Needs User Action",
    PICKLIST_STATUS_BLANK_REQUIRED: "Needs User Action",
    PICKLIST_STATUS_WHITESPACE_CLEANUP: "Needs Review",
    PICKLIST_STATUS_METADATA_UNAVAILABLE: "Not Checked",
    PICKLIST_STATUS_RECORD_TYPE_FALLBACK: "Needs Review",
}

_PICKLIST_NEEDS_CORRECTION_STATUSES = {
    PICKLIST_STATUS_NEEDS_USER_ACTION,
    PICKLIST_STATUS_INVALID,
    PICKLIST_STATUS_MULTI_INVALID,
    PICKLIST_STATUS_NEEDS_REVIEW,
    PICKLIST_STATUS_BLANK_REQUIRED,
}

PREREQ_UI_LABELS = {
    PREREQ_STATUS_ALREADY_LOADED: "Confirmed Uploaded",
    PREREQ_STATUS_INCLUDED: "Confirmed Uploaded",
    PREREQ_STATUS_NOT_LOADED: "Not Uploaded",
    PREREQ_STATUS_UNKNOWN: "Unknown",
}

PREREQ_UI_ICONS = {
    PREREQ_STATUS_ALREADY_LOADED: "✅",
    PREREQ_STATUS_INCLUDED: "✅",
    PREREQ_STATUS_NOT_LOADED: "🔴",
    PREREQ_STATUS_UNKNOWN: "⚪",
}


def is_required_dit_header(header: str, template_context: TemplateContext | None = None) -> bool:
    """Return True when a DIT template header is required (* prefix or metadata)."""
    if header.startswith("*"):
        return True
    if template_context and template_context.template_definition:
        return header in template_context.template_definition.required_csv_labels
    if template_context and template_context.fallback_config:
        for label, cfg in template_context.fallback_config.get("column_mappings", {}).items():
            if label == header and label.startswith("*") and cfg.get("suggested_api_field"):
                return True
    return False


def requiredness_badge(header: str, template_context: TemplateContext | None = None) -> str:
    return REQUIRED_BADGE if is_required_dit_header(header, template_context) else OPTIONAL_BADGE


def available_header_actions(
    *,
    required: bool,
    has_rename: bool,
    is_extra: bool,
    is_missing_optional: bool = False,
) -> list[str]:
    if is_missing_optional:
        return [HEADER_ACTION_ADD_EMPTY, HEADER_ACTION_SKIP_OPTIONAL]
    if is_extra:
        if required:
            return [HEADER_ACTION_KEEP]
        return [HEADER_ACTION_KEEP, HEADER_ACTION_EXCLUDE]
    actions = [HEADER_ACTION_KEEP]
    if has_rename:
        actions.append(HEADER_ACTION_RENAME)
    if not required:
        actions.append(HEADER_ACTION_EXCLUDE)
    return actions


def build_dit_header_review_rows(
    correction_plan: dict[str, Any],
    template_context: TemplateContext | None = None,
    optional_exclusions: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Build per-column header review rows for the DIT Header Review UI."""
    optional_exclusions = optional_exclusions or set()
    rows: list[dict[str, Any]] = []
    seen_uploaded: set[str] = set()

    for rename in correction_plan.get("proposed_renames", []):
        source = rename["source_column"]
        target = rename["target_column"]
        seen_uploaded.add(source)
        required = is_required_dit_header(target, template_context)
        rows.append({
            "uploaded_header": source,
            "target_header": target,
            "requiredness": requiredness_badge(target, template_context),
            "required": required,
            "confidence": rename.get("confidence", "—"),
            "reason": rename.get(
                "description",
                f"{rename.get('match_type', 'match')} match to template header",
            ),
            "actions": available_header_actions(required=required, has_rename=True, is_extra=False),
            "default_action": HEADER_ACTION_RENAME,
            "status": "Suggested",
            "change_id": f"rename:{source}->{target}",
            "category": "rename",
        })

    comparison = (correction_plan.get("comparison_result") or {}).get("comparison", {})
    for header in comparison.get("matching_headers", []):
        if header in seen_uploaded:
            continue
        required = is_required_dit_header(header, template_context)
        rows.append({
            "uploaded_header": header,
            "target_header": header,
            "requiredness": requiredness_badge(header, template_context),
            "required": required,
            "confidence": "High",
            "reason": "Exact template header match",
            "actions": available_header_actions(required=required, has_rename=False, is_extra=False),
            "default_action": HEADER_ACTION_KEEP,
            "status": "Confirmed",
            "change_id": None,
            "category": "match",
        })
        seen_uploaded.add(header)

    for change in correction_plan.get("changes", []):
        if change.get("category") != "exclude_extra_column":
            continue
        source = change.get("source_column")
        if not source or source in seen_uploaded:
            continue
        required = is_required_dit_header(source, template_context)
        default_action = HEADER_ACTION_EXCLUDE if not required else HEADER_ACTION_KEEP
        if source in optional_exclusions:
            default_action = HEADER_ACTION_EXCLUDE
        rows.append({
            "uploaded_header": source,
            "target_header": "—",
            "requiredness": requiredness_badge(source, template_context),
            "required": required,
            "confidence": "—",
            "reason": change.get("description", "Unsupported extra column"),
            "actions": available_header_actions(required=required, has_rename=False, is_extra=True),
            "default_action": default_action,
            "status": "Excluded" if default_action == HEADER_ACTION_EXCLUDE else "Needs Action",
            "change_id": change.get("change_id"),
            "category": "exclude_extra_column",
        })
        seen_uploaded.add(source)

    for target in comparison.get("missing_columns", []):
        required = is_required_dit_header(target, template_context)
        rows.append({
            "uploaded_header": "—",
            "target_header": target,
            "requiredness": requiredness_badge(target, template_context),
            "required": required,
            "confidence": "—",
            "reason": f"Required template column '{target}' is missing from the upload.",
            "actions": [HEADER_ACTION_KEEP] if required else [HEADER_ACTION_ADD_EMPTY],
            "default_action": HEADER_ACTION_KEEP,
            "status": "Missing Required" if required else "Missing",
            "change_id": f"missing:{target}",
            "category": "required_data_missing",
        })

    for target in comparison.get("optional_missing_columns", []):
        rows.append({
            "uploaded_header": "—",
            "target_header": target,
            "requiredness": OPTIONAL_BADGE,
            "required": False,
            "confidence": "—",
            "reason": f"Optional template column '{target}' is not present in the upload.",
            "actions": available_header_actions(
                required=False,
                has_rename=False,
                is_extra=False,
                is_missing_optional=True,
            ),
            "default_action": HEADER_ACTION_SKIP_OPTIONAL,
            "status": "Optional Missing",
            "change_id": f"empty:{target}",
            "category": "add_empty_optional_column",
        })

    return rows


def resolve_header_decisions_to_change_ids(
    correction_plan: dict[str, Any],
    row_decisions: dict[str, str],
    optional_exclusions: set[str] | None = None,
) -> set[str]:
    """Convert per-row header actions into enabled correction-plan change IDs."""
    optional_exclusions = optional_exclusions or set()
    enabled: set[str] = set()
    changes_by_id = {
        change["change_id"]: change
        for change in correction_plan.get("changes", [])
    }

    for row in build_dit_header_review_rows(
        correction_plan,
        optional_exclusions=optional_exclusions,
    ):
        uploaded = row.get("uploaded_header") or ""
        target = row.get("target_header") or ""
        key = uploaded if uploaded != "—" else target
        action = row_decisions.get(key, row.get("default_action"))

        if action == HEADER_ACTION_RENAME and row.get("change_id"):
            enabled.add(row["change_id"])
        elif action == HEADER_ACTION_EXCLUDE and row.get("change_id"):
            enabled.add(row["change_id"])
        elif action == HEADER_ACTION_ADD_EMPTY and row.get("change_id"):
            enabled.add(row["change_id"])
        elif action == HEADER_ACTION_SKIP_OPTIONAL:
            continue
        elif action == HEADER_ACTION_KEEP and row.get("category") == "match":
            continue

    for change in correction_plan.get("changes", []):
        if change.get("category") == "reorder_columns" and change.get("safe"):
            enabled.add(change["change_id"])

    return enabled


def approve_all_high_confidence_headers(correction_plan: dict[str, Any]) -> set[str]:
    enabled = set(get_header_rename_change_ids(correction_plan))
    enabled.update(get_safe_change_ids(correction_plan))
    return enabled


def exclude_all_optional_unmapped(
    correction_plan: dict[str, Any],
    template_context: TemplateContext | None = None,
) -> set[str]:
    enabled = set(get_header_rename_change_ids(correction_plan))
    for change in correction_plan.get("changes", []):
        if change.get("category") != "exclude_extra_column":
            continue
        source = change.get("source_column")
        if source and not is_required_dit_header(source, template_context):
            enabled.add(change["change_id"])
    return enabled


def format_reorder_message(template: str, count: int = 1) -> str:
    if count <= 0:
        return ""
    suffix = "" if count == 1 else f" ({count} column order adjustment(s))"
    return (
        f"Column order will be updated to match the {template} template{suffix}."
    )


def build_structure_change_lines(summary: dict[str, int], template: str) -> list[str]:
    lines: list[str] = []
    rename_count = summary.get("rename", 0)
    if rename_count:
        lines.append(f"Rename headers: **{rename_count}**")
    reorder_count = summary.get("reorder_columns", 0)
    if reorder_count:
        lines.append(format_reorder_message(template, reorder_count))
    generated_count = summary.get("add_generated_value", 0)
    if generated_count:
        lines.append(f"Add generated values: **{generated_count}**")
    optional_count = summary.get("add_empty_optional_column", 0)
    if optional_count:
        lines.append(f"Add optional blank columns: **{optional_count}**")
    exclude_count = summary.get("exclude_extra_column", 0)
    if exclude_count:
        lines.append(f"Exclude unsupported columns: **{exclude_count}**")
    return lines


def optional_exclusions_block_readiness(
    correction_plan: dict[str, Any] | None,
    enabled_change_ids: set[str] | None = None,
) -> bool:
    """Excluded optional columns must NOT block template readiness."""
    if not correction_plan:
        return False
    enabled_change_ids = enabled_change_ids or set()
    for change in correction_plan.get("changes", []):
        if change.get("category") != "exclude_extra_column":
            continue
        if change["change_id"] not in enabled_change_ids:
            continue
        if change.get("requiredness") == REQUIREDNESS["OPTIONAL"]:
            continue
        if is_required_dit_header(change.get("source_column", "")):
            return True
    blocking_manual = [
        item for item in correction_plan.get("manual_review", [])
        if item.get("category") in {"required_data_missing", "manual_mapping_required"}
    ]
    unresolved_required = [
        item for item in blocking_manual
        if item.get("category") == "required_data_missing"
        and not _manual_issue_enabled(item, enabled_change_ids, correction_plan)
    ]
    return bool(unresolved_required)


def _manual_issue_enabled(
    issue: dict[str, Any],
    enabled_change_ids: set[str],
    correction_plan: dict[str, Any],
) -> bool:
    target = issue.get("target_column")
    if not target:
        return False
    for change in correction_plan.get("changes", []):
        if change.get("target_column") != target:
            continue
        if change["change_id"] in enabled_change_ids:
            return change["category"] != "required_data_missing"
    return False


def build_picklist_status_summary(picklist_validation: dict[str, Any]) -> dict[str, int]:
    counts = {
        "Valid": 0,
        "Needs Review": 0,
        "Needs User Action": 0,
        "Not Checked": 0,
    }
    for issue in picklist_validation.get("issues", []):
        label = PICKLIST_SUMMARY_LABELS.get(issue.get("status"), "Not Checked")
        if label == "Needs User Action":
            counts["Needs User Action"] += 1
        elif label == "Needs Review":
            counts["Needs Review"] += 1
        elif label == "Valid":
            counts["Valid"] += 1
        else:
            counts["Not Checked"] += 1

    for summary in picklist_validation.get("field_summaries", []):
        if summary.get("invalid_row_count"):
            continue
        if summary.get("blank_required_row_count"):
            continue
        if summary.get("valid_row_count"):
            counts["Valid"] += 1
    return counts


def build_picklist_column_summary_lines(picklist_validation: dict[str, Any]) -> list[str]:
    """Build per-column picklist summary lines for the review UI."""
    issues_by_field: dict[str, set[int]] = {}
    for issue in picklist_validation.get("issues", []):
        if issue.get("status") not in _PICKLIST_NEEDS_CORRECTION_STATUSES:
            continue
        api_field = issue.get("salesforce_api_field")
        row = issue.get("row")
        if api_field and row is not None:
            issues_by_field.setdefault(api_field, set()).add(row)

    lines: list[str] = []
    for summary in picklist_validation.get("field_summaries", []):
        friendly = summary.get("uploaded_column") or summary.get("salesforce_field") or "Field"
        api_field = summary.get("salesforce_field")
        valid_count = summary.get("valid_row_count", 0)
        needs_correction = len(issues_by_field.get(api_field, set()))
        if needs_correction == 0:
            lines.append(f"{friendly} - All values valid")
        elif needs_correction == 1:
            lines.append(f"{friendly} - 1 value needs correction")
        else:
            lines.append(f"{friendly} - {valid_count} valid, {needs_correction} need correction")
    return lines


def filter_picklist_issues(
    issues: list[dict[str, Any]],
    statuses: set[str] | None = None,
) -> list[dict[str, Any]]:
    statuses = statuses or set(DEFAULT_PICKLIST_FILTERS)
    return [issue for issue in issues if issue.get("status") in statuses]


def build_picklist_review_rows(picklist_validation: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    allowed_by_field = {
        item.get("salesforce_field"): item.get("allowed_values") or []
        for item in picklist_validation.get("field_summaries", [])
        if item.get("allowed_values") is not None
    }
    for issue in picklist_validation.get("issues", []):
        if issue.get("status") == PICKLIST_STATUS_VALID:
            continue
        api_field = issue.get("salesforce_api_field")
        allowed = issue.get("allowed_values") or allowed_by_field.get(api_field, [])
        status = issue.get("status")
        if status in {
            PICKLIST_STATUS_NEEDS_USER_ACTION,
            PICKLIST_STATUS_INVALID,
            PICKLIST_STATUS_MULTI_INVALID,
        }:
            problem = "This value is not configured for this Salesforce picklist."
            title = "Picklist value needs correction"
        elif is_whitespace_only_picklist_issue(issue):
            problem = issue.get("reason") or "Whitespace trim suggested."
            title = "Whitespace trim suggested"
        else:
            problem = issue.get("reason") or issue.get("status")
            title = issue.get("status")
        rows.append({
            "row": issue.get("row"),
            "friendly_column": issue.get("uploaded_column"),
            "api_field": api_field,
            "uploaded_value": issue.get("uploaded_value"),
            "allowed_values": allowed,
            "allowed_values_display": ", ".join(allowed) if allowed else "—",
            "problem": problem,
            "title": title,
            "suggested_correction": issue.get("suggested_replacement") if is_whitespace_only_picklist_issue(issue) else "—",
            "status": status,
            "issue_id": issue.get("issue_id"),
        })
    return rows


def _picklist_field_status_icon(statuses: set[str]) -> str:
    blocking = {
        PICKLIST_STATUS_NEEDS_USER_ACTION,
        PICKLIST_STATUS_INVALID,
        PICKLIST_STATUS_MULTI_INVALID,
        PICKLIST_STATUS_BLANK_REQUIRED,
    }
    if statuses & blocking:
        return "🔴"
    if PICKLIST_STATUS_NEEDS_REVIEW in statuses or PICKLIST_STATUS_WHITESPACE_CLEANUP in statuses:
        return "🟡"
    return "🟢"


def build_picklist_field_groups(
    picklist_validation: dict[str, Any],
    correctable: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Group picklist corrections by field for summary display."""
    correctable = correctable or []
    field_summaries = {
        item.get("salesforce_field"): item
        for item in picklist_validation.get("field_summaries", [])
    }
    allowed_by_field: dict[str, list[str]] = {}
    for issue in picklist_validation.get("issues", []):
        api_field = issue.get("salesforce_api_field")
        if api_field and issue.get("allowed_values") and api_field not in allowed_by_field:
            allowed_by_field[api_field] = issue["allowed_values"]

    grouped: dict[str, list[dict[str, Any]]] = {}
    for correction in correctable:
        api_field = correction.get("salesforce_api_field") or ""
        grouped.setdefault(api_field, []).append(correction)

    results: list[dict[str, Any]] = []
    for api_field, corrections in grouped.items():
        summary = field_summaries.get(api_field, {})
        friendly = (
            summary.get("uploaded_column")
            or corrections[0].get("uploaded_column")
            or corrections[0].get("friendly_column")
            or api_field
        )
        statuses = {item.get("status") for item in corrections if item.get("status")}
        rows_affected = len({item.get("row") for item in corrections if item.get("row") is not None})
        allowed = corrections[0].get("allowed_values") or allowed_by_field.get(api_field, [])
        whitespace_only = all(item.get("is_whitespace_trim") for item in corrections)
        suggested = next((item for item in corrections if item.get("is_whitespace_trim")), None)
        suggested_example = None
        if suggested and suggested.get("proposed_value"):
            uploaded = suggested.get("uploaded_value") or suggested.get("original_value") or ""
            proposed = suggested.get("proposed_value") or ""
            suggested_example = f'"{uploaded}" → "{proposed}"'

        results.append({
            "friendly_column": friendly,
            "salesforce_field": api_field,
            "status_icon": _picklist_field_status_icon(statuses),
            "affected_rows": rows_affected,
            "allowed_values": allowed,
            "suggested_example": suggested_example,
            "whitespace_only": whitespace_only,
            "corrections": corrections,
        })

    results.sort(key=lambda item: str(item["friendly_column"]))
    return results


def picklist_review_row_index_key(salesforce_field: str) -> str:
    safe_field = salesforce_field.replace(".", "_")
    return f"picklist_review_current_row_index_{safe_field}"


def count_reviewable_picklist_corrections(corrections: list[dict[str, Any]]) -> int:
    """Count non-whitespace picklist rows that require manual review."""
    return len([
        correction for correction in corrections
        if not correction.get("is_whitespace_trim")
    ])


def build_picklist_review_button_label(invalid_count: int) -> str:
    if invalid_count == 1:
        return "Review 1 Value"
    return f"Review {invalid_count} Values"


def set_picklist_review_expanded_field(
    session_state: dict[str, Any],
    salesforce_field: str,
) -> None:
    """Open inline picklist review for one field (accordion: one at a time)."""
    for key in list(session_state):
        if key.startswith("picklist_review_current_row_index_"):
            session_state.pop(key, None)
    session_state[SESSION_PICKLIST_REVIEW_EXPANDED_FIELD] = salesforce_field
    session_state[picklist_review_row_index_key(salesforce_field)] = 0


def advance_picklist_review_after_save(
    session_state: dict[str, Any],
    salesforce_field: str,
    *,
    remaining_invalid_count: int,
) -> None:
    """Keep accordion open and reset row index, or collapse when resolved."""
    row_index_key = picklist_review_row_index_key(salesforce_field)
    if remaining_invalid_count > 0:
        session_state[SESSION_PICKLIST_REVIEW_EXPANDED_FIELD] = salesforce_field
        session_state[row_index_key] = 0
        return
    session_state.pop(SESSION_PICKLIST_REVIEW_EXPANDED_FIELD, None)
    session_state.pop(row_index_key, None)


def resolve_picklist_review_row_index(
    invalid_corrections: list[dict[str, Any]],
    row_index: int,
) -> tuple[dict[str, Any] | None, int]:
    """Return the active invalid correction and a safe row index."""
    if not invalid_corrections:
        return None, 0
    safe_index = row_index if 0 <= row_index < len(invalid_corrections) else 0
    return invalid_corrections[safe_index], safe_index


def group_repeated_whitespace_trims(
    corrections: list[dict[str, Any]],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Group repeated whitespace-trim corrections for safe bulk apply."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for correction in corrections:
        if not correction.get("is_whitespace_trim"):
            continue
        key = (
            correction.get("salesforce_api_field") or "",
            str(correction.get("uploaded_value") or ""),
        )
        groups.setdefault(key, []).append(correction)
    return groups


def group_repeated_picklist_mismatches(
    corrections: list[dict[str, Any]],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Backward-compatible alias for whitespace-trim bulk grouping."""
    return group_repeated_whitespace_trims(corrections)


def apply_bulk_picklist_decision(
    corrections: list[dict[str, Any]],
    bulk_decisions: dict[str, str],
) -> list[dict[str, Any]]:
    approved: list[dict[str, Any]] = []
    for correction in corrections:
        correction_id = correction.get("correction_id")
        selected = bulk_decisions.get(correction_id)
        if selected and selected != "Keep for Manual Review":
            approved.append({**correction, "proposed_value": selected})
    return approved


def build_template_readiness_summary(
    *,
    correction_plan: dict[str, Any] | None,
    picklist_validation: dict[str, Any] | None,
    prerequisite_status: dict[str, str] | None,
    upload_order_plan: dict[str, Any] | None,
    enabled_change_ids: set[str] | None = None,
    picklist_corrections_applied: int = 0,
    template: str = "",
) -> dict[str, Any]:
    correction_plan = correction_plan or {}
    comparison = (correction_plan.get("comparison_result") or {}).get("comparison", {})
    target_headers = correction_plan.get("target_headers") or []
    required_total = sum(
        1 for header in target_headers if is_required_dit_header(header)
    )
    required_present = sum(
        1 for header in comparison.get("matching_headers", [])
        if is_required_dit_header(header)
    )
    required_present += sum(
        1 for rename in comparison.get("proposed_renames", [])
        if is_required_dit_header(rename.get("target_column", ""))
    )
    optional_total = max(len(target_headers) - required_total, 0)
    optional_missing = len(comparison.get("optional_missing_columns", []))
    optional_included = max(optional_total - optional_missing, 0)
    optional_excluded = sum(
        1 for change in correction_plan.get("changes", [])
        if change.get("category") == "exclude_extra_column"
        and change.get("change_id") in (enabled_change_ids or set())
    )

    picklist_summary = build_picklist_status_summary(picklist_validation or {})
    prereq_status = prerequisite_status or {}
    unresolved_prereqs = [
        template_name
        for template_name, status in prereq_status.items()
        if status in {PREREQ_STATUS_NOT_LOADED, PREREQ_STATUS_UNKNOWN}
    ]

    next_action = "Review headers and approve structural changes."
    if optional_exclusions_block_readiness(correction_plan, enabled_change_ids):
        next_action = "Resolve missing required template columns."
    elif picklist_summary.get("Needs User Action") or picklist_summary.get("Needs Review"):
        next_action = "Review and approve picklist corrections."
    elif unresolved_prereqs:
        next_action = "Confirm prerequisite upload status."
    elif correction_plan.get("has_fixable_changes") and not correction_plan.get("corrections_applied"):
        next_action = "Approve header review changes to continue."

    return {
        "required_present": required_present,
        "required_total": required_total,
        "optional_included": optional_included,
        "optional_excluded": optional_excluded,
        "optional_missing": optional_missing,
        "picklist_summary": picklist_summary,
        "picklist_corrections_applied": picklist_corrections_applied,
        "prerequisites_confirmed": all(
            status in {PREREQ_STATUS_ALREADY_LOADED, PREREQ_STATUS_INCLUDED}
            for status in prereq_status.values()
        ) if prereq_status else True,
        "unresolved_prerequisites": unresolved_prereqs,
        "next_action": next_action,
        "template": template or correction_plan.get("template", ""),
        "upload_order_message": (upload_order_plan or {}).get("message"),
    }


def evaluate_prerequisite_gate(
    dependencies: list[dict[str, Any]],
    prerequisite_status: dict[str, str],
    confirmed: bool,
) -> tuple[bool, str]:
    if not dependencies:
        return True, ""
    unresolved = []
    for dep in dependencies:
        template_name = dep.get("template")
        if not template_name:
            continue
        status = prerequisite_status.get(template_name, PREREQ_STATUS_UNKNOWN)
        if status == PREREQ_STATUS_NOT_LOADED:
            unresolved.append(template_name)
        elif status == PREREQ_STATUS_UNKNOWN:
            unresolved.append(template_name)
    if unresolved and not confirmed:
        return False, (
            "Confirm whether required prerequisite files have already been uploaded "
            f"({', '.join(unresolved)})."
        )
    if unresolved and confirmed:
        return True, (
            "Continuing with unresolved prerequisites — verify parent data is available before upload."
        )
    if not confirmed and dependencies:
        return False, "Check the box to confirm required prerequisite files have already been uploaded."
    return True, ""


def resolve_template_context(template: str) -> TemplateContext | None:
    try:
        return resolve_template(template)
    except (FileNotFoundError, ValueError):
        return None
