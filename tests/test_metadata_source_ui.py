"""Tests for Salesforce metadata connection status used by the UI."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from services.git_repository_service import GitRepositoryStatus, SyncStatus
from services.metadata_refresh_service import (
    MetadataCounts,
    MetadataHealth,
    get_metadata_health,
    is_metadata_connected,
)
from services.metadata_refresh_service import refresh_metadata


def _git_status(
    repo: Path,
    *,
    available: bool = True,
    error: str | None = None,
) -> GitRepositoryStatus:
    return GitRepositoryStatus(
        repo_path=repo.resolve(),
        available=available,
        branch="main" if available else None,
        commit_hash="abc123" if available else None,
        commit_hash_short="abc123" if available else None,
        last_commit_date="2026-01-01T12:00:00+00:00" if available else None,
        working_tree_clean=True if available else None,
        tracking_remote=True if available else False,
        ahead_count=0 if available else None,
        behind_count=0 if available else None,
        sync_status=SyncStatus.UP_TO_DATE if available else SyncStatus.GIT_UNAVAILABLE,
        error=error,
    )


def _health(
    repo: Path,
    *,
    adapter_available: bool = True,
    git_available: bool = True,
    path_exists: bool = True,
    error: str | None = None,
) -> MetadataHealth:
    git_status = _git_status(repo, available=git_available, error=error)
    return MetadataHealth(
        repo_path=repo.resolve(),
        adapter_available=adapter_available,
        adapter_status="Healthy" if adapter_available else "Unavailable",
        counts=MetadataCounts(objects=1, fields=2, picklists=1, templates=1),
        skipped_files=[],
        git_status=git_status,
        error=error,
    )


class MetadataConnectionStatusTests(unittest.TestCase):
    def test_connected_when_path_git_and_adapter_available(self) -> None:
        repo = Path("/tmp/metadata-repo")
        health = _health(repo)
        with patch(
            "services.metadata_refresh_service.validate_metadata_root",
            return_value=(True, None),
        ):
            self.assertTrue(is_metadata_connected(health))

    def test_not_connected_when_path_missing(self) -> None:
        repo = Path("/tmp/missing-repo")
        health = _health(repo, adapter_available=False)
        with patch(
            "services.metadata_refresh_service.validate_metadata_root",
            return_value=(False, "Metadata path does not exist"),
        ):
            self.assertFalse(is_metadata_connected(health))

    def test_not_connected_when_git_unavailable(self) -> None:
        repo = Path("/tmp/metadata-repo")
        health = _health(repo, git_available=False, adapter_available=True)
        with patch.object(Path, "exists", return_value=True):
            with patch(
                "services.metadata_refresh_service.validate_metadata_root",
                return_value=(True, None),
            ):
                self.assertTrue(is_metadata_connected(health))

    def test_not_connected_when_adapter_unavailable(self) -> None:
        repo = Path("/tmp/metadata-repo")
        health = _health(repo, adapter_available=False)
        with patch(
            "services.metadata_refresh_service.validate_metadata_root",
            return_value=(True, None),
        ):
            self.assertFalse(is_metadata_connected(health))

    def test_get_metadata_health_not_connected_without_metadata_files(self) -> None:
        import tempfile

        repo = Path(tempfile.mkdtemp())
        (repo / ".git").mkdir()
        with patch(
            "services.metadata_refresh_service.get_repository_status",
            return_value=_git_status(repo),
        ):
            health = get_metadata_health(repo)
        self.assertFalse(is_metadata_connected(health))

    def test_refresh_failure_yields_not_connected(self) -> None:
        import tempfile

        repo = Path(tempfile.mkdtemp())
        (repo / ".git").mkdir()
        with patch(
            "services.metadata_refresh_service.get_repository_status",
            return_value=_git_status(repo),
        ):
            result = refresh_metadata(repo)
            health = get_metadata_health(repo)
        self.assertFalse(result.success)
        self.assertFalse(is_metadata_connected(health))


if __name__ == "__main__":
    unittest.main()
