"""Tests for git_repository_service using temporary repository directories."""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from services.git_repository_service import (
    SyncStatus,
    fetch_remote_updates,
    find_git_root,
    get_repository_status,
    pull_fast_forward_only,
    validate_metadata_root,
    validate_repo_path,
)


def _git_available() -> bool:
    return shutil.which("git") is not None


def _make_fake_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()


def _completed(stdout: str = "", stderr: str = "", code: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=stdout, stderr=stderr)


class GitRepositoryServiceMockedTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self.repo = Path(tempfile.mkdtemp())
        _make_fake_repo(self.repo)

    def test_validate_existing_git_repository(self) -> None:
        valid, error = validate_repo_path(self.repo)
        self.assertTrue(valid)
        self.assertIsNone(error)

    def test_find_git_root_from_nested_path(self) -> None:
        nested = self.repo / "force-app" / "main" / "default"
        nested.mkdir(parents=True)
        self.assertEqual(find_git_root(nested), self.repo.resolve())

    def test_validate_metadata_root_requires_sfdx_structure(self) -> None:
        metadata = self.repo / "sfdx"
        metadata.mkdir()
        valid, error = validate_metadata_root(metadata)
        self.assertFalse(valid)
        self.assertIn("sfdx-project.json", error or "")

        (metadata / "sfdx-project.json").write_text("{}", encoding="utf-8")
        default = metadata / "force-app" / "main" / "default"
        default.mkdir(parents=True)
        valid, error = validate_metadata_root(metadata)
        self.assertTrue(valid)
        self.assertIsNone(error)

    def test_nonexistent_path_is_unavailable(self) -> None:
        missing = self.repo / "missing"
        status = get_repository_status(missing)
        self.assertFalse(status.available)
        self.assertEqual(status.sync_status, SyncStatus.GIT_UNAVAILABLE)

    def test_directory_without_git_is_unavailable(self) -> None:
        import tempfile

        plain = Path(tempfile.mkdtemp())
        status = get_repository_status(plain)
        self.assertFalse(status.available)
        self.assertEqual(status.sync_status, SyncStatus.GIT_UNAVAILABLE)
        self.assertIn("No Git repository found", status.error or "")

    @patch("services.git_repository_service._run_git")
    def test_status_includes_branch_commit_and_date(self, mock_run) -> None:
        mock_run.side_effect = [
            _completed("main\n"),
            _completed("abc123def456\n"),
            _completed("abc123d\n"),
            _completed("2026-01-01T12:00:00+00:00\n"),
            _completed(""),
            _completed("", code=1),
        ]
        status = get_repository_status(self.repo)
        self.assertTrue(status.available)
        self.assertEqual(status.branch, "main")
        self.assertEqual(status.commit_hash, "abc123def456")
        self.assertEqual(status.commit_hash_short, "abc123d")
        self.assertTrue(status.working_tree_clean)
        self.assertEqual(status.sync_status, SyncStatus.BRANCH_NOT_TRACKING)

    @patch("services.git_repository_service._run_git")
    def test_modified_working_tree_reports_local_changes(self, mock_run) -> None:
        mock_run.side_effect = [
            _completed("main\n"),
            _completed("abc\n"),
            _completed("abc\n"),
            _completed("2026-01-01T12:00:00+00:00\n"),
            _completed(" M file.txt\n"),
            _completed("origin/main\n"),
            _completed("0\t0\n"),
        ]
        status = get_repository_status(self.repo)
        self.assertFalse(status.working_tree_clean)
        self.assertEqual(status.sync_status, SyncStatus.LOCAL_CHANGES)

    @patch("services.git_repository_service._run_git")
    def test_clean_tracked_branch_is_up_to_date(self, mock_run) -> None:
        mock_run.side_effect = [
            _completed("main\n"),
            _completed("abc\n"),
            _completed("abc\n"),
            _completed("2026-01-01T12:00:00+00:00\n"),
            _completed(""),
            _completed("origin/main\n"),
            _completed(""),
            _completed("0\t0\n"),
            _completed("0\t0\n"),
        ]
        status = get_repository_status(self.repo, fetch=True)
        self.assertTrue(status.tracking_remote)
        self.assertEqual(status.sync_status, SyncStatus.UP_TO_DATE)

    @patch("services.git_repository_service._run_git")
    def test_fetch_detects_remote_updates(self, mock_run) -> None:
        mock_run.side_effect = [
            _completed("main\n"),
            _completed("abc\n"),
            _completed("abc\n"),
            _completed("2026-01-01T12:00:00+00:00\n"),
            _completed(""),
            _completed("origin/main\n"),
            _completed(""),
            _completed("2\t0\n"),
        ]
        fetch_result = fetch_remote_updates(self.repo)
        self.assertTrue(fetch_result.success)
        self.assertEqual(fetch_result.status.sync_status, SyncStatus.UPDATES_AVAILABLE)
        self.assertEqual(fetch_result.status.behind_count, 2)

    @patch("services.git_repository_service._run_git")
    def test_pull_fast_forward_success(self, mock_run) -> None:
        mock_run.side_effect = [
            _completed("main\n"),
            _completed("old\n"),
            _completed("old\n"),
            _completed("2026-01-01T12:00:00+00:00\n"),
            _completed(""),
            _completed("origin/main\n"),
            _completed(""),
            _completed("1\t0\n"),
            _completed("", code=0),
            _completed(""),
            _completed("main\n"),
            _completed("new\n"),
            _completed("new\n"),
            _completed("2026-01-02T12:00:00+00:00\n"),
            _completed(""),
            _completed("origin/main\n"),
            _completed("0\t0\n"),
        ]
        pull_result = pull_fast_forward_only(self.repo)
        self.assertTrue(pull_result.success)
        self.assertTrue(pull_result.fast_forward)
        self.assertEqual(pull_result.status.commit_hash, "new")

    @patch("services.git_repository_service._run_git")
    def test_pull_rejects_non_fast_forward(self, mock_run) -> None:
        mock_run.side_effect = [
            _completed("main\n"),
            _completed("local\n"),
            _completed("local\n"),
            _completed("2026-01-01T12:00:00+00:00\n"),
            _completed(""),
            _completed("origin/main\n"),
            _completed(""),
            _completed("1\t1\n"),
            _completed("", code=1),
            _completed("main\n"),
            _completed("local\n"),
            _completed("local\n"),
            _completed("2026-01-01T12:00:00+00:00\n"),
            _completed(""),
            _completed("origin/main\n"),
            _completed("1\t1\n"),
        ]
        pull_result = pull_fast_forward_only(self.repo)
        self.assertFalse(pull_result.success)
        self.assertIn("manual Git resolution", pull_result.message)

    @patch("services.git_repository_service._run_git")
    def test_branch_without_upstream_is_not_tracking(self, mock_run) -> None:
        mock_run.side_effect = [
            _completed("feature/no-upstream\n"),
            _completed("abc\n"),
            _completed("abc\n"),
            _completed("2026-01-01T12:00:00+00:00\n"),
            _completed(""),
            _completed("", code=128),
        ]
        status = get_repository_status(self.repo)
        self.assertFalse(status.tracking_remote)
        self.assertEqual(status.sync_status, SyncStatus.BRANCH_NOT_TRACKING)

    @patch("services.git_repository_service._run_git")
    def test_git_errors_are_sanitized(self, mock_run) -> None:
        mock_run.side_effect = [
            _completed("", stderr="fatal: https://token:secret@github.com/org/repo\n", code=128),
        ]
        status = get_repository_status(self.repo)
        self.assertFalse(status.available)
        self.assertEqual(status.sync_status, SyncStatus.GIT_UNAVAILABLE)
        self.assertNotIn("secret", status.error or "")

    @patch("services.git_repository_service._run_git")
    def test_fetch_does_not_modify_working_tree_files(self, mock_run) -> None:
        marker = self.repo / "local-marker.txt"
        marker.write_text("unchanged", encoding="utf-8")
        mock_run.side_effect = [
            _completed("main\n"),
            _completed("abc\n"),
            _completed("abc\n"),
            _completed("2026-01-01T12:00:00+00:00\n"),
            _completed(""),
            _completed("origin/main\n"),
            _completed(""),
            _completed("1\t0\n"),
        ]
        fetch_result = fetch_remote_updates(self.repo)
        self.assertTrue(fetch_result.success)
        self.assertEqual(marker.read_text(encoding="utf-8"), "unchanged")
        pull_commands = [call.args[1:] for call in mock_run.call_args_list]
        self.assertFalse(any(args and args[0] == "pull" for args in pull_commands))

    @patch("services.git_repository_service._run_git")
    def test_dirty_working_tree_blocks_pull(self, mock_run) -> None:
        mock_run.side_effect = [
            _completed("main\n"),
            _completed("abc\n"),
            _completed("abc\n"),
            _completed("2026-01-01T12:00:00+00:00\n"),
            _completed(" M dirty.txt\n"),
            _completed("origin/main\n"),
            _completed(""),
            _completed("2\t0\n"),
        ]
        pull_result = pull_fast_forward_only(self.repo)
        self.assertFalse(pull_result.success)
        self.assertIn("Local changes", pull_result.message)
        pull_commands = [call.args[1:] for call in mock_run.call_args_list]
        self.assertFalse(any(args and args[0] == "pull" for args in pull_commands))


