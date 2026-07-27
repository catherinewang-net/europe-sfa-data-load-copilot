"""Metadata source panel — shows the active validation provider (live org or snapshot)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

from core.config import (
    is_bundled_metadata_mode,
    is_git_metadata_sync_enabled,
    metadata_source_label,
    resolve_metadata_repo_path,
)
from services.git_repository_service import (
    GitPullResult,
    SyncStatus,
    fetch_remote_updates,
    find_git_root,
    get_repository_status,
    pull_fast_forward_only,
)
from services.metadata_refresh_service import (
    MetadataHealth,
    MetadataRefreshResult,
    get_metadata_health,
    is_metadata_connected,
    refresh_metadata,
    serialize_change_summary,
    serialize_refresh_result,
)
from services.metadata_session_service import (
    METADATA_VERSION_KEY,
    METADATA_VERSION_WARNING,
    SESSION_LAST_REFRESH_RESULT,
    SESSION_METADATA_CHANGE_SUMMARY,
    SESSION_METADATA_REFRESH_PENDING,
    apply_new_metadata_version,
    mark_metadata_refresh_pending,
    metadata_version_changed,
    session_has_uploaded_file,
)
from services.revalidation_service import clear_stale_metadata_validation
from services.salesforce_oauth_service import get_connection_info, is_connected

SESSION_LAST_REFRESHED = "metadata_last_refreshed"
SESSION_UPDATES_AVAILABLE = "metadata_updates_available"
SESSION_GIT_STATUS = "metadata_git_status_snapshot"
SESSION_PULL_PREVIOUS_COMMIT = "metadata_pull_previous_commit"
SESSION_REFRESH_FEEDBACK = "metadata_refresh_feedback"

SNAPSHOT_UNAVAILABLE_MESSAGE = (
    "The approved metadata snapshot is missing or could not be loaded. "
    "Contact the platform team if this persists."
)
SNAPSHOT_ACTIVE_MESSAGE = (
    "The Copilot is currently using a read-only metadata snapshot. "
    "Connect Salesforce for live validation against your org."
)
SNAPSHOT_REFRESH_CAPTION = (
    "Reload the approved metadata snapshot used for field and picklist validation."
)
LIVE_ACTIVE_CAPTION = (
    "Field and picklist validation use your connected Salesforce org. "
    "Template CSV mappings still use the approved snapshot."
)
SNAPSHOT_REFRESH_SUCCESS = "Approved metadata snapshot refreshed."
SNAPSHOT_REFRESH_FAILED = (
    "Could not refresh the approved metadata snapshot. "
    "Validation may be unavailable until the snapshot is restored."
)


def _metadata_repo_path() -> Path:
    return resolve_metadata_repo_path()


def _format_timestamp(value: datetime | str | None) -> str:
    if value is None:
        return "Not refreshed this session"
    if isinstance(value, str):
        return value
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _status_badge(sync_status: SyncStatus) -> str:
    return sync_status.value


def _format_count_delta(previous: int | None, current: int) -> str:
    if previous is None:
        return str(current)
    delta = current - previous
    if delta == 0:
        return str(current)
    sign = "+" if delta > 0 else ""
    return f"{current} ({sign}{delta})"


def format_snapshot_version(health: MetadataHealth) -> str:
    """Return a user-facing snapshot version label (commit hash or bundled date)."""
    git_status = health.git_status
    if git_status.commit_hash_short and git_status.last_commit_date:
        date_part = git_status.last_commit_date[:10]
        return f"{git_status.commit_hash_short} ({date_part})"
    if git_status.commit_hash_short:
        return git_status.commit_hash_short

    manifest_path = health.repo_path / "SNAPSHOT_MANIFEST.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
        commit_hash = manifest.get("commit_hash")
        if commit_hash:
            return str(commit_hash)[:12]
        bundled_at = manifest.get("bundled_at_utc") or manifest.get("commit_date")
        if bundled_at:
            return str(bundled_at)[:10]
    return "—"


def _snapshot_badge_html(available: bool) -> str:
    if available:
        return (
            '<div class="metadata-status-badge metadata-status-connected" role="status">'
            '<span class="metadata-status-icon" aria-hidden="true">📦</span>'
            '<span class="metadata-status-label">Snapshot available</span>'
            "</div>"
        )
    return (
        '<div class="metadata-status-badge metadata-status-disconnected" role="status">'
        '<span class="metadata-status-icon" aria-hidden="true">⚠️</span>'
        '<span class="metadata-status-label">Snapshot unavailable</span>'
        "</div>"
    )


def _live_badge_html() -> str:
    return (
        '<div class="metadata-status-badge metadata-status-connected" role="status">'
        '<span class="metadata-status-icon" aria-hidden="true">☁️</span>'
        '<span class="metadata-status-label">Active validation source</span>'
        "</div>"
    )


def _handle_refresh_result(result: MetadataRefreshResult) -> None:
    st.session_state[SESSION_LAST_REFRESHED] = result.refreshed_at
    st.session_state[SESSION_LAST_REFRESH_RESULT] = serialize_refresh_result(result)

    locked_hash = st.session_state.get(METADATA_VERSION_KEY)
    if session_has_uploaded_file(st.session_state) and metadata_version_changed(
        locked_hash,
        result.commit_hash,
    ):
        clear_stale_metadata_validation(st.session_state)
        mark_metadata_refresh_pending(
            st.session_state,
            change_summary=serialize_change_summary(result.change_summary),
            refresh_result=serialize_refresh_result(result),
        )
    elif result.change_summary and result.change_summary.has_changes:
        st.session_state[SESSION_METADATA_CHANGE_SUMMARY] = serialize_change_summary(
            result.change_summary
        )


def _render_business_refresh_feedback(*, success: bool) -> None:
    st.session_state[SESSION_REFRESH_FEEDBACK] = "success" if success else "failed"


def _render_persisted_refresh_feedback() -> None:
    feedback = st.session_state.pop(SESSION_REFRESH_FEEDBACK, None)
    if feedback == "success":
        st.success(SNAPSHOT_REFRESH_SUCCESS)
    elif feedback == "failed":
        st.warning(SNAPSHOT_REFRESH_FAILED)


def render_metadata_source_panel() -> dict[str, Any]:
    """
    Render the metadata source panel for the active validation provider.

    When OAuth is connected, live org metadata is active and the snapshot is inactive.
    Otherwise the approved snapshot is the active provider.
    """
    live_connected = is_connected(st.session_state)
    bundled = is_bundled_metadata_mode()
    repo_path = _metadata_repo_path()
    health = get_metadata_health(repo_path)

    st.subheader("Metadata Source")

    if live_connected:
        return _render_live_metadata_source_panel(health, bundled=bundled)

    return _render_snapshot_metadata_source_panel(health, bundled=bundled)


def _render_live_metadata_source_panel(
    health: MetadataHealth,
    *,
    bundled: bool,
) -> dict[str, Any]:
    info = get_connection_info(st.session_state)
    refreshed_at = info.metadata_refreshed_at if info else None

    with st.container(border=True):
        st.markdown(_live_badge_html(), unsafe_allow_html=True)
        st.markdown(f"**{metadata_source_label(live_connected=True)}**")
        st.markdown(
            f"Metadata was last refreshed: **{_format_timestamp(refreshed_at)}**"
        )
        st.caption(LIVE_ACTIVE_CAPTION)

    _render_developer_expander(health, bundled=bundled, live_connected=True)

    return {
        "commit_hash": None,
        "commit_hash_short": None,
        "adapter_status": "live-oauth",
        "sync_status": "live",
        "metadata_last_refreshed": refreshed_at,
        "connected": True,
        "metadata_mode": "live",
    }


def _render_snapshot_metadata_source_panel(
    health: MetadataHealth,
    *,
    bundled: bool,
) -> dict[str, Any]:
    git_status = health.git_status
    snapshot_available = is_metadata_connected(health)
    last_refreshed = st.session_state.get(SESSION_LAST_REFRESHED)
    snapshot_version = format_snapshot_version(health)

    with st.container(border=True):
        st.markdown(
            _snapshot_badge_html(snapshot_available),
            unsafe_allow_html=True,
        )
        st.markdown(f"**{metadata_source_label(live_connected=False)}**")

        if snapshot_available:
            st.markdown(SNAPSHOT_ACTIVE_MESSAGE)
            st.markdown(f"**Snapshot version:** {snapshot_version}")
        else:
            st.markdown(SNAPSHOT_UNAVAILABLE_MESSAGE)

        _render_pending_metadata_change_notice()

        _render_persisted_refresh_feedback()

        if st.button("Refresh Snapshot", type="primary", key="metadata_refresh_action"):
            result = refresh_metadata(_metadata_repo_path())
            _handle_refresh_result(result)
            _render_business_refresh_feedback(success=result.success)
            st.rerun()

        st.caption(SNAPSHOT_REFRESH_CAPTION)

    _render_developer_expander(health, bundled=bundled, live_connected=False)

    return {
        "commit_hash": git_status.commit_hash,
        "commit_hash_short": git_status.commit_hash_short,
        "adapter_status": health.adapter_status,
        "sync_status": git_status.sync_status.value,
        "metadata_last_refreshed": last_refreshed,
        "connected": snapshot_available,
        "metadata_mode": "bundled" if bundled else "local",
    }


def _render_developer_expander(
    health: MetadataHealth,
    *,
    bundled: bool,
    live_connected: bool,
) -> None:
    git_status = health.git_status
    last_refreshed = st.session_state.get(SESSION_LAST_REFRESHED)
    last_refresh = st.session_state.get(SESSION_LAST_REFRESH_RESULT)

    with st.expander("View technical details", expanded=False):
        st.markdown(f"**Active provider:** {metadata_source_label(live_connected=live_connected)}")
        st.markdown(f"**Metadata root:** `{health.repo_path}`")
        st.markdown(f"**Metadata mode:** {'bundled snapshot' if bundled else 'local clone'}")
        st.markdown(f"**Snapshot version:** {format_snapshot_version(health)}")

        if live_connected:
            info = get_connection_info(st.session_state)
            if info:
                st.markdown(f"**Connected org:** {info.org_name}")
                st.markdown(f"**Instance URL:** `{info.instance_url}`")

        git_root = find_git_root(health.repo_path)
        if not bundled:
            st.markdown(f"**Git root:** `{git_root}`" if git_root else "**Git root:** Not found")
            st.markdown(f"**Git available:** {'Yes' if git_status.available else 'No'}")
            st.markdown(f"**Branch:** {git_status.branch or '—'}")
        st.markdown(f"**Commit / snapshot id:** {git_status.commit_hash_short or '—'}")
        st.markdown(f"**Full hash:** `{git_status.commit_hash or '—'}`")
        if not bundled:
            st.markdown(f"**Last commit date:** {git_status.last_commit_date or '—'}")
            if git_status.working_tree_clean is None:
                clean_label = "—"
            else:
                clean_label = "Clean" if git_status.working_tree_clean else "Modified"
            st.markdown(f"**Working tree:** {clean_label}")
        st.markdown(f"**Metadata last refreshed:** {_format_timestamp(last_refreshed)}")
        st.markdown(f"**Adapter status:** {health.adapter_status}")
        if not bundled:
            st.markdown(f"**Sync status:** {_status_badge(git_status.sync_status)}")

        count_cols = st.columns(4)
        count_cols[0].metric("Objects", health.counts.objects)
        count_cols[1].metric("Fields", health.counts.fields)
        count_cols[2].metric("Picklists", health.counts.picklists)
        count_cols[3].metric("Templates", health.counts.templates)

        if health.skipped_files:
            st.markdown(f"**Skipped metadata files ({len(health.skipped_files)}):**")
            for skipped in health.skipped_files:
                st.text(skipped)

        raw_errors: list[str] = []
        if health.error:
            raw_errors.append(health.error)
        if last_refresh and not last_refresh.get("success") and last_refresh.get("error"):
            raw_errors.append(str(last_refresh["error"]))
        if raw_errors:
            st.markdown("**Raw errors:**")
            for error in raw_errors:
                st.code(error)

        if last_refresh:
            _render_technical_refresh_details(last_refresh)

        if last_refresh and last_refresh.get("change_summary"):
            summary = last_refresh["change_summary"]
            if summary.get("display_lines"):
                st.markdown("**Latest metadata change summary:**")
                for line in summary["display_lines"]:
                    st.markdown(f"- {line}")

        if is_git_metadata_sync_enabled() and not live_connected:
            st.divider()
            st.markdown("**Git sync controls**")
            _render_git_sync_controls(health)


def _render_technical_refresh_details(last_refresh: dict[str, Any]) -> None:
    counts = last_refresh.get("counts") or {}
    previous = last_refresh.get("previous_counts")
    if counts:
        count_message = (
            f"Objects {_format_count_delta(previous.get('objects') if previous else None, counts.get('objects', 0))}, "
            f"Fields {_format_count_delta(previous.get('fields') if previous else None, counts.get('fields', 0))}, "
            f"Picklists {_format_count_delta(previous.get('picklists') if previous else None, counts.get('picklists', 0))}, "
            f"Templates {_format_count_delta(previous.get('templates') if previous else None, counts.get('templates', 0))}"
        )
        st.markdown(f"**Last refresh counts:** {count_message}")

    previous_commit = last_refresh.get("previous_commit_hash")
    commit_hash = last_refresh.get("commit_hash")
    if previous_commit and commit_hash and previous_commit != commit_hash:
        st.markdown(
            f"**Commit hash:** `{previous_commit[:12]}` → `{commit_hash[:12]}`"
        )

    skipped_count = last_refresh.get("skipped_file_count", 0)
    if skipped_count:
        st.warning(f"{skipped_count} metadata file(s) could not be parsed.")


def _render_git_sync_controls(health: MetadataHealth) -> None:
    repo_path = _metadata_repo_path()
    git_status = health.git_status
    action_cols = st.columns(2)

    with action_cols[0]:
        if st.button("Check for Salesforce Updates", use_container_width=True, key="metadata_check_updates"):
            fetch_result = fetch_remote_updates(repo_path)
            st.session_state[SESSION_GIT_STATUS] = fetch_result.status
            st.session_state[SESSION_UPDATES_AVAILABLE] = (
                fetch_result.status.sync_status == SyncStatus.UPDATES_AVAILABLE
            )
            if fetch_result.success:
                st.info(_status_badge(fetch_result.status.sync_status))
            else:
                st.error(fetch_result.error or "Unable to check for updates.")
            st.rerun()

    with action_cols[1]:
        updates_available = st.session_state.get(SESSION_UPDATES_AVAILABLE, False)
        current_status = st.session_state.get(SESSION_GIT_STATUS) or git_status
        can_pull = (
            updates_available
            and current_status.working_tree_clean is True
            and current_status.tracking_remote
        )
        confirm_key = "confirm_salesforce_pull"
        if can_pull:
            st.checkbox(
                "I approve pulling approved updates",
                key=confirm_key,
            )
        if st.button(
            "Pull Approved Salesforce Updates",
            use_container_width=True,
            disabled=not (can_pull and st.session_state.get(confirm_key, False)),
            key="metadata_pull_updates",
        ):
            previous_commit = git_status.commit_hash
            st.session_state[SESSION_PULL_PREVIOUS_COMMIT] = previous_commit
            pull_result = pull_fast_forward_only(repo_path)
            _render_pull_feedback(pull_result, previous_commit=previous_commit)
            if pull_result.success and pull_result.fast_forward:
                refresh_result = refresh_metadata(repo_path)
                _handle_refresh_result(refresh_result)
                _render_business_refresh_feedback(success=refresh_result.success)
                st.session_state[SESSION_UPDATES_AVAILABLE] = False
                st.session_state[SESSION_GIT_STATUS] = refresh_result.git_status
            st.rerun()


def _render_pending_metadata_change_notice() -> None:
    if not st.session_state.get(SESSION_METADATA_REFRESH_PENDING):
        return
    if not session_has_uploaded_file(st.session_state):
        return

    st.warning(METADATA_VERSION_WARNING)
    summary = st.session_state.get(SESSION_METADATA_CHANGE_SUMMARY) or {}
    for line in summary.get("display_lines", []):
        st.markdown(f"- {line}")

    if st.button("Restart validation using new metadata", key="apply_new_metadata_version"):
        current_status = get_repository_status(_metadata_repo_path())
        apply_new_metadata_version(st.session_state, current_status.commit_hash)
        st.success("Session reset to use the refreshed metadata snapshot.")
        st.rerun()


def _render_pull_feedback(
    result: GitPullResult,
    *,
    previous_commit: str | None = None,
) -> None:
    if result.success:
        st.success(result.message)
        if previous_commit and result.status.commit_hash:
            st.info(
                f"Commit updated: `{previous_commit[:12]}` → `{result.status.commit_hash[:12]}`"
            )
    else:
        st.warning(result.message)
        if result.error:
            st.error(result.error)
