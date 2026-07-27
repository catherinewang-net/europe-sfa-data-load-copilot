"""Salesforce OAuth 2.0 authorization code flow with PKCE (session-scoped)."""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import requests

from core.config import (
    get_salesforce_api_version,
    get_salesforce_client_id,
    get_salesforce_oauth_scopes,
    get_salesforce_redirect_uri,
    salesforce_login_host,
)

# Session keys — per Streamlit browser session only (v1: no persistence across restarts).
SF_ACCESS_TOKEN = "sf_oauth_access_token"
SF_REFRESH_TOKEN = "sf_oauth_refresh_token"
SF_INSTANCE_URL = "sf_oauth_instance_url"
SF_ORG_ID = "sf_oauth_org_id"
SF_ORG_NAME = "sf_oauth_org_name"
SF_USER_ID = "sf_oauth_user_id"
SF_USERNAME = "sf_oauth_username"
SF_ENVIRONMENT = "sf_oauth_environment"
SF_CONNECTED_AT = "sf_oauth_connected_at"
SF_METADATA_REFRESHED_AT = "sf_oauth_metadata_refreshed_at"
SF_PKCE_VERIFIER = "sf_oauth_pkce_verifier"
SF_OAUTH_STATE = "sf_oauth_state"
SF_OAUTH_ERROR = "sf_oauth_error"

SF_SESSION_KEYS = (
    SF_ACCESS_TOKEN,
    SF_REFRESH_TOKEN,
    SF_INSTANCE_URL,
    SF_ORG_ID,
    SF_ORG_NAME,
    SF_USER_ID,
    SF_USERNAME,
    SF_ENVIRONMENT,
    SF_CONNECTED_AT,
    SF_METADATA_REFRESHED_AT,
    SF_PKCE_VERIFIER,
    SF_OAUTH_STATE,
    SF_OAUTH_ERROR,
)


@dataclass(frozen=True)
class SalesforceConnectionInfo:
    org_id: str
    org_name: str
    username: str
    user_id: str
    instance_url: str
    environment: str
    connected_at: datetime
    metadata_refreshed_at: datetime | None


def is_oauth_configured() -> bool:
    return bool(get_salesforce_client_id() and get_salesforce_redirect_uri())


OAUTH_UNAVAILABLE_MESSAGE = (
    "Live Salesforce connection is not currently available. "
    "Validation will use the approved metadata snapshot."
)


def get_oauth_configuration_gaps() -> list[str]:
    """Return missing Salesforce OAuth env var names (for technical details only)."""
    gaps: list[str] = []
    if not get_salesforce_client_id():
        gaps.append("SALESFORCE_CLIENT_ID")
    if not get_salesforce_redirect_uri():
        gaps.append("SALESFORCE_REDIRECT_URI")
    return gaps


def is_connected(session_state: dict[str, Any]) -> bool:
    return bool(session_state.get(SF_ACCESS_TOKEN) and session_state.get(SF_INSTANCE_URL))


def get_connection_info(session_state: dict[str, Any]) -> SalesforceConnectionInfo | None:
    if not is_connected(session_state):
        return None
    connected_raw = session_state.get(SF_CONNECTED_AT)
    refreshed_raw = session_state.get(SF_METADATA_REFRESHED_AT)
    connected_at = (
        datetime.fromisoformat(connected_raw)
        if isinstance(connected_raw, str)
        else datetime.now(timezone.utc)
    )
    metadata_refreshed_at = (
        datetime.fromisoformat(refreshed_raw) if isinstance(refreshed_raw, str) else None
    )
    return SalesforceConnectionInfo(
        org_id=str(session_state.get(SF_ORG_ID) or ""),
        org_name=str(session_state.get(SF_ORG_NAME) or "Connected org"),
        username=str(session_state.get(SF_USERNAME) or ""),
        user_id=str(session_state.get(SF_USER_ID) or ""),
        instance_url=str(session_state.get(SF_INSTANCE_URL) or ""),
        environment=str(session_state.get(SF_ENVIRONMENT) or "production"),
        connected_at=connected_at,
        metadata_refreshed_at=metadata_refreshed_at,
    )


def get_session_auth(session_state: dict[str, Any]) -> dict[str, str] | None:
    if not is_connected(session_state):
        return None
    return {
        "access_token": str(session_state[SF_ACCESS_TOKEN]),
        "instance_url": str(session_state[SF_INSTANCE_URL]).rstrip("/"),
        "api_version": get_salesforce_api_version(),
    }


def disconnect(session_state: dict[str, Any]) -> None:
    for key in SF_SESSION_KEYS:
        session_state.pop(key, None)


def _generate_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")
    return verifier, challenge


