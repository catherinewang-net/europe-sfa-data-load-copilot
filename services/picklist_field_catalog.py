"""Discover picklist and multipicklist fields from Salesforce metadata."""

from __future__ import annotations

from typing import Any

from adapters.sfdx_metadata.adapter import SfdxMetadataAdapter
from services.template_service import get_adapter


def _value_set_source(field_def) -> tuple[str, str | None]:
    if field_def.global_value_set:
        return "Global Value Set", field_def.global_value_set
    if field_def.standard_value_set:
        return "Standard Value Set", field_def.standard_value_set
    if field_def.inline_picklist_values:
        return "Inline Field Values", None
    return "Unknown", None


def _record_type_restrictions_available(
    adapter: SfdxMetadataAdapter,
    object_name: str,
    field_api_name: str,
    record_type_name: str | None,
) -> bool:
    if not record_type_name:
        return False
    return adapter.has_record_type_picklist_restriction(
        object_name,
        record_type_name,
        field_api_name,
    )


def get_picklist_fields(
    object_name: str,
    record_type_name: str | None = None,
    adapter: SfdxMetadataAdapter | None = None,
) -> list[dict[str, Any]]:
    """Return all picklist and multipicklist fields for a Salesforce object."""
    adapter = adapter or get_adapter()
    object_fields = adapter.get_object_fields(object_name)
    catalog: list[dict[str, Any]] = []

    for field_def in object_fields.values():
        if not field_def.is_picklist:
            continue

        value_set_source, value_set_name = _value_set_source(field_def)
        details = adapter.get_picklist_value_details(object_name, field_def.api_name)
        allowed_values = [value.api_name for value in details if value.is_active]
        labels = [value.label for value in details if value.is_active]

        record_type_values: list[str] = []
        has_record_type_restrictions = _record_type_restrictions_available(
            adapter,
            object_name,
            field_def.api_name,
            record_type_name,
        )
        if record_type_name and has_record_type_restrictions:
            record_type_values = adapter.get_allowed_values_for_record_type(
                object_name,
                record_type_name,
                field_def.api_name,
            )

        catalog.append({
            "object_api_name": object_name,
            "field_api_name": field_def.api_name,
            "field_label": field_def.label,
            "field_type": field_def.field_type,
            "value_set_source": value_set_source,
            "value_set_name": value_set_name,
            "record_type_restrictions_available": has_record_type_restrictions,
            "record_type_name": record_type_name,
            "record_type_allowed_values": record_type_values,
            "allowed_values": allowed_values,
            "labels": labels,
            "active_values": [
                {"api_name": value.api_name, "label": value.label, "is_active": value.is_active}
                for value in details
            ],
            "metadata_available": bool(details),
            "required": field_def.required,
        })

    return sorted(catalog, key=lambda item: item["field_api_name"].lower())


def build_picklist_metadata_debug_report(
    object_name: str,
    record_type_name: str | None = None,
    adapter: SfdxMetadataAdapter | None = None,
) -> dict[str, Any]:
    """Build a debug report for the picklist metadata debug panel."""
    adapter = adapter or get_adapter()
    object_fields = adapter.get_object_fields(object_name)
    picklist_fields = get_picklist_fields(object_name, record_type_name, adapter)

    picklists = [field for field in picklist_fields if field["field_type"].lower() == "picklist"]
    multipicklists = [
        field for field in picklist_fields
        if field["field_type"].lower() == "multipicklist"
    ]
    missing_value_sets = [
        field["field_api_name"]
        for field in picklist_fields
        if not field["metadata_available"]
    ]

    return {
        "object_name": object_name,
        "record_type_name": record_type_name,
        "object_field_count": len(object_fields),
        "picklist_field_count": len(picklists),
        "multipicklist_field_count": len(multipicklists),
        "picklist_field_api_names": [field["field_api_name"] for field in picklists],
        "multipicklist_field_api_names": [field["field_api_name"] for field in multipicklists],
        "fields": picklist_fields,
        "fields_with_missing_value_set_metadata": missing_value_sets,
    }
