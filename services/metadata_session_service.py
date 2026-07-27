"""Session metadata version lock and stale validation invalidation."""

from __future__ import annotations

from typing import Any

METADATA_VERSION_KEY = "metadata_version"
SESSION_METADATA_CHANGE_SUMMARY = "metadata_change_summary"
SESSION_METADATA_REFRESH_PENDING = "metadata_refresh_pending"
SESSION_LAST_REFRESH_RESULT = "metadata_last_refresh_result"

METADATA_VERSION_WARNING = (
    "A newer Salesforce metadata version is available. Finish the current file using "
    "the existing version or restart validation using the new version."
)

METADATA_DEPENDENT_SESSION_KEYS = (
    "mapping_rows",
    "type_confirmed",
    "formatting_review",
    "preparation_result",
    "validation_bundle",
    "last_comparison",
    "correction_plan",
    "row_correction_plan",
    "workbench_preparation_plan",
    "workbench_mappings",
    "mapped_df",
    "proposed_df",
    "header_review_complete",
    "header_enabled_change_ids",
    "mapping_preparation_started",
    "picklist_correction_plan",
    "source_date_format",
    "date_conversion_plan",
    "date_conversions_approved",
    "upload_prerequisites",
)


def metadata_version_changed(
    locked_hash: str | None,
    current_hash: str | None,
) -> bool:
    """Return True when the active session metadata version differs from current."""
    return bool(locked_hash and current_hash and locked_hash != current_hash)


def session_has_uploaded_file(session_state: dict[str, Any]) -> bool:
    """Return True when a CSV upload session is active."""
    return bool(session_state.get("original_df") is not None)


def invalidate_metadata_dependent_session_state(session_state: dict[str, Any]) -> None:
    """Clear cached validation and mapping decisions that depend on metadata."""
    for key in METADATA_DEPENDENT_SESSION_KEYS:
        session_state.pop(key, None)


def apply_new_metadata_version(
    session_state: dict[str, Any],
    commit_hash: str | None,
) -> None:
    """Adopt a refreshed metadata version and discard stale validation state."""
    session_state[METADATA_VERSION_KEY] = commit_hash
    invalidate_metadata_dependent_session_state(session_state)
    session_state.pop(SESSION_METADATA_REFRESH_PENDING, None)
    session_state.pop(SESSION_METADATA_CHANGE_SUMMARY, None)
    session_state.pop(SESSION_LAST_REFRESH_RESULT, None)


def mark_metadata_refresh_pending(
    session_state: dict[str, Any],
    *,
    change_summary: dict[str, Any] | None,
    refresh_result: dict[str, Any] | None,
) -> None:
    """Flag that metadata changed while a file session may be active."""
    session_state[SESSION_METADATA_REFRESH_PENDING] = True
    if change_summary is not None:
        session_state[SESSION_METADATA_CHANGE_SUMMARY] = change_summary
    if refresh_result is not None:
        session_state[SESSION_LAST_REFRESH_RESULT] = refresh_result
