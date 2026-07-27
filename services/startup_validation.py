"""Startup validation and health checks for hosted deployments."""

from __future__ import annotations

from pathlib import Path

from core.config import (
    get_bundled_metadata_dir,
    get_deployment_mode,
    get_metadata_mode,
    get_salesforce_client_id,
    get_salesforce_redirect_uri,
    is_bundled_metadata_mode,
    is_hosted_deployment,
    resolve_metadata_repo_path,
)
from services.git_repository_service import validate_metadata_root


def validate_startup_metadata() -> tuple[bool, str | None]:
    """
    Validate that metadata is loadable at application startup.

    Returns (ok, error_message).
    """
    try:
        repo_path = resolve_metadata_repo_path()
    except RuntimeError as exc:
        return False, _format_metadata_path_error(str(exc))

    valid, error = validate_metadata_root(repo_path)
    if not valid:
        return False, error

    if is_bundled_metadata_mode():
        bundled_dir = get_bundled_metadata_dir()
        manifest = bundled_dir / "SNAPSHOT_MANIFEST.json"
        if not manifest.is_file():
            return False, (
                f"Bundled metadata manifest not found: {manifest}. "
                "Run scripts/bundle_metadata_snapshot.ps1, audit with "
                "python scripts/audit_bundled_metadata.py, then commit bundled_metadata/."
            )
        sfdx_project = bundled_dir / "sfdx-project.json"
        metadata_root = bundled_dir / "force-app" / "main" / "default"
        if not sfdx_project.is_file() or not metadata_root.is_dir():
            return False, (
                "Bundled metadata snapshot is incomplete. "
                "Rebuild with scripts/bundle_metadata_snapshot.ps1 before deploying."
            )

    return True, None


def get_deployment_startup_notices() -> list[str]:
    """Return non-blocking deployment hints shown after successful metadata validation."""
    notices: list[str] = []

    if is_bundled_metadata_mode():
        notices.append(
            "Metadata mode: bundled snapshot (no local EUSFA clone required)."
        )
    else:
        notices.append(
            f"Metadata mode: local clone at `{resolve_metadata_repo_path()}`."
        )

    client_id = get_salesforce_client_id()
    redirect_uri = get_salesforce_redirect_uri()
    if client_id and redirect_uri:
        notices.append(
            "Live Salesforce connection is available — users can connect for live org validation."
        )
    elif client_id or redirect_uri:
        notices.append(
            "Live Salesforce connection is partially configured and unavailable until "
            "OAuth client ID and redirect URI are both set."
        )
    else:
        notices.append(
            "Live Salesforce connection is not configured — validation uses the approved "
            "metadata snapshot."
        )

    if is_hosted_deployment() and get_deployment_mode() in {"demo", "production"}:
        notices.append(
            f"Deployment mode: {get_deployment_mode()} "
            f"(metadata mode defaults to {get_metadata_mode()})."
        )

    return notices


def _format_metadata_path_error(message: str) -> str:
    if is_bundled_metadata_mode():
        return (
            f"{message} For Streamlit Community Cloud, set METADATA_MODE=bundled in "
            "Advanced settings and commit an audited bundled_metadata/ snapshot."
        )
    if is_hosted_deployment():
        return (
            f"{message} Hosted deployments require METADATA_MODE=bundled or "
            "EUSFA_SFDX_REPO_PATH when using METADATA_MODE=local."
        )
    return message


def health_check(repo_path: Path | None = None) -> tuple[bool, str]:
    """
    Lightweight health probe used by scripts/healthcheck.py and container probes.

    Returns (healthy, detail_message).
    """
    path = repo_path or resolve_metadata_repo_path()
    valid, error = validate_metadata_root(path)
    if not valid:
        return False, error or "Metadata root invalid"
    return True, f"Metadata root OK: {path}"
