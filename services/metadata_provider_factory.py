"""Factory for metadata providers based on deployment configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from adapters.metadata_provider import MetadataProvider
from adapters.repository_metadata_provider import RepositoryMetadataProvider
from adapters.sfdx_metadata.adapter import SfdxMetadataAdapter
from adapters.sfdx_metadata.models import FieldDefinition, PicklistValue, TemplateDefinition
from core.config import get_metadata_mode, resolve_metadata_repo_path
from services.salesforce.hybrid_metadata_provider import HybridMetadataProvider
from services.salesforce.live_metadata_provider import LiveSalesforceMetadataProvider
from services.salesforce_oauth_service import SF_ORG_ID, is_connected


def resolve_active_metadata_mode(session_state: dict[str, Any] | None) -> str:
    """Return ``live`` when OAuth is connected, otherwise ``snapshot``."""
    if session_state is not None and is_connected(session_state):
        return "live"
    return "snapshot"

_SESSION_ADAPTERS: dict[str, CopilotMetadataAdapter] = {}


def get_metadata_repo_path(repo_root: Path | None = None) -> Path:
    """Resolve the metadata filesystem root for the current deployment mode."""
    if repo_root is not None:
        return repo_root.resolve()
    return resolve_metadata_repo_path()


def create_metadata_provider(
    repo_root: Path | None = None,
    *,
    session_state: dict[str, Any] | None = None,
) -> MetadataProvider:
    """
    Return a metadata provider for the configured mode.

    When the browser session has an active Salesforce OAuth connection, field and
    picklist metadata come from the connected org; template definitions still use
    the local/bundled repository snapshot.
    """
    resolved = get_metadata_repo_path(repo_root)
    mode = get_metadata_mode()
    if mode not in {"local", "bundled"}:
        raise ValueError(f"Unsupported METADATA_MODE: {mode!r}")

    repository = RepositoryMetadataProvider(resolved)
    if session_state is not None and is_connected(session_state):
        live = LiveSalesforceMetadataProvider(session_state, fallback_repo_root=resolved)
        return HybridMetadataProvider(live, repository)
    return repository


def create_hybrid_metadata_provider(
    session_state: dict[str, Any],
    repo_root: Path | None = None,
) -> HybridMetadataProvider | RepositoryMetadataProvider:
    """Return hybrid live+repository provider when OAuth session is active."""
    provider = create_metadata_provider(repo_root, session_state=session_state)
    if isinstance(provider, HybridMetadataProvider):
        return provider
    return provider


class CopilotMetadataAdapter:
    """Delegates metadata lookups to repository or live OAuth-backed providers."""

    def __init__(self, provider: MetadataProvider) -> None:
        self._provider = provider

    @property
    def repo_root(self) -> Path:
        return self._provider.repo_root

    @property
    def skipped_files(self) -> list[str]:
        return self._provider.skipped_files

    @property
    def adapter(self) -> SfdxMetadataAdapter | None:
        if isinstance(self._provider, RepositoryMetadataProvider):
            return self._provider.adapter
        if isinstance(self._provider, HybridMetadataProvider):
            return self._provider.repository_provider.adapter
        return None

    def get_template(self, template_name: str) -> TemplateDefinition | None:
        return self._provider.get_template(template_name)

    def list_templates(self) -> list[TemplateDefinition]:
        return self._provider.list_templates()

    def get_object_fields(self, object_name: str) -> dict[str, FieldDefinition]:
        return self._provider.get_object_fields(object_name)

    def get_picklist_values(self, object_name: str, field_name: str) -> list[str]:
        return self._provider.get_picklist_values(object_name, field_name)

    def get_picklist_value_details(
        self,
        object_name: str,
        field_name: str,
    ) -> list[PicklistValue]:
        return self._provider.get_picklist_value_details(object_name, field_name)

    def get_allowed_values_for_record_type(
        self,
        object_name: str,
        record_type: str,
        field_name: str,
    ) -> list[str]:
        return self._provider.get_allowed_values_for_record_type(
            object_name,
            record_type,
            field_name,
        )

    def get_record_type_names(self, object_name: str) -> list[str]:
        return self._provider.get_record_type_names(object_name)

    def has_record_type_picklist_restriction(
        self,
        object_name: str,
        record_type_name: str,
        field_name: str,
    ) -> bool:
        return self._provider.has_record_type_picklist_restriction(
            object_name,
            record_type_name,
            field_name,
        )


def get_metadata_adapter(repo_root: Path | None = None) -> CopilotMetadataAdapter:
    """
    Return a session-aware metadata adapter.

    Uses live Salesforce Describe/UI API when OAuth-connected; otherwise the
    configured local or bundled repository snapshot.
    """
    resolved_root = (repo_root or resolve_metadata_repo_path()).resolve()
    session_state = _current_session_state()
    cache_key = _adapter_cache_key(resolved_root, session_state)
    adapter = _SESSION_ADAPTERS.get(cache_key)
    if adapter is None:
        provider = create_metadata_provider(resolved_root, session_state=session_state)
        adapter = CopilotMetadataAdapter(provider)
        _SESSION_ADAPTERS[cache_key] = adapter
    return adapter


def clear_metadata_adapter_cache() -> None:
    """Clear the in-process metadata adapter cache (mainly for tests)."""
    _SESSION_ADAPTERS.clear()


def _current_session_state():
    try:
        import streamlit as st

        return st.session_state
    except Exception:
        return None


def _adapter_cache_key(repo_root: Path, session_state) -> str:
    base = str(repo_root)
    if session_state is not None and is_connected(session_state):
        org_id = session_state.get(SF_ORG_ID) or "connected"
        return f"{base}:live:{org_id}"
    return base
