"""Hybrid metadata provider: live org fields + repository templates."""

from __future__ import annotations

from pathlib import Path

from adapters.repository_metadata_provider import RepositoryMetadataProvider
from adapters.sfdx_metadata.models import FieldDefinition, PicklistValue, TemplateDefinition
from services.salesforce.live_metadata_provider import LiveSalesforceMetadataProvider


class HybridMetadataProvider:
    """Uses live Salesforce for object metadata; repository for template definitions."""

    def __init__(
        self,
        live: LiveSalesforceMetadataProvider,
        repository: RepositoryMetadataProvider,
    ) -> None:
        self._live = live
        self._repository = repository

    @property
    def repo_root(self) -> Path:
        return self._repository.repo_root

    @property
    def skipped_files(self) -> list[str]:
        return self._repository.skipped_files

    @property
    def live_provider(self) -> LiveSalesforceMetadataProvider:
        return self._live

    @property
    def repository_provider(self) -> RepositoryMetadataProvider:
        return self._repository

    def refresh_metadata(self) -> None:
        self._live.refresh_metadata()

    def get_template(self, template_name: str) -> TemplateDefinition | None:
        return self._repository.get_template(template_name)

    def list_templates(self) -> list[TemplateDefinition]:
        return self._repository.list_templates()

    def get_object_fields(self, object_name: str) -> dict[str, FieldDefinition]:
        return self._live.get_object_fields(object_name)

    def get_picklist_values(self, object_name: str, field_name: str) -> list[str]:
        return self._live.get_picklist_values(object_name, field_name)

    def get_picklist_value_details(
        self,
        object_name: str,
        field_name: str,
    ) -> list[PicklistValue]:
        return self._live.get_picklist_value_details(object_name, field_name)

    def get_allowed_values_for_record_type(
        self,
        object_name: str,
        record_type: str,
        field_name: str,
    ) -> list[str]:
        return self._live.get_allowed_values_for_record_type(object_name, record_type, field_name)

    def get_record_type_names(self, object_name: str) -> list[str]:
        return self._live.get_record_type_names(object_name)

    def has_record_type_picklist_restriction(
        self,
        object_name: str,
        record_type_name: str,
        field_name: str,
    ) -> bool:
        return self._live.has_record_type_picklist_restriction(
            object_name,
            record_type_name,
            field_name,
        )
