"""Salesforce connection card — primary OAuth entry point."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import streamlit as st

from core.config import get_salesforce_api_version
from services.metadata_provider_factory import create_hybrid_metadata_provider
from services.metadata_session_service import (
    apply_new_metadata_version,
    mark_metadata_refresh_pending,
    metadata_version_changed,
    session_has_uploaded_file,
)
from services.revalidation_service import clear_stale_metadata_validation
from services.salesforce_oauth_service import (
    OAUTH_UNAVAILABLE_MESSAGE,
    SF_OAUTH_ERROR,
    build_authorize_url,
    disconnect,
    get_connection_info,
    get_oauth_configuration_gaps,
    is_connected,
    is_oauth_configured,
)


SESSION_NOTE = (
    "Your Salesforce connection is active only for this browser session."
)


def _format_timestamp(value: datetime | None) -> str:
    if value is None:
        return "Not refreshed this session"
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _connection_badge_html(connected: bool) -> str:
    if connected:
        return (
            '<div class="metadata-status-badge metadata-status-connected" role="status">'
            '<span class="metadata-status-icon" aria-hidden="true">✅</span>'
            '<span class="metadata-status-label">Connected</span>'
            "</div>"
        )
    return (
        '<div class="metadata-status-badge metadata-status-disconnected" role="status">'
        '<span class="metadata-status-icon" aria-hidden="true">⚠️</span>'
        '<span class="metadata-status-label">Not connected</span>'
        "</div>"
    )


def _render_oauth_technical_expander() -> None:
    gaps = get_oauth_configuration_gaps()
    with st.expander("View technical details", expanded=False):
        st.markdown("**Live Salesforce OAuth configuration**")
        if gaps:
            st.markdown(
                "Missing environment variables: "
                + ", ".join(f"`{name}`" for name in gaps)
            )
        else:
            st.markdown("OAuth client ID and redirect URI are configured.")
        st.markdown(f"**API version:** `{get_salesforce_api_version()}`")


def render_salesforce_connection_card() -> dict[str, Any]:
    """Render the primary Salesforce OAuth connection card."""
    connected = is_connected(st.session_state)
    st.subheader("Salesforce Connection")

    with st.container(border=True):
        st.markdown(_connection_badge_html(connected), unsafe_allow_html=True)

        oauth_error = st.session_state.pop(SF_OAUTH_ERROR, None)
        if oauth_error:
            st.error(oauth_error)

        refresh_error = st.session_state.pop("_sf_refresh_error", None)
        if refresh_error:
            st.error(refresh_error)

        if connected:
            info = get_connection_info(st.session_state)
            if info:
                st.markdown(f"**Org:** {info.org_name}")
                st.markdown(f"**Environment:** {info.environment.title()}")
                st.markdown(f"**User:** {info.username or info.user_id}")
                st.markdown(f"**Instance:** `{info.instance_url}`")
                st.markdown(
                    f"**Last refresh:** {_format_timestamp(info.metadata_refreshed_at)}"
                )
            st.caption(SESSION_NOTE)

            action_cols = st.columns(2)
            with action_cols[0]:
                if st.button(
                    "Refresh Salesforce Metadata",
                    type="primary",
                    key="sf_refresh_metadata",
                ):
                    try:
                        provider = create_hybrid_metadata_provider(st.session_state)
                        if hasattr(provider, "refresh_metadata"):
                            provider.refresh_metadata()
                        _handle_live_metadata_refresh()
                        st.session_state.pop("_sf_refresh_error", None)
                        st.success("Live Salesforce metadata refreshed.")
                    except Exception as exc:
                        st.session_state["_sf_refresh_error"] = (
                            "Could not refresh live Salesforce metadata. "
                            "Validation continues using the approved metadata snapshot "
                            "until you connect and refresh again."
                        )
                        st.session_state["_sf_refresh_technical_error"] = str(exc)
                    st.rerun()
            with action_cols[1]:
                if st.button("Disconnect", key="sf_disconnect"):
                    disconnect(st.session_state)
                    from services.metadata_provider_factory import clear_metadata_adapter_cache

                    clear_metadata_adapter_cache()
                    st.session_state.pop("_sf_refresh_error", None)
                    st.session_state.pop("_sf_refresh_technical_error", None)
                    st.info("Disconnected from Salesforce. Using approved metadata snapshot.")
                    st.rerun()

            technical_error = st.session_state.get("_sf_refresh_technical_error")
            if technical_error:
                with st.expander("View technical details", expanded=False):
                    st.code(technical_error)
        else:
            st.markdown(
                "Connect your Salesforce org to validate files against its latest metadata."
            )

            if not is_oauth_configured():
                st.info(OAUTH_UNAVAILABLE_MESSAGE)
                _render_oauth_technical_expander()
            else:
                env_choice = st.radio(
                    "Choose org type",
                    options=["Production / Developer Org", "Sandbox"],
                    horizontal=True,
                    key="sf_environment_choice",
                )
                environment = "sandbox" if env_choice == "Sandbox" else "production"
                if st.button("Connect Salesforce", type="primary", key="sf_connect"):
                    authorize_url = build_authorize_url(
                        st.session_state, environment=environment
                    )
                    st.session_state["_sf_authorize_url"] = authorize_url
                    st.rerun()

    pending_redirect = st.session_state.pop("_sf_authorize_url", None)
    if pending_redirect:
        st.components.v1.html(
            f'<script>window.location.href = {pending_redirect!r};</script>',
            height=0,
        )

    return {"connected": connected}


def _handle_live_metadata_refresh() -> None:
    """Invalidate cached validation when live metadata is refreshed mid-session."""
    if not session_has_uploaded_file(st.session_state):
        return
    locked_hash = st.session_state.get("metadata_version")
    current_hash = "live-oauth"
    if metadata_version_changed(locked_hash, current_hash):
        clear_stale_metadata_validation(st.session_state)
        mark_metadata_refresh_pending(st.session_state)
    else:
        apply_new_metadata_version(st.session_state, current_hash)
