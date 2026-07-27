"""Tests for Streamlit OIDC gate (separate from Salesforce OAuth)."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from services.streamlit_auth_service import (
    _SSO_NOT_CONFIGURED_MESSAGE,
    enforce_streamlit_login_gate,
    is_streamlit_oidc_configured,
)


class _StreamlitStop(Exception):
    """Simulates Streamlit stopping script execution."""


class StreamlitOidcConfiguredTests(unittest.TestCase):
    def test_returns_false_when_secrets_unavailable(self) -> None:
        mock_st = MagicMock()
        mock_st.secrets.get.side_effect = RuntimeError("no secrets")
        with patch("services.streamlit_auth_service.st", mock_st):
            self.assertFalse(is_streamlit_oidc_configured())

    def test_returns_false_when_auth_block_empty(self) -> None:
        mock_st = MagicMock()
        mock_st.secrets.get.return_value = {}
        with patch("services.streamlit_auth_service.st", mock_st):
            self.assertFalse(is_streamlit_oidc_configured())

    def test_returns_true_when_auth_block_present(self) -> None:
        mock_st = MagicMock()
        mock_st.secrets.get.return_value = {"client_id": "abc"}
        with patch("services.streamlit_auth_service.st", mock_st):
            self.assertTrue(is_streamlit_oidc_configured())


class EnforceStreamlitLoginGateTests(unittest.TestCase):
    def _mock_st(self) -> MagicMock:
        mock_st = MagicMock()
        mock_st.secrets.get.return_value = {}
        mock_st.user = MagicMock()
        mock_st.user.is_logged_in = False
        mock_st.button.return_value = False
        mock_st.stop.side_effect = _StreamlitStop
        return mock_st

    @patch.dict(os.environ, {"REQUIRE_SSO": "false", "DEPLOYMENT_MODE": "demo"}, clear=False)
    def test_no_auth_secrets_and_sso_not_required(self) -> None:
        mock_st = self._mock_st()
        with patch("services.streamlit_auth_service.st", mock_st):
            enforce_streamlit_login_gate()
        mock_st.error.assert_not_called()
        mock_st.stop.assert_not_called()
        mock_st.login.assert_not_called()

    @patch.dict(os.environ, {"REQUIRE_SSO": "true", "DEPLOYMENT_MODE": "demo"}, clear=False)
    def test_no_auth_secrets_and_sso_required(self) -> None:
        mock_st = self._mock_st()
        with patch("services.streamlit_auth_service.st", mock_st):
            with self.assertRaises(_StreamlitStop):
                enforce_streamlit_login_gate()
        mock_st.title.assert_called_once_with("Europe SFA Data Load Copilot")
        mock_st.error.assert_called_once_with(_SSO_NOT_CONFIGURED_MESSAGE)
        mock_st.stop.assert_called_once()
        mock_st.login.assert_not_called()

    @patch.dict(os.environ, {"REQUIRE_SSO": "true", "DEPLOYMENT_MODE": "demo"}, clear=False)
    def test_auth_configured_user_logged_out(self) -> None:
        mock_st = self._mock_st()
        mock_st.secrets.get.return_value = {"client_id": "entra-client"}
        mock_st.user.is_logged_in = False
        with patch("services.streamlit_auth_service.st", mock_st):
            with self.assertRaises(_StreamlitStop):
                enforce_streamlit_login_gate()
        mock_st.title.assert_called_once_with("Europe SFA Data Load Copilot")
        mock_st.write.assert_called_once_with("Sign in to continue.")
        mock_st.button.assert_called_once_with("Sign in")
        mock_st.stop.assert_called_once()
        mock_st.login.assert_not_called()

    @patch.dict(os.environ, {"REQUIRE_SSO": "true", "DEPLOYMENT_MODE": "demo"}, clear=False)
    def test_auth_configured_user_logged_in(self) -> None:
        mock_st = self._mock_st()
        mock_st.secrets.get.return_value = {"client_id": "entra-client"}
        mock_st.user.is_logged_in = True
        with patch("services.streamlit_auth_service.st", mock_st):
            enforce_streamlit_login_gate()
        mock_st.error.assert_not_called()
        mock_st.stop.assert_not_called()
        mock_st.login.assert_not_called()

    @patch.dict(os.environ, {"REQUIRE_SSO": "true", "DEPLOYMENT_MODE": "demo"}, clear=False)
    def test_auth_configured_sign_in_button_triggers_login(self) -> None:
        mock_st = self._mock_st()
        mock_st.secrets.get.return_value = {"client_id": "entra-client"}
        mock_st.user.is_logged_in = False
        mock_st.button.return_value = True
        with patch("services.streamlit_auth_service.st", mock_st):
            with self.assertRaises(_StreamlitStop):
                enforce_streamlit_login_gate()
        mock_st.login.assert_called_once()
        mock_st.stop.assert_called_once()


class IsSsoRequiredDefaultsTests(unittest.TestCase):
    @patch.dict(os.environ, {"DEPLOYMENT_MODE": "demo"}, clear=False)
    def test_demo_defaults_sso_off_without_require_sso(self) -> None:
        from core.config import is_sso_required

        with patch.dict(os.environ, {"REQUIRE_SSO": "", "SSO_ENABLED": "", "SSO_DISABLED": ""}, clear=False):
            os.environ.pop("REQUIRE_SSO", None)
            os.environ.pop("SSO_ENABLED", None)
            os.environ.pop("SSO_DISABLED", None)
            os.environ["DEPLOYMENT_MODE"] = "demo"
            self.assertFalse(is_sso_required())

    @patch.dict(os.environ, {"DEPLOYMENT_MODE": "demo", "REQUIRE_SSO": "true"}, clear=False)
    def test_demo_honors_explicit_require_sso(self) -> None:
        from core.config import is_sso_required

        self.assertTrue(is_sso_required())


if __name__ == "__main__":
    unittest.main()
