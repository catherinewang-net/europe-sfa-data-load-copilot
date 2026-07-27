"""Low-level read-only metadata adapter over a local SFDX repository."""

from __future__ import annotations

from pathlib import Path

from core.config import resolve_metadata_repo_path
from adapters.sfdx_metadata.loader import SfdxMetadataLoader
from adapters.sfdx_metadata.models import FieldDefinition, PicklistValue, TemplateDefinition


class SfdxMetadataAdapter:
    """
    Read-only adapter over the local EUSFA SF Salesforce DX repository.

    Metadata is loaded once per adapter instance and reused for all lookups.
    """

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve()
        self._loader = SfdxMetadataLoader(self.repo_root)

    @classmethod
    def from_default_repo(cls) -> SfdxMetadataAdapter:
        return cls(resolve_metadata_repo_path())

    def get_template(self, template_name: str) -> TemplateDefinition | None:
        """Return a Template_Config__mdt definition by template label or developer name."""
        if not template_name:
            return None
        return self._loader.templates.get(template_name.strip().lower())

    def list_templates(self) -> list[TemplateDefinition]:
        """Return unique active template definitions."""
        seen: set[str] = set()
        templates: list[TemplateDefinition] = []
        for template in self._loader.templates.values():
            key = template.developer_name
            if key in seen:
                continue
            seen.add(key)
            if template.is_active:
                templates.append(template)
        return sorted(templates, key=lambda item: item.name.lower())

    def get_object_fields(self, object_name: str) -> dict[str, FieldDefinition]:
        """Return field metadata for a Salesforce object."""
        if not object_name:
            return {}
        return dict(self._loader.object_fields.get(object_name, {}))

    def get_picklist_values(self, object_name: str, field_name: str) -> list[str]:
        """
        Return active picklist API values for a field.

        Resolution order:
        1. Inline field picklist values
        2. Referenced Global Value Set
        3. Referenced or inferred Standard Value Set
        """
        values = self._resolve_picklist_values(object_name, field_name)
        return [value.api_name for value in values if value.is_active]

    def get_picklist_value_details(
        self,
        object_name: str,
        field_name: str,
    ) -> list[PicklistValue]:
        """Return picklist values with stored value (API Name), label, and active flag."""
        return list(self._resolve_picklist_values(object_name, field_name))

    def get_allowed_values_for_record_type(
        self,
        object_name: str,
        record_type: str,
        field_name: str,
    ) -> list[str]:
        """
        Return picklist values allowed for a record type.

        Falls back to object-level picklist values when no record-type restriction
        exists (for example Key Account, which has no dedicated record type file).
        """
        normalized_record_type = self._normalize_record_type_name(record_type)
        record_type_def = self._loader.record_types.get((object_name, normalized_record_type))
        if record_type_def:
            allowed = record_type_def.picklist_values.get(field_name)
            if allowed:
                return list(allowed)
        return self.get_picklist_values(object_name, field_name)

    def get_record_type_names(self, object_name: str) -> list[str]:
        """Return known record type names for an object."""
        names: set[str] = set()
        for (obj_name, record_type_name), record_type in self._loader.record_types.items():
            if obj_name == object_name:
                names.add(record_type.name)
        return sorted(names)

    def has_record_type_picklist_restriction(
        self,
        object_name: str,
        record_type_name: str,
        field_name: str,
    ) -> bool:
        """Return True when record-type-specific picklist values exist for a field."""
        normalized_record_type = self._normalize_record_type_name(record_type_name)
        record_type_def = self._loader.record_types.get((object_name, normalized_record_type))
        if record_type_def is None:
            return False
        return field_name in record_type_def.picklist_values

    @property
    def skipped_files(self) -> list[str]:
        """Metadata files that could not be parsed and were skipped."""
        return list(self._loader.skipped_files)

    def _resolve_picklist_values(
        self,
        object_name: str,
        field_name: str,
    ) -> list[PicklistValue]:
        field = self._loader.object_fields.get(object_name, {}).get(field_name)
        if field is None:
            return []

        if field.inline_picklist_values:
            return [
                PicklistValue(api_name=value, label=value, is_active=True)
                for value in field.inline_picklist_values
            ]

        if field.global_value_set:
            return list(self._loader.global_value_sets.get(field.global_value_set, ()))

        if field.standard_value_set:
            return list(self._loader.standard_value_sets.get(field.standard_value_set, ()))

        return []

    @staticmethod
    def _normalize_record_type_name(record_type: str) -> str:
        normalized = record_type.strip().lower()
        aliases = {
            "customers": "customer",
            "wholesalers": "wholesaler",
            "prospects": "prospect",
            "payers": "payer",
            "key account": "key account",
            "key accounts": "key account",
        }
        return aliases.get(normalized, normalized)


def get_sfdx_adapter(repo_path: Path | None = None) -> SfdxMetadataAdapter:
    """Return a low-level SFDX metadata adapter for a repository path."""
    resolved = (repo_path or resolve_metadata_repo_path()).resolve()
    return SfdxMetadataAdapter(resolved)
