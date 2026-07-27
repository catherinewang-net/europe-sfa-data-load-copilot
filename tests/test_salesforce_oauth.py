"""Tests for Salesforce OAuth service and live metadata provider selection."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from services.metadata_provider_factory import clear_metadata_adapter_cache
from services.export_service import build_review_dataframe
from services.metadata_provider_factory import create_metadata_provider
from services.salesforce_oauth_service import (
    SF_ACCESS_TOKEN,
    SF_INSTANCE_URL,
    SF_OAUTH_STATE,
    SF_PKCE_VERIFIER,
    SF_USERNAME,
    build_authorize_url,
    disconnect,
    exchange_authorization_code,
    handle_oauth_callback,
    is_connected,
    store_connection,
)
import pandas as pd


class SalesforceOAuthServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_metadata_adapter_cache()
        self.session: dict = {}

    def tearDown(self) -> None:
        clear_metadata_adapter_cache()

    @patch.dict(
        os.environ,
        {
            "SALESFORCE_CLIENT_ID": "test-client-id",
            "SALESFORCE_REDIRECT_URI": "https://copilot.example/",
            "SALESFORCE_API_VERSION": "v59.0",
        },
        clear=False,
    )
    def test_build_authorize_url_stores_pkce_and_state(self) -> None:
        url = build_authorize_url(self.session, environment="production")
        self.assertIn("login.salesforce.com", url)
        self.assertIn("code_challenge=", url)
        self.assertIn("client_id=test-client-id", url)
        self.assertTrue(self.session.get(SF_PKCE_VERIFIER))
        self.assertTrue(self.session.get(SF_OAUTH_STATE))

    @patch.dict(
        os.environ,
        {
            "SALESFORCE_CLIENT_ID": "test-client-id",
            "SALESFORCE_REDIRECT_URI": "https://copilot.example/",
        },
        clear=False,
    )
    def test_build_authorize_url_sandbox_host(self) -> None:
        url = build_authorize_url(self.session, environment="sandbox")
        self.assertIn("test.salesforce.com", url)

    @patch("services.salesforce_oauth_service.requests.post")
    @patch.dict(
        os.environ,
        {
            "SALESFORCE_CLIENT_ID": "test-client-id",
            "SALESFORCE_REDIRECT_URI": "https://copilot.example/",
        },
        clear=False,
    )
    def test_exchange_authorization_code(self, post_mock: MagicMock) -> None:
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "access_token": "token-abc",
            "instance_url": "https://example.my.salesforce.com",
            "id": "https://login.salesforce.com/id/00D/005",
        }
        post_mock.return_value = response

        payload = exchange_authorization_code(
            "auth-code",
            environment="production",
            code_verifier="verifier-123",
        )
        self.assertEqual(payload["access_token"], "token-abc")
        post_mock.assert_called_once()
        sent_data = post_mock.call_args.kwargs["data"]
        self.assertEqual(sent_data["code_verifier"], "verifier-123")
        self.assertNotIn("client_secret", sent_data)

    def test_is_connected_requires_token_and_instance(self) -> None:
        self.assertFalse(is_connected(self.session))
        self.session[SF_ACCESS_TOKEN] = "secret-token"
        self.assertFalse(is_connected(self.session))
        self.session[SF_INSTANCE_URL] = "https://example.my.salesforce.com"
        self.assertTrue(is_connected(self.session))

    @patch("services.salesforce_oauth_service._fetch_org_name", return_value="Demo Org")
    @patch("services.salesforce_oauth_service._fetch_identity")
    def test_store_connection_populates_session(
        self,
        identity_mock: MagicMock,
        _org_mock: MagicMock,
    ) -> None:
        identity_mock.return_value = {
            "organization_id": "00Dxx",
            "user_id": "005xx",
            "username": "user@example.com",
        }
        store_connection(
            self.session,
            {
                "access_token": "token-abc",
                "instance_url": "https://example.my.salesforce.com",
                "id": "https://login.salesforce.com/id/00D/005",
            },
        )
        self.assertEqual(self.session[SF_USERNAME], "user@example.com")
        self.assertNotIn(SF_PKCE_VERIFIER, self.session)

    @patch("services.salesforce_oauth_service.exchange_authorization_code")
    def test_handle_oauth_callback_exchanges_code(self, exchange_mock: MagicMock) -> None:
        self.session[SF_OAUTH_STATE] = "state-1"
        self.session[SF_PKCE_VERIFIER] = "verifier-1"
        exchange_mock.return_value = {
            "access_token": "token-abc",
            "instance_url": "https://example.my.salesforce.com",
            "id": "https://login.salesforce.com/id/00D/005",
        }
        query_params = {"code": "auth-code", "state": "state-1"}
        with patch("services.salesforce_oauth_service._fetch_identity", return_value={}):
            with patch("services.salesforce_oauth_service._fetch_org_name", return_value="Org"):
                handled = handle_oauth_callback(self.session, query_params)
        self.assertTrue(handled)
        self.assertTrue(is_connected(self.session))

    def test_disconnect_clears_session_keys(self) -> None:
        self.session[SF_ACCESS_TOKEN] = "token"
        self.session[SF_INSTANCE_URL] = "https://example.my.salesforce.com"
        disconnect(self.session)
        self.assertFalse(is_connected(self.session))

    def test_exported_csv_does_not_contain_token(self) -> None:
        df = pd.DataFrame({"Name": ["Acme"], "Token": ["should-not-leak"]})
        review_df = build_review_dataframe(df, include_issue_notes=False)
        csv_text = review_df.to_csv(index=False)
        self.session[SF_ACCESS_TOKEN] = "super-secret-token-value"
        self.assertNotIn("super-secret-token-value", csv_text)


class MetadataProviderFactoryOAuthTests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_metadata_adapter_cache()

    @patch.dict(os.environ, {"METADATA_MODE": "bundled", "BUNDLED_METADATA_PATH": ""}, clear=False)
    def test_provider_uses_repository_when_not_connected(self) -> None:
        from pathlib import Path
        from unittest.mock import patch as patch_module

        with patch_module(
            "services.metadata_provider_factory.resolve_metadata_repo_path",
            return_value=Path("/tmp/metadata"),
        ):
            with patch_module(
                "services.metadata_provider_factory.RepositoryMetadataProvider"
            ) as repo_mock:
                repo_mock.return_value = MagicMock()
                create_metadata_provider(session_state={})
                repo_mock.assert_called_once()

    @patch.dict(os.environ, {"METADATA_MODE": "bundled"}, clear=False)
    def test_provider_switches_to_live_when_connected(self) -> None:
        from pathlib import Path
        from unittest.mock import patch as patch_module

        session = {
            SF_ACCESS_TOKEN: "token",
            SF_INSTANCE_URL: "https://example.my.salesforce.com",
        }
        with patch_module(
            "services.metadata_provider_factory.resolve_metadata_repo_path",
            return_value=Path("/tmp/metadata"),
        ):
            with patch_module(
                "services.metadata_provider_factory.RepositoryMetadataProvider"
            ) as repo_mock:
                with patch_module(
                    "services.metadata_provider_factory.LiveSalesforceMetadataProvider"
                ) as live_mock:
                    repo_mock.return_value = MagicMock()
                    live_mock.return_value = MagicMock()
                    provider = create_metadata_provider(session_state=session)
                    from services.salesforce.hybrid_metadata_provider import HybridMetadataProvider

                    self.assertIsInstance(provider, HybridMetadataProvider)
                    live_mock.assert_called_once()
                    repo_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
