"""Metadata cache refresh and health reporting for the SFDX adapter."""



from __future__ import annotations



from dataclasses import dataclass

from datetime import datetime, timezone

from pathlib import Path

from typing import Any



from adapters.sfdx_metadata.adapter import SfdxMetadataAdapter
from services.metadata_provider_factory import (
    CopilotMetadataAdapter,
    clear_metadata_adapter_cache,
    get_metadata_adapter,
)

from core.config import resolve_metadata_repo_path

from services.git_repository_service import (
    GitRepositoryStatus,
    get_repository_status,
    validate_metadata_root,
)

from services.metadata_snapshot_service import (

    MetadataChangeSummary,

    MetadataSnapshot,

    capture_metadata_snapshot,

    compare_metadata_snapshots,

)

from services.template_service import _reset_template_dropdown_cache





@dataclass(frozen=True)

class MetadataCounts:

    objects: int

    fields: int

    picklists: int

    templates: int





@dataclass(frozen=True)

class MetadataHealth:

    repo_path: Path

    adapter_available: bool

    adapter_status: str

    counts: MetadataCounts

    skipped_files: list[str]

    git_status: GitRepositoryStatus

    error: str | None = None





@dataclass(frozen=True)

class MetadataRefreshResult:

    success: bool

    refreshed_at: datetime

    commit_hash: str | None

    adapter_status: str

    counts: MetadataCounts

    skipped_files: list[str]

    git_status: GitRepositoryStatus

    previous_counts: MetadataCounts | None = None

    previous_commit_hash: str | None = None

    change_summary: MetadataChangeSummary | None = None

    error: str | None = None





def _require_sfdx_adapter(adapter: CopilotMetadataAdapter) -> SfdxMetadataAdapter:
    sfdx = adapter.adapter
    if sfdx is None:
        raise RuntimeError("Repository-backed SFDX adapter is required for metadata refresh.")
    return sfdx


def _count_metadata(adapter: SfdxMetadataAdapter) -> MetadataCounts:

    loader = adapter._loader

    object_count = len(loader.object_fields)

    field_count = sum(len(fields) for fields in loader.object_fields.values())

    picklist_count = 0

    for fields in loader.object_fields.values():

        for field in fields.values():

            if (

                field.inline_picklist_values

                or field.global_value_set

                or field.standard_value_set

                or field.field_type in {"Picklist", "MultiselectPicklist"}

            ):

                picklist_count += 1

    template_count = len(adapter.list_templates())

    return MetadataCounts(

        objects=object_count,

        fields=field_count,

        picklists=picklist_count,

        templates=template_count,

    )





def _adapter_status_label(adapter: SfdxMetadataAdapter, error: str | None) -> str:

    if error:

        return "Error"

    if adapter.skipped_files:

        return "Loaded with warnings"

    return "Healthy"





def _capture_existing_snapshot(

    repo_path: Path,

    commit_hash: str | None,

) -> MetadataSnapshot | None:

    try:

        adapter = get_metadata_adapter(repo_path)

        return capture_metadata_snapshot(_require_sfdx_adapter(adapter), commit_hash)

    except Exception:

        return None





def get_metadata_health(repo_path: Path | None = None) -> MetadataHealth:

    """Return adapter health and metadata counts without clearing the cache."""

    resolved = (repo_path or resolve_metadata_repo_path()).resolve()

    metadata_valid, metadata_error = validate_metadata_root(resolved)

    git_status = get_repository_status(resolved)

    error: str | None = None if metadata_valid else metadata_error

    adapter_available = False

    adapter_status = "Unavailable"

    counts = MetadataCounts(objects=0, fields=0, picklists=0, templates=0)

    skipped_files: list[str] = []



    if metadata_valid:

        try:

            adapter = get_metadata_adapter(resolved)

            sfdx_adapter = _require_sfdx_adapter(adapter)

            counts = _count_metadata(sfdx_adapter)

            skipped_files = list(adapter.skipped_files)

            adapter_available = True

            adapter_status = _adapter_status_label(sfdx_adapter, None)

        except Exception as exc:

            error = str(exc)

            adapter_status = "Error"



    return MetadataHealth(

        repo_path=resolved,

        adapter_available=adapter_available,

        adapter_status=adapter_status,

        counts=counts,

        skipped_files=skipped_files,

        git_status=git_status,

        error=error,

    )





