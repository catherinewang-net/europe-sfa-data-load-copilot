"""Tests for Salesforce connection and metadata source UI behavior."""

from __future__ import annotations

import inspect
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.config import metadata_source_label
from services.git_repository_service import GitRepositoryStatus, SyncStatus
from services.metadata_provider_factory import (
    clear_metadata_adapter_cache,
    create_metadata_provider,
    resolve_active_metadata_mode,
)
from services.metadata_refresh_service import MetadataCounts, MetadataHealth, is_metadata_connected
from services.salesforce_oauth_service import (
    OAUTH_UNAVAILABLE_MESSAGE,
    SF_ACCESS_TOKEN,
    SF_INSTANCE_URL,
    disconnect,
    get_oauth_configuration_gaps,
    is_connected,
    is_oauth_configured,
)
from ui import metadata_source, salesforce_connection


def _git_status(repo: Path) -> GitRepositoryStatus:
    return GitRepositoryStatus(
        repo_path=repo.resolve(),
        available=True,
        branch="main",
        commit_hash="abc123def456",
        commit_hash_short="abc123d",
        last_commit_date="2026-01-01T12:00:00+00:00",
        working_tree_clean=True,
        tracking_remote=True,
        ahead_count=0,
        behind_count=0,
        sync_status=SyncStatus.UP_TO_DATE,
        error=None,
    )


def _health(repo: Path, *, adapter_available: bool = True) -> MetadataHealth:
    return MetadataHealth(
        repo_path=repo.resolve(),
        adapter_available=adapter_available,
        adapter_status="Healthy" if adapter_available else "Unavailable",
        counts=MetadataCounts(objects=1, fields=2, picklists=1, templates=1),
        skipped_files=[],
        git_status=_git_status(repo),
        error=None,
    )


class MetadataSourceLabelTests(unittest.TestCase):
    def test_live_label(self) -> None:
        self.assertEqual(metadata_source_label(live_connected=True), "Live Salesforce Org")

    def test_snapshot_label(self) -> None:
        self.assertEqual(metadata_source_label(live_connected=False), "Approved Snapshot")


class OAuthConfigurationTests(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_oauth_not_configured_when_env_missing(self) -> None:
        self.assertFalse(is_oauth_configured())
        self.assertEqual(
            get_oauth_configuration_gaps(),
            ["SALESFORCE_CLIENT_ID", "SALESFORCE_REDIRECT_URI"],
        )

    @patch.dict(
        os.environ,
        {
            "SALESFORCE_CLIENT_ID": "client",
            "SALESFORCE_REDIRECT_URI": "https://example/callback",
        },
        clear=False,
    )
    def test_oauth_configured_when_env_present(self) -> None:
        self.assertTrue(is_oauth_configured())
        self.assertEqual(get_oauth_configuration_gaps(), [])


class ActiveMetadataProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_metadata_adapter_cache()
        self.session: dict = {}

    def tearDown(self) -> None:
        clear_metadata_adapter_cache()

    def test_snapshot_active_when_disconnected(self) -> None:
        self.assertEqual(resolve_active_metadata_mode(self.session), "snapshot")
        self.assertFalse(is_connected(self.session))

    def test_live_active_when_connected(self) -> None:
        self.session[SF_ACCESS_TOKEN] = "token"
        self.session[SF_INSTANCE_URL] = "https://example.my.salesforce.com"
        self.assertEqual(resolve_active_metadata_mode(self.session), "live")

    @patch.dict(os.environ, {"METADATA_MODE": "bundled"}, clear=False)
    def test_factory_uses_repository_when_disconnected(self) -> None:
        with patch(
            "services.metadata_provider_factory.resolve_metadata_repo_path",
            return_value=Path("/tmp/metadata"),
        ):
            with patch(
                "services.metadata_provider_factory.RepositoryMetadataProvider"
            ) as repo_mock:
                with patch(
                    "services.metadata_provider_factory.LiveSalesforceMetadataProvider"
                ) as live_mock:
                    repo_mock.return_value = MagicMock()
                    create_metadata_provider(session_state=self.session)
                    repo_mock.assert_called_once()
                    live_mock.assert_not_called()

    @patch.dict(os.environ, {"METADATA_MODE": "bundled"}, clear=False)
    def test_factory_uses_hybrid_when_connected(self) -> None:
        from services.salesforce.hybrid_metadata_provider import HybridMetadataProvider

        self.session[SF_ACCESS_TOKEN] = "token"
        self.session[SF_INSTANCE_URL] = "https://example.my.salesforce.com"
        with patch(
            "services.metadata_provider_factory.resolve_metadata_repo_path",
            return_value=Path("/tmp/metadata"),
        ):
            with patch(
                "services.metadata_provider_factory.RepositoryMetadataProvider"
            ) as repo_mock:
                with patch(
                    "services.metadata_provider_factory.LiveSalesforceMetadataProvider"
                ) as live_mock:
                    repo_mock.return_value = MagicMock()
                    live_mock.return_value = MagicMock()
                    provider = create_metadata_provider(session_state=self.session)
                    self.assertIsInstance(provider, HybridMetadataProvider)


class DisconnectBehaviorTests(unittest.TestCase):
    def test_disconnect_removes_tokens(self) -> None:
        session = {
            SF_ACCESS_TOKEN: "secret-token",
            SF_INSTANCE_URL: "https://example.my.salesforce.com",
        }
        disconnect(session)
        self.assertFalse(is_connected(session))
        self.assertNotIn(SF_ACCESS_TOKEN, session)


class SnapshotVersionFormattingTests(unittest.TestCase):
    def test_uses_git_commit_when_available(self) -> None:
        repo = Path("/tmp/metadata-repo")
        health = _health(repo)
        version = metadata_source.format_snapshot_version(health)
        self.assertIn("abc123d", version)
        self.assertIn("2026-01-01", version)

    def test_uses_manifest_bundled_date_when_no_git_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "SNAPSHOT_MANIFEST.json").write_text(
                json.dumps({"bundled_at_utc": "2026-07-27T16:03:00.8240939Z"}),
                encoding="utf-8",
            )
            git_status = GitRepositoryStatus(
                repo_path=repo.resolve(),
                available=False,
                branch=None,
                commit_hash=None,
                commit_hash_short=None,
                last_commit_date=None,
                working_tree_clean=None,
                tracking_remote=False,
                ahead_count=None,
                behind_count=None,
                sync_status=SyncStatus.GIT_UNAVAILABLE,
                error=None,
            )
            health = MetadataHealth(
                repo_path=repo.resolve(),
                adapter_available=True,
                adapter_status="Healthy",
                counts=MetadataCounts(objects=1, fields=1, picklists=0, templates=1),
                skipped_files=[],
                git_status=git_status,
                error=None,
            )
            version = metadata_source.format_snapshot_version(health)
            self.assertEqual(version, "2026-07-27")


