"""Tests for PepFlow AI branding, landing, and hybrid metadata fallback."""

from __future__ import annotations

import inspect
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.config import APP_NAME, APP_TAGLINE, get_salesforce_oauth_scopes
from services.metadata_provider_factory import _adapter_cache_key, clear_metadata_adapter_cache
from services.salesforce.hybrid_metadata_provider import HybridMetadataProvider
from services.salesforce_oauth_service import SF_ACCESS_TOKEN, SF_INSTANCE_URL, SF_ORG_ID
from ui import landing, metadata_source, salesforce_connection


class PepFlowBrandingTests(unittest.TestCase):
    def test_app_name_and_tagline(self) -> None:
        self.assertEqual(APP_NAME, "PepFlow AI")
        self.assertEqual(APP_TAGLINE, "Prepare. Validate. Load.")

    def test_app_py_page_config_uses_pepflow(self) -> None:
        source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn('page_title=APP_NAME', source)
        self.assertIn('page_icon="🔵"', source)
        self.assertIn("render_landing_hero()", source)
        self.assertNotIn('st.title("Europe SFA Data Load Copilot")', source)

    def test_landing_hero_renders_product_identity(self) -> None:
        source = inspect.getsource(landing.render_landing_hero)
        self.assertIn("APP_NAME", source)
        self.assertIn("APP_TAGLINE", source)
        self.assertIn("APP_DESCRIPTION", source)


class ConnectionUiEnhancementTests(unittest.TestCase):
    def test_connected_card_shows_instance_and_session_note(self) -> None:
        source = inspect.getsource(salesforce_connection.render_salesforce_connection_card)
        self.assertIn("**Instance:**", source)
        self.assertIn("**Last refresh:**", source)
        self.assertIn("SESSION_NOTE", source)

    def test_metadata_source_shows_automatic_fallback(self) -> None:
        source = inspect.getsource(metadata_source._render_snapshot_metadata_source_panel)
        self.assertIn("SNAPSHOT_FALLBACK_CAPTION", source)
        self.assertIn("PepFlow AI", metadata_source.SNAPSHOT_ACTIVE_MESSAGE)


class HybridFallbackTests(unittest.TestCase):
    def test_live_describe_failure_falls_back_to_repository(self) -> None:
        live = MagicMock()
        repository = MagicMock()
        live.get_object_fields.side_effect = ConnectionError("Unable to describe Salesforce org.")
        repository.get_object_fields.return_value = {"Name": MagicMock()}

        provider = HybridMetadataProvider(live, repository)
        fields = provider.get_object_fields("Account")

        self.assertIn("Name", fields)
        repository.get_object_fields.assert_called_once_with("Account")


class SessionIsolationTests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_metadata_adapter_cache()

    def test_adapter_cache_key_includes_org_when_connected(self) -> None:
        repo = Path("/tmp/metadata")
        session_a = {SF_ACCESS_TOKEN: "a", SF_INSTANCE_URL: "https://a.example.com", SF_ORG_ID: "00D-A"}
        session_b = {SF_ACCESS_TOKEN: "b", SF_INSTANCE_URL: "https://b.example.com", SF_ORG_ID: "00D-B"}
        key_a = _adapter_cache_key(repo, session_a)
        key_b = _adapter_cache_key(repo, session_b)
        self.assertNotEqual(key_a, key_b)
        self.assertIn("live:00D-A", key_a)


class OAuthScopeTests(unittest.TestCase):
    def test_default_oauth_scopes(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(get_salesforce_oauth_scopes(), "api refresh_token id")


if __name__ == "__main__":
    unittest.main()
