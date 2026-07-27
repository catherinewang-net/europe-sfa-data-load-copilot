"""Read-only Salesforce REST client interface and environment-backed implementation."""

from __future__ import annotations

import os
from typing import Any, Protocol, runtime_checkable

import requests

from services.constants import RECORD_CHECK_UNAVAILABLE


@runtime_checkable
class SalesforceQueryClient(Protocol):
    """Minimal read-only Salesforce query interface."""

    def is_configured(self) -> bool:
        """Return True when credentials are present."""

    def test_connection(self) -> dict[str, Any]:
        """Return connection status without exposing secrets."""

    def query(self, soql: str) -> dict[str, Any]:
        """Execute a SOQL query and return the raw REST payload."""


class UnavailableSalesforceClient:
    """Placeholder client used when live Salesforce is not configured."""

    def __init__(self, reason: str = "Salesforce credentials are not configured.") -> None:
        self._reason = reason

    def is_configured(self) -> bool:
        return False

    def test_connection(self) -> dict[str, Any]:
        return {
            "available": False,
            "status": "unavailable",
            "message": self._reason,
        }

    def query(self, soql: str) -> dict[str, Any]:
        raise ConnectionError(self._reason)


class EnvSalesforceClient:
    """
    Read-only Salesforce client using environment variables.

    Supported auth:
    - SF_INSTANCE_URL + SF_ACCESS_TOKEN
    - SF_USERNAME + SF_PASSWORD + SF_SECURITY_TOKEN (+ optional SF_DOMAIN)
    """

    API_VERSION = "v59.0"

    def __init__(self) -> None:
        self._instance_url = (os.environ.get("SF_INSTANCE_URL") or "").rstrip("/")
        self._access_token = os.environ.get("SF_ACCESS_TOKEN") or ""
        self._username = os.environ.get("SF_USERNAME") or ""
        self._password = os.environ.get("SF_PASSWORD") or ""
        self._security_token = os.environ.get("SF_SECURITY_TOKEN") or ""
        self._domain = os.environ.get("SF_DOMAIN") or "login"
        self._session = requests.Session()
        self._authenticated = False
        self._last_error: str | None = None

    def is_configured(self) -> bool:
        if self._instance_url and self._access_token:
            return True
        return bool(self._username and self._password)

    def test_connection(self) -> dict[str, Any]:
        if not self.is_configured():
            return {
                "available": False,
                "status": "unavailable",
                "message": "Salesforce credentials are not configured.",
            }
        try:
            payload = self.query("SELECT Id FROM User LIMIT 1")
            return {
                "available": True,
                "status": "connected",
                "message": "Live Salesforce connection is available.",
                "record_count": payload.get("totalSize", 0),
            }
        except Exception as exc:
            self._last_error = str(exc)
            return {
                "available": False,
                "status": "error",
                "message": RECORD_CHECK_UNAVAILABLE,
                "error": self._last_error,
            }

    def query(self, soql: str) -> dict[str, Any]:
        self._ensure_authenticated()
        url = f"{self._instance_url}/services/data/{self.API_VERSION}/query"
        response = self._session.get(
            url,
            params={"q": soql},
            headers={"Authorization": f"Bearer {self._access_token}"},
            timeout=30,
        )
        if response.status_code >= 400:
            raise ConnectionError(
                f"Salesforce query failed with status {response.status_code}."
            )
        return response.json()

    def _ensure_authenticated(self) -> None:
        if self._authenticated and self._instance_url and self._access_token:
            return
        if self._instance_url and self._access_token:
            self._authenticated = True
            return
        if not (self._username and self._password):
            raise ConnectionError("Salesforce credentials are not configured.")

        token_url = f"https://{self._domain}.salesforce.com/services/oauth2/token"
        response = self._session.post(
            token_url,
            data={
                "grant_type": "password",
                "client_id": os.environ.get("SF_CLIENT_ID", ""),
                "client_secret": os.environ.get("SF_CLIENT_SECRET", ""),
                "username": self._username,
                "password": f"{self._password}{self._security_token}",
            },
            timeout=30,
        )
        if response.status_code >= 400:
            raise ConnectionError("Salesforce authentication failed.")
        payload = response.json()
        self._instance_url = str(payload.get("instance_url", "")).rstrip("/")
        self._access_token = str(payload.get("access_token", ""))
        if not self._instance_url or not self._access_token:
            raise ConnectionError("Salesforce authentication response was incomplete.")
        self._authenticated = True


def get_salesforce_client() -> SalesforceQueryClient:
    """Return a read-only Salesforce client based on environment configuration."""
    client = EnvSalesforceClient()
    if client.is_configured():
        return client
    return UnavailableSalesforceClient()
