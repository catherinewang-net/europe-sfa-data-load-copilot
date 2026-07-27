"""Filesystem-backed metadata provider wrapping the SFDX adapter."""

from __future__ import annotations

from pathlib import Path

from adapters.metadata_provider import MetadataProvider
from adapters.sfdx_metadata.adapter import SfdxMetadataAdapter
from adapters.sfdx_metadata.models import FieldDefinition, PicklistValue, TemplateDefinition


class RepositoryMetadataProvider:
    """Read-only metadata from a local SFDX project root or bundled snapshot directory."""

    def __init__(self, repo_root: Path) -> None:
        self._adapter = SfdxMetadataAdapter(repo_root)

    @property
    def repo_root(self) -> Path:
        return self._adapter.repo_root

    def get_template(self, template_name: str) -> TemplateDefinition | None:
        return self._adapter.get_template(template_name)

    def list_templates(self) -> list[TemplateDefinition]:
        return self._adapter.list_templates()

    def get_object_fields(self, object_name: str) -> dict[str, FieldDefinition]:
        return self._adapter.get_object_fields(object_name)

    def get_picklist_values(self, object_name: str, field_name: str) -> list[str]:
        return self._adapter.get_picklist_values(object_name, field_name)

    def get_picklist_value_details(
        self,
        object_name: str,
        field_name: str,
    ) -> list[PicklistValue]:
        return self._adapter.get_picklist_value_details(object_name, field_name)

    def get_allowed_values_for_record_type(
        self,
        object_name: str,
        record_type: str,
        field_name: str,
    ) -> list[str]:
        return self._adapter.get_allowed_values_for_record_type(
            object_name,
            record_type,
            field_name,
        )

    def get_record_type_names(self, object_name: str) -> list[str]:
        return self._adapter.get_record_type_names(object_name)

    def has_record_type_picklist_restriction(
        self,
        object_name: str,
        record_type_name: str,
        field_name: str,
    ) -> bool:
        return self._adapter.has_record_type_picklist_restriction(
            object_name,
            record_type_name,
            field_name,
        )

    @property
    def skipped_files(self) -> list[str]:
        return self._adapter.skipped_files

    @property
    def adapter(self) -> SfdxMetadataAdapter:
        """Underlying adapter for code paths that still expect SfdxMetadataAdapter."""
        return self._adapter


def as_metadata_provider(adapter: SfdxMetadataAdapter) -> MetadataProvider:
    """Wrap an existing adapter instance as a MetadataProvider."""
    provider = RepositoryMetadataProvider.__new__(RepositoryMetadataProvider)
    provider._adapter = adapter
    return provider