class SalesforceConnectionUiStructureTests(unittest.TestCase):
    def test_disconnected_card_does_not_claim_sf_metadata_connected(self) -> None:
        card_source = inspect.getsource(salesforce_connection.render_salesforce_connection_card)
        badge_source = inspect.getsource(salesforce_connection._connection_badge_html)
        self.assertNotIn("Salesforce Metadata Connected", card_source)
        self.assertIn("Not connected", badge_source)
        self.assertIn("Connect your Salesforce org", card_source)

    def test_oauth_unavailable_uses_business_message_not_raw_env_names(self) -> None:
        source = inspect.getsource(salesforce_connection.render_salesforce_connection_card)
        self.assertIn("OAUTH_UNAVAILABLE_MESSAGE", source)
        self.assertNotIn("Set `SALESFORCE_CLIENT_ID`", source)

    def test_connected_card_has_refresh_and_disconnect(self) -> None:
        source = inspect.getsource(salesforce_connection.render_salesforce_connection_card)
        self.assertIn("Refresh Salesforce Metadata", source)
        self.assertIn("Disconnect", source)

    def test_refresh_failure_does_not_claim_current_metadata(self) -> None:
        source = inspect.getsource(salesforce_connection.render_salesforce_connection_card)
        self.assertIn("_sf_refresh_error", source)
        self.assertIn("approved metadata snapshot", source.lower())


class MetadataSourceUiStructureTests(unittest.TestCase):
    def test_panel_always_uses_metadata_source_subheader(self) -> None:
        source = inspect.getsource(metadata_source.render_metadata_source_panel)
        self.assertIn('st.subheader("Metadata Source")', source)

    def test_snapshot_panel_does_not_show_sf_metadata_connected(self) -> None:
        source = inspect.getsource(metadata_source._render_snapshot_metadata_source_panel)
        self.assertNotIn("Salesforce Metadata Connected", source)
        self.assertIn("metadata_source_label(live_connected=False)", source)
        self.assertIn("Refresh Snapshot", source)

    def test_live_panel_shows_last_refreshed_timestamp(self) -> None:
        source = inspect.getsource(metadata_source._render_live_metadata_source_panel)
        self.assertIn("metadata_source_label(live_connected=True)", source)
        self.assertIn("Metadata was last refreshed", source)

    def test_snapshot_available_when_health_connected(self) -> None:
        repo = Path("/tmp/metadata-repo")
        health = _health(repo)
        with patch(
            "services.metadata_refresh_service.validate_metadata_root",
            return_value=(True, None),
        ):
            self.assertTrue(is_metadata_connected(health))


class AppLayoutOrderTests(unittest.TestCase):
    def test_salesforce_connection_before_metadata_source(self) -> None:
        with open("app.py", encoding="utf-8") as handle:
            source = handle.read()
        sf_index = source.index("render_salesforce_connection_card()")
        metadata_index = source.index("render_metadata_source_panel()")
        self.assertLess(sf_index, metadata_index)


if __name__ == "__main__":
    unittest.main()