def build_authorize_url(session_state: dict[str, Any], *, environment: str) -> str:
    if not is_oauth_configured():
        raise RuntimeError(
            "Salesforce OAuth is not configured. Set SALESFORCE_CLIENT_ID and "
            "SALESFORCE_REDIRECT_URI."
        )
    verifier, challenge = _generate_pkce_pair()
    state = secrets.token_urlsafe(32)
    session_state[SF_PKCE_VERIFIER] = verifier
    session_state[SF_OAUTH_STATE] = state
    session_state[SF_ENVIRONMENT] = environment
    session_state.pop(SF_OAUTH_ERROR, None)

    params = {
        "response_type": "code",
        "client_id": get_salesforce_client_id(),
        "redirect_uri": get_salesforce_redirect_uri(),
        "scope": get_salesforce_oauth_scopes(),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    host = salesforce_login_host(environment)
    return f"{host}/services/oauth2/authorize?{urlencode(params)}"


def exchange_authorization_code(
    code: str,
    *,
    environment: str,
    code_verifier: str,
) -> dict[str, Any]:
    host = salesforce_login_host(environment)
    response = requests.post(
        f"{host}/services/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": get_salesforce_client_id(),
            "redirect_uri": get_salesforce_redirect_uri(),
            "code_verifier": code_verifier,
        },
        timeout=30,
    )
    if response.status_code >= 400:
        raise ConnectionError("Salesforce authorization failed. Try connecting again.")
    payload = response.json()
    if not payload.get("access_token") or not payload.get("instance_url"):
        raise ConnectionError("Salesforce token response was incomplete.")
    return payload


def _fetch_identity(access_token: str, identity_url: str) -> dict[str, Any]:
    response = requests.get(
        identity_url,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    if response.status_code >= 400:
        return {}
    return response.json()


def _fetch_org_name(instance_url: str, access_token: str, org_id: str) -> str:
    api_version = get_salesforce_api_version()
    soql = f"SELECT Name FROM Organization WHERE Id = '{org_id}' LIMIT 1"
    response = requests.get(
        f"{instance_url.rstrip('/')}/services/data/{api_version}/query",
        params={"q": soql},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    if response.status_code >= 400:
        return org_id
    records = response.json().get("records") or []
    if records:
        return str(records[0].get("Name") or org_id)
    return org_id


def store_connection(session_state: dict[str, Any], token_payload: dict[str, Any]) -> None:
    access_token = str(token_payload["access_token"])
    instance_url = str(token_payload["instance_url"]).rstrip("/")
    identity_url = str(token_payload.get("id") or "")
    environment = str(session_state.get(SF_ENVIRONMENT) or "production")

    identity = _fetch_identity(access_token, identity_url) if identity_url else {}
    org_id = str(identity.get("organization_id") or "")
    user_id = str(identity.get("user_id") or "")
    username = str(identity.get("username") or identity.get("preferred_username") or "")

    org_name = _fetch_org_name(instance_url, access_token, org_id) if org_id else "Connected org"
    now = datetime.now(timezone.utc).isoformat()

    session_state[SF_ACCESS_TOKEN] = access_token
    session_state[SF_REFRESH_TOKEN] = str(token_payload.get("refresh_token") or "")
    session_state[SF_INSTANCE_URL] = instance_url
    session_state[SF_ORG_ID] = org_id
    session_state[SF_ORG_NAME] = org_name
    session_state[SF_USER_ID] = user_id
    session_state[SF_USERNAME] = username
    session_state[SF_ENVIRONMENT] = environment
    session_state[SF_CONNECTED_AT] = now
    session_state[SF_METADATA_REFRESHED_AT] = now
    session_state.pop(SF_PKCE_VERIFIER, None)
    session_state.pop(SF_OAUTH_STATE, None)
    session_state.pop(SF_OAUTH_ERROR, None)


def handle_oauth_callback(session_state: dict[str, Any], query_params: Any) -> bool:
    """
    Process Salesforce OAuth callback query params.

    Returns True when a callback was handled (caller should rerun and clear URL params).
    """
    code = _first_param(query_params, "code")
    state = _first_param(query_params, "state")
    error = _first_param(query_params, "error")

    if error:
        session_state[SF_OAUTH_ERROR] = _first_param(query_params, "error_description") or error
        session_state.pop(SF_PKCE_VERIFIER, None)
        session_state.pop(SF_OAUTH_STATE, None)
        return True

    if not code:
        return False

    expected_state = session_state.get(SF_OAUTH_STATE)
    verifier = session_state.get(SF_PKCE_VERIFIER)
    environment = str(session_state.get(SF_ENVIRONMENT) or "production")

    if not expected_state or state != expected_state or not verifier:
        session_state[SF_OAUTH_ERROR] = (
            "OAuth state mismatch or session expired. Connect to Salesforce again."
        )
        return True

    try:
        token_payload = exchange_authorization_code(
            code,
            environment=environment,
            code_verifier=str(verifier),
        )
        store_connection(session_state, token_payload)
    except ConnectionError as exc:
        session_state[SF_OAUTH_ERROR] = str(exc)
    return True


def mark_metadata_refreshed(session_state: dict[str, Any]) -> None:
    session_state[SF_METADATA_REFRESHED_AT] = datetime.now(timezone.utc).isoformat()


def _first_param(query_params: Any, key: str) -> str | None:
    if query_params is None:
        return None
    if hasattr(query_params, "get"):
        value = query_params.get(key)
        if value is None:
            return None
        if isinstance(value, list):
            return str(value[0]) if value else None
        return str(value) if value else None
    return None