@unittest.skipUnless(_git_available(), "git executable not available")
class GitRepositoryServiceIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = Path(tempfile.mkdtemp())
        self.repo = self._tmp / "repo"
        self.remote = self._tmp / "remote.git"
        self._init_bare_remote(self.remote)
        self._init_repo(self.repo)
        subprocess.run(["git", "-C", str(self.repo), "branch", "-M", "main"], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "remote", "add", "origin", str(self.remote)],
            check=True,
        )
        subprocess.run(["git", "-C", str(self.repo), "push", "-u", "origin", "main"], check=True)

    @staticmethod
    def _init_bare_remote(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "--bare"], cwd=path, check=True, capture_output=True)

    @staticmethod
    def _init_repo(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=path,
            check=True,
            capture_output=True,
        )
        (path / "README.md").write_text("v1", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, capture_output=True)

    def test_real_fetch_and_fast_forward_pull(self) -> None:
        clone = self._tmp / "clone"
        subprocess.run(["git", "clone", str(self.remote), str(clone)], check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=clone,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=clone,
            check=True,
            capture_output=True,
        )

        (self.repo / "README.md").write_text("v2", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-m", "update"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "push", "origin", "main"], check=True)

        fetch_result = fetch_remote_updates(clone)
        self.assertEqual(fetch_result.status.sync_status, SyncStatus.UPDATES_AVAILABLE)

        pull_result = pull_fast_forward_only(clone)
        self.assertTrue(pull_result.success)
        self.assertEqual((clone / "README.md").read_text(encoding="utf-8"), "v2")


if __name__ == "__main__":
    unittest.main()
