"""Metadata provider protocol for modular Salesforce metadata access."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from adapters.sfdx_metadata.models import FieldDefinition, PicklistValue, TemplateDefinition


@runtime_checkable
class MetadataProvider(Protocol):
    """
    Read-only metadata access surface shared by local SFDX clones and bundled snapshots.

    Matches the public API of SfdxMetadataAdapter so callers can migrate gradually.
    """

    @property
    def repo_root(self) -> Path: ...

    def get_template(self, template_name: str) -> TemplateDefinition | None: ...

    def list_templates(self) -> list[TemplateDefinition]: ...

    def get_object_fields(self, object_name: str) -> dict[str, FieldDefinition]: ...

    def get_picklist_values(self, object_name: str, field_name: str) -> list[str]: ...

    def get_picklist_value_details(
        self,
        object_name: str,
        field_name: str,
    ) -> list[PicklistValue]: ...

    def get_allowed_values_for_record_type(
        self,
        object_name: str,
        record_type: str,
        field_name: str,
    ) -> list[str]: ...

    def get_record_type_names(self, object_name: str) -> list[str]: ...

    def has_record_type_picklist_restriction(
        self,
        object_name: str,
        record_type_name: str,
        field_name: str,
    ) -> bool: ...

    @property
    def skipped_files(self) -> list[str]: ...
