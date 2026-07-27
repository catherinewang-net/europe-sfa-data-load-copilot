"""Discover reliable identifier fields from Salesforce metadata."""

from __future__ import annotations

from typing import Any

from adapters.sfdx_metadata.adapter import SfdxMetadataAdapter
from adapters.sfdx_metadata.models import FieldDefinition
from services.template_service import get_adapter


IDENTIFIER_KIND_EXTERNAL_ID = "External ID"
IDENTIFIER_KIND_UNIQUE = "Unique"
IDENTIFIER_KIND_ID_LOOKUP = "Id Lookup"
IDENTIFIER_KIND_SALESFORCE_ID = "Salesforce Id"
IDENTIFIER_KIND_BUSINESS_KEY = "Business Key"


def discover_identifier_fields(
    object_name: str,
    adapter: SfdxMetadataAdapter | None = None,
    *,
    mapped_api_fields: set[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Return identifier candidates discovered from metadata.

    Includes External ID, Unique, Id Lookup, Salesforce Id, and mapped business keys.
    """
    adapter = adapter or get_adapter()
    object_fields = adapter.get_object_fields(object_name)
    mapped_api_fields = mapped_api_fields or set()
    discovered: list[dict[str, Any]] = []

    for api_name, field_def in sorted(object_fields.items(), key=lambda item: item[0].lower()):
        kinds = _identifier_kinds(field_def)
        if not kinds:
            continue
        discovered.append(_field_entry(object_name, field_def, kinds))

    if "Id" not in object_fields:
        discovered.insert(0, {
            "object_api_name": object_name,
            "field_api_name": "Id",
            "field_label": "Record ID",
            "field_type": "Id",
            "identifier_kinds": [IDENTIFIER_KIND_SALESFORCE_ID],
            "is_reliable_identifier": True,
            "metadata_source": "Standard Field Supplement",
        })

    for api_name in sorted(mapped_api_fields):
        if api_name in object_fields:
            continue
        if api_name.endswith("_Id__c") or api_name.endswith("ExtID__c"):
            discovered.append({
                "object_api_name": object_name,
                "field_api_name": api_name,
                "field_label": api_name,
                "field_type": "Text",
                "identifier_kinds": [IDENTIFIER_KIND_BUSINESS_KEY],
                "is_reliable_identifier": True,
                "metadata_source": "Mapped Column Heuristic",
            })

    return _dedupe_discovered_fields(discovered)


def discover_external_id_fields(
    object_name: str,
    adapter: SfdxMetadataAdapter | None = None,
) -> list[dict[str, Any]]:
    """Return only External ID candidates for an object."""
    return [
        field
        for field in discover_identifier_fields(object_name, adapter)
        if IDENTIFIER_KIND_EXTERNAL_ID in field.get("identifier_kinds", [])
    ]


def default_identifier_field(
    object_name: str,
    adapter: SfdxMetadataAdapter | None = None,
    *,
    mapped_api_fields: set[str] | None = None,
) -> str | None:
    """Pick the best default identifier field for live lookup."""
    candidates = discover_identifier_fields(
        object_name,
        adapter,
        mapped_api_fields=mapped_api_fields,
    )
    for preferred_kind in (
        IDENTIFIER_KIND_EXTERNAL_ID,
        IDENTIFIER_KIND_UNIQUE,
        IDENTIFIER_KIND_ID_LOOKUP,
        IDENTIFIER_KIND_BUSINESS_KEY,
    ):
        for candidate in candidates:
            if preferred_kind in candidate.get("identifier_kinds", []):
                return candidate["field_api_name"]
    return None


def resolve_identifier_column(
    identifier_field: str,
    mapping_rows: list[dict[str, Any]],
    *,
    use_mapped_columns: bool = False,
    df_columns: list[str] | None = None,
) -> str | None:
    """Resolve the dataframe column containing identifier values."""
    if use_mapped_columns and df_columns and identifier_field in df_columns:
        return identifier_field

    for row in mapping_rows:
        api_field = row.get("confirmed_api_field")
        if api_field != identifier_field:
            continue
        uploaded = str(row.get("uploaded_column") or row.get("dit_column") or "").strip()
        if uploaded:
            return uploaded
    return identifier_field if df_columns and identifier_field in df_columns else None


def _identifier_kinds(field_def: FieldDefinition) -> list[str]:
    kinds: list[str] = []
    if field_def.api_name == "Id":
        kinds.append(IDENTIFIER_KIND_SALESFORCE_ID)
    if field_def.is_external_id_field:
        kinds.append(IDENTIFIER_KIND_EXTERNAL_ID)
    if field_def.unique:
        kinds.append(IDENTIFIER_KIND_UNIQUE)
    if field_def.id_lookup:
        kinds.append(IDENTIFIER_KIND_ID_LOOKUP)
    return kinds


def _field_entry(
    object_name: str,
    field_def: FieldDefinition,
    kinds: list[str],
) -> dict[str, Any]:
    return {
        "object_api_name": object_name,
        "field_api_name": field_def.api_name,
        "field_label": field_def.label,
        "field_type": field_def.field_type,
        "identifier_kinds": kinds,
        "is_reliable_identifier": field_def.is_reliable_identifier,
        "metadata_source": "Object Metadata",
    }


def _dedupe_discovered_fields(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for field in fields:
        api_name = field["field_api_name"]
        if api_name in seen:
            continue
        seen.add(api_name)
        deduped.append(field)
    return deduped
