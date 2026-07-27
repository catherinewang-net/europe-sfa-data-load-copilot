"""Data models for Salesforce DX metadata."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PicklistValue:
    api_name: str
    label: str
    is_active: bool = True

    @property
    def value(self) -> str:
        """Salesforce stored value / API Name."""
        return self.api_name

    @property
    def active(self) -> bool:
        return self.is_active


@dataclass(frozen=True)
class FieldDefinition:
    api_name: str
    label: str
    field_type: str
    required: bool
    global_value_set: str | None = None
    standard_value_set: str | None = None
    inline_picklist_values: tuple[str, ...] = field(default_factory=tuple)
    reference_to: str | None = None
    writeability: str = "Writeability unknown"
    external_id: bool = False
    unique: bool = False
    id_lookup: bool = False

    @property
    def is_picklist(self) -> bool:
        return self.field_type.lower() in {"picklist", "multipicklist"}

    @property
    def is_external_id_field(self) -> bool:
        return self.external_id or self.field_type.lower() == "externalid"

    @property
    def is_reliable_identifier(self) -> bool:
        return (
            self.api_name == "Id"
            or self.is_external_id_field
            or self.unique
            or self.id_lookup
        )

    @property
    def uses_global_value_set(self) -> bool:
        return bool(self.global_value_set)

    @property
    def has_inline_picklist_values(self) -> bool:
        return bool(self.inline_picklist_values)


@dataclass(frozen=True)
class TemplateDefinition:
    name: str
    developer_name: str
    object_api_name: str
    is_active: bool
    api_to_csv_label: dict[str, str]
    csv_label_to_api: dict[str, str]
    required_csv_labels: tuple[str, ...]

    @property
    def csv_headers(self) -> tuple[str, ...]:
        return tuple(self.api_to_csv_label.values())


@dataclass(frozen=True)
class RecordTypeDefinition:
    object_api_name: str
    name: str
    label: str
    picklist_values: dict[str, tuple[str, ...]]
