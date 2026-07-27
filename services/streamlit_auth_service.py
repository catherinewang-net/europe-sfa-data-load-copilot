"""Streamlit OIDC app gate — separate from Salesforce OAuth."""

from __future__ import annotations

import streamlit as st

from core.config import APP_NAME, is_sso_required

_SSO_NOT_CONFIGURED_MESSAGE = "Application sign-in is enabled but not configured."


def is_streamlit_oidc_configured() -> bool:
    """Return True when Streamlit `[auth]` secrets are present."""
    try:
        auth_config = st.secrets.get("auth", {})
        return bool(auth_config)
    except Exception:
        return False


def enforce_streamlit_login_gate() -> None:
    """
    Enforce optional Streamlit OIDC sign-in when required and configured.

    - SSO not required: no-op (Salesforce OAuth remains available separately).
    - SSO required but OIDC not configured: admin message, no crash.
    - SSO required and OIDC configured: standard st.login() gate.
    """
    if not is_sso_required():
        return

    if not is_streamlit_oidc_configured():
        st.title(APP_NAME)
        st.error(_SSO_NOT_CONFIGURED_MESSAGE)
        st.stop()

    if not st.user.is_logged_in:
        st.title(APP_NAME)
        st.write("Sign in to continue.")
        if st.button("Sign in"):
            st.login()
        st.stop()