def refresh_metadata(repo_path: Path | None = None) -> MetadataRefreshResult:

    """

    Clear the in-process adapter cache and reload metadata from disk.



    Does not run Git fetch or pull.

    """

    resolved = (repo_path or resolve_metadata_repo_path()).resolve()

    refreshed_at = datetime.now(timezone.utc)

    git_status = get_repository_status(resolved)



    previous_snapshot = _capture_existing_snapshot(resolved, git_status.commit_hash)

    previous_counts = previous_snapshot.counts if previous_snapshot else None

    previous_commit_hash = previous_snapshot.commit_hash if previous_snapshot else None



    clear_metadata_adapter_cache()

    _reset_template_dropdown_cache()



    metadata_valid, metadata_error = validate_metadata_root(resolved)

    error: str | None = None if metadata_valid else metadata_error

    counts = MetadataCounts(objects=0, fields=0, picklists=0, templates=0)

    skipped_files: list[str] = []

    adapter_status = "Unavailable"

    change_summary: MetadataChangeSummary | None = None



    try:

        if not metadata_valid:

            raise FileNotFoundError(metadata_error or "Invalid metadata root.")

        adapter = get_metadata_adapter(resolved)

        sfdx_adapter = _require_sfdx_adapter(adapter)

        counts = _count_metadata(sfdx_adapter)

        skipped_files = list(adapter.skipped_files)

        adapter_status = _adapter_status_label(sfdx_adapter, None)

        new_snapshot = capture_metadata_snapshot(sfdx_adapter, git_status.commit_hash)

        change_summary = compare_metadata_snapshots(previous_snapshot, new_snapshot)

        success = True

    except Exception as exc:

        error = str(exc)

        adapter_status = "Error"

        success = False



    return MetadataRefreshResult(

        success=success,

        refreshed_at=refreshed_at,

        commit_hash=git_status.commit_hash,

        adapter_status=adapter_status,

        counts=counts,

        skipped_files=skipped_files,

        git_status=git_status,

        previous_counts=previous_counts,

        previous_commit_hash=previous_commit_hash,

        change_summary=change_summary,

        error=error,

    )





def is_metadata_connected(health: MetadataHealth) -> bool:
    """
    Return True when the metadata root is valid and the SFDX adapter loads.

    Git availability does not affect metadata connection status.
    """
    metadata_valid, _ = validate_metadata_root(health.repo_path)
    return metadata_valid and health.adapter_available


def metadata_health_summary(health: MetadataHealth) -> dict[str, Any]:

    """Serialize health information for UI layers and downloadable reports."""

    return {

        "adapter_available": health.adapter_available,

        "adapter_status": health.adapter_status,

        "counts": {

            "objects": health.counts.objects,

            "fields": health.counts.fields,

            "picklists": health.counts.picklists,

            "templates": health.counts.templates,

        },

        "skipped_file_count": len(health.skipped_files),

        "git_status": health.git_status.sync_status.value,

        "commit_hash": health.git_status.commit_hash,

        "commit_hash_short": health.git_status.commit_hash_short,

        "branch": health.git_status.branch,

        "last_commit_date": health.git_status.last_commit_date,

    }





def serialize_change_summary(summary: MetadataChangeSummary | None) -> dict[str, Any] | None:

    """Convert a change summary into a JSON-safe dict for session storage."""

    if summary is None:

        return None

    return {

        "has_changes": summary.has_changes,

        "display_lines": summary.display_lines(),

        "picklist_values_added": list(summary.picklist_values_added),

        "picklist_values_removed": list(summary.picklist_values_removed),

        "fields_added": list(summary.fields_added),

        "fields_removed": list(summary.fields_removed),

        "record_type_changes": list(summary.record_type_changes),

        "templates_added": list(summary.templates_added),

        "templates_removed": list(summary.templates_removed),

        "templates_updated": list(summary.templates_updated),

    }





def serialize_refresh_result(result: MetadataRefreshResult) -> dict[str, Any]:

    """Serialize refresh feedback without exposing unnecessary local paths."""

    return {

        "success": result.success,

        "commit_hash": result.commit_hash,

        "previous_commit_hash": result.previous_commit_hash,

        "adapter_status": result.adapter_status,

        "counts": {

            "objects": result.counts.objects,

            "fields": result.counts.fields,

            "picklists": result.counts.picklists,

            "templates": result.counts.templates,

        },

        "previous_counts": None

        if result.previous_counts is None

        else {

            "objects": result.previous_counts.objects,

            "fields": result.previous_counts.fields,

            "picklists": result.previous_counts.picklists,

            "templates": result.previous_counts.templates,

        },

        "skipped_file_count": len(result.skipped_files),

        "error": result.error,

        "change_summary": serialize_change_summary(result.change_summary),

    }


