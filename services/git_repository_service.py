"""Safe Git operations for the local EUSFA Salesforce DX repository."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class SyncStatus(str, Enum):
    UP_TO_DATE = "Up to date"
    UPDATES_AVAILABLE = "Updates available"
    LOCAL_CHANGES = "Local changes"
    BRANCH_NOT_TRACKING = "Branch not tracking"
    GIT_UNAVAILABLE = "Git unavailable"


@dataclass(frozen=True)
class GitRepositoryStatus:
    repo_path: Path
    available: bool
    branch: str | None
    commit_hash: str | None
    commit_hash_short: str | None
    last_commit_date: str | None
    working_tree_clean: bool | None
    tracking_remote: bool
    ahead_count: int | None
    behind_count: int | None
    sync_status: SyncStatus
    error: str | None = None


@dataclass(frozen=True)
class GitFetchResult:
    success: bool
    status: GitRepositoryStatus
    error: str | None = None


@dataclass(frozen=True)
class GitPullResult:
    success: bool
    fast_forward: bool
    status: GitRepositoryStatus
    message: str
    error: str | None = None


_CREDENTIAL_PATTERN = re.compile(
    r"(https?://)[^/@\s]+@[^/\s]+",
    re.IGNORECASE,
)


def _sanitize_git_message(message: str) -> str:
    """Remove credential fragments from Git error output."""
    sanitized = _CREDENTIAL_PATTERN.sub(r"\1***@", message)
    sanitized = re.sub(r"(?i)(password|token|credential)[^\s]*", "***", sanitized)
    return sanitized.strip()


def _run_git(repo_path: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_path), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped or stripped == "-":
        return None
    try:
        return int(stripped)
    except ValueError:
        return None


def find_git_root(start_path: Path) -> Path | None:
    """Return the nearest parent directory containing a .git folder, if any."""
    resolved = start_path.resolve()
    if not resolved.exists():
        return None
    current = resolved if resolved.is_dir() else resolved.parent
    while True:
        if (current / ".git").exists():
            return current
        if current == current.parent:
            return None
        current = current.parent


def validate_metadata_root(metadata_path: Path) -> tuple[bool, str | None]:
    """
    Return whether the path is a valid Salesforce DX metadata project root.

    Requires sfdx-project.json and force-app/main/default/.
    Does not require a Git repository.
    """
    resolved = metadata_path.resolve()
    if not resolved.exists():
        return False, f"Metadata path does not exist: {resolved}"
    if not resolved.is_dir():
        return False, f"Metadata path is not a directory: {resolved}"
    if not (resolved / "sfdx-project.json").is_file():
        return False, f"sfdx-project.json not found in: {resolved}"
    metadata_default = resolved / "force-app" / "main" / "default"
    if not metadata_default.is_dir():
        return False, f"Salesforce metadata directory not found: {metadata_default}"
    return True, None


def validate_repo_path(repo_path: Path) -> tuple[bool, str | None]:
    """Return whether the path exists and contains a Git repository."""
    resolved = repo_path.resolve()
    if not resolved.exists():
        return False, f"Repository path does not exist: {resolved}"
    if not resolved.is_dir():
        return False, f"Repository path is not a directory: {resolved}"
    git_dir = resolved / ".git"
    if not git_dir.exists():
        return False, f"Path is not a Git repository: {resolved}"
    return True, None


def get_repository_status(
    metadata_path: Path,
    fetch: bool = False,
) -> GitRepositoryStatus:
    """
    Inspect Git branch, commit, working tree, and remote sync state.

    ``metadata_path`` is the Salesforce DX project root. Git operations use
    the nearest parent directory with a ``.git`` folder when the metadata
    root itself is not a Git repository.

    When ``fetch`` is True, runs ``git fetch`` before comparing with the remote.
    """
    metadata_root = metadata_path.resolve()
    git_root = find_git_root(metadata_root)
    if git_root is None:
        return GitRepositoryStatus(
            repo_path=metadata_root,
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
            error="No Git repository found for metadata path.",
        )

    valid, validation_error = validate_repo_path(git_root)
    if not valid:
        return GitRepositoryStatus(
            repo_path=metadata_root,
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
            error=validation_error,
        )

    try:
        branch_result = _run_git(git_root, "rev-parse", "--abbrev-ref", "HEAD")
        if branch_result.returncode != 0:
            raise RuntimeError(_sanitize_git_message(branch_result.stderr or branch_result.stdout))

        branch = branch_result.stdout.strip() or None

        hash_result = _run_git(git_root, "rev-parse", "HEAD")
        if hash_result.returncode != 0:
            raise RuntimeError(_sanitize_git_message(hash_result.stderr or hash_result.stdout))
        commit_hash = hash_result.stdout.strip() or None

        short_result = _run_git(git_root, "rev-parse", "--short", "HEAD")
        commit_hash_short = (
            short_result.stdout.strip() if short_result.returncode == 0 else None
        )

        date_result = _run_git(git_root, "log", "-1", "--format=%cI")
        last_commit_date = date_result.stdout.strip() if date_result.returncode == 0 else None

        status_result = _run_git(git_root, "status", "--porcelain")
        if status_result.returncode != 0:
            raise RuntimeError(_sanitize_git_message(status_result.stderr or status_result.stdout))
        working_tree_clean = not bool(status_result.stdout.strip())

        upstream_result = _run_git(
            git_root,
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{u}",
        )
        tracking_remote = upstream_result.returncode == 0
        ahead_count: int | None = None
        behind_count: int | None = None

        if fetch and tracking_remote:
            fetch_result = _run_git(git_root, "fetch", "--quiet")
            if fetch_result.returncode != 0:
                raise RuntimeError(_sanitize_git_message(fetch_result.stderr or fetch_result.stdout))

        if tracking_remote:
            count_result = _run_git(
                git_root,
                "rev-list",
                "--left-right",
                "--count",
                "@{u}...HEAD",
            )
            if count_result.returncode == 0:
                parts = count_result.stdout.strip().split()
                if len(parts) == 2:
                    behind_count = _parse_int(parts[0])
                    ahead_count = _parse_int(parts[1])

        sync_status = _resolve_sync_status(
            working_tree_clean=working_tree_clean,
            tracking_remote=tracking_remote,
            ahead_count=ahead_count,
            behind_count=behind_count,
        )

        return GitRepositoryStatus(
            repo_path=metadata_root,
            available=True,
            branch=branch,
            commit_hash=commit_hash,
            commit_hash_short=commit_hash_short,
            last_commit_date=last_commit_date,
            working_tree_clean=working_tree_clean,
            tracking_remote=tracking_remote,
            ahead_count=ahead_count,
            behind_count=behind_count,
            sync_status=sync_status,
        )
    except (subprocess.SubprocessError, OSError, RuntimeError) as exc:
        return GitRepositoryStatus(
            repo_path=metadata_root,
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
            error=_sanitize_git_message(str(exc)),
        )


def fetch_remote_updates(repo_path: Path) -> GitFetchResult:
    """Fetch from remote and return updated sync status without modifying the working tree."""
    status = get_repository_status(repo_path, fetch=True)
    if not status.available:
        return GitFetchResult(success=False, status=status, error=status.error)
    if status.error:
        return GitFetchResult(success=False, status=status, error=status.error)
    return GitFetchResult(success=True, status=status)


def pull_fast_forward_only(metadata_path: Path) -> GitPullResult:
    """
    Perform a fast-forward-only pull when the working tree is clean.

    Never runs reset, clean, merge, rebase, or force operations.
    """
    status = get_repository_status(metadata_path, fetch=True)
    if not status.available:
        return GitPullResult(
            success=False,
            fast_forward=False,
            status=status,
            message="Git repository is unavailable.",
            error=status.error,
        )

    git_root = find_git_root(metadata_path)
    if git_root is None:
        return GitPullResult(
            success=False,
            fast_forward=False,
            status=status,
            message="Git repository is unavailable.",
            error="No Git repository found for metadata path.",
        )

    if not status.tracking_remote:
        return GitPullResult(
            success=False,
            fast_forward=False,
            status=status,
            message="Current branch is not tracking a remote branch.",
        )

    if status.working_tree_clean is False:
        return GitPullResult(
            success=False,
            fast_forward=False,
            status=status,
            message="Local changes must be committed or stashed before pulling updates.",
        )

    behind = status.behind_count or 0
    if behind == 0:
        return GitPullResult(
            success=True,
            fast_forward=True,
            status=status,
            message="Repository is already up to date.",
        )

    ff_check = _run_git(git_root, "merge-base", "--is-ancestor", "HEAD", "@{u}")
    if ff_check.returncode != 0:
        refreshed = get_repository_status(metadata_path, fetch=False)
        return GitPullResult(
            success=False,
            fast_forward=False,
            status=refreshed,
            message=(
                "Salesforce updates require manual Git resolution. No files were changed."
            ),
        )

    pull_result = _run_git(git_root, "pull", "--ff-only", "--quiet")
    if pull_result.returncode != 0:
        refreshed = get_repository_status(metadata_path, fetch=False)
        error_text = _sanitize_git_message(pull_result.stderr or pull_result.stdout)
        if "Not possible to fast-forward" in error_text or "non-fast-forward" in error_text.lower():
            return GitPullResult(
                success=False,
                fast_forward=False,
                status=refreshed,
                message=(
                    "Salesforce updates require manual Git resolution. No files were changed."
                ),
                error=error_text or None,
            )
        return GitPullResult(
            success=False,
            fast_forward=False,
            status=refreshed,
            message="Git pull failed.",
            error=error_text or None,
        )

    refreshed = get_repository_status(metadata_path, fetch=False)
    return GitPullResult(
        success=True,
        fast_forward=True,
        status=refreshed,
        message="Salesforce repository updated successfully.",
    )


def _resolve_sync_status(
    *,
    working_tree_clean: bool,
    tracking_remote: bool,
    ahead_count: int | None,
    behind_count: int | None,
) -> SyncStatus:
    if not working_tree_clean:
        return SyncStatus.LOCAL_CHANGES
    if not tracking_remote:
        return SyncStatus.BRANCH_NOT_TRACKING
    if (behind_count or 0) > 0:
        return SyncStatus.UPDATES_AVAILABLE
    return SyncStatus.UP_TO_DATE
