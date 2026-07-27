"""Discover lookup/reference fields from Salesforce metadata for mapped columns."""

from __future__ import annotations

import re
from typing import Any

from adapters.sfdx_metadata.adapter import SfdxMetadataAdapter
from adapters.sfdx_metadata.models import FieldDefinition
from services.constants import (
    LOOKUP_METHOD_BUSINESS_KEY,
    LOOKUP_METHOD_EXTERNAL_ID,
    LOOKUP_METHOD_NAME,
    LOOKUP_METHOD_SALESFORCE_ID,
    LOOKUP_METHOD_UNKNOWN,
    MAPPING_STATUS_EXCLUDED,
    MAPPING_SOURCE_SALESFORCE,
)
from services.external_id_discovery_service import (
    IDENTIFIER_KIND_EXTERNAL_ID,
    discover_identifier_fields,
)
from services.template_service import get_adapter

LOOKUP_FIELD_TYPES = {"lookup", "reference", "masterdetail", "hierarchy"}
_SALESFORCE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9]{15}(?:[a-zA-Z0-9]{3})?$")


def is_lookup_field(field_def: FieldDefinition) -> bool:
    """Return True when metadata marks the field as a relationship."""
    return field_def.field_type.lower() in LOOKUP_FIELD_TYPES


def relationship_type(field_def: FieldDefinition) -> str:
    lowered = field_def.field_type.lower()
    if lowered == "masterdetail":
        return "Master-detail"
    if lowered == "hierarchy":
        return "Hierarchy"
    if lowered == "reference":
        return "Reference"
    return "Lookup"


def discover_mapped_lookup_fields(
    object_name: str,
    mapping_rows: list[dict[str, Any]],
    *,
    adapter: SfdxMetadataAdapter | None = None,
    metadata_source: str = MAPPING_SOURCE_SALESFORCE,
) -> list[dict[str, Any]]:
    """
    Return lookup field metadata for retained mapped API fields only.

    Lookup fields are identified from Salesforce field metadata, not column names.
    """
    adapter = adapter or get_adapter()
    object_fields = adapter.get_object_fields(object_name)
    retained_api_fields = _retained_api_fields(mapping_rows)
    discovered: list[dict[str, Any]] = []

    for api_name in sorted(retained_api_fields):
        field_def = object_fields.get(api_name)
        if field_def is None or not is_lookup_field(field_def):
            continue
        discovered.append(_lookup_field_entry(
            source_object=object_name,
            field_def=field_def,
            mapping_rows=mapping_rows,
            metadata_source=metadata_source,
        ))

    return discovered


def resolve_lookup_column(
    api_field: str,
    mapping_rows: list[dict[str, Any]],
    *,
    use_mapped_columns: bool = False,
    df_columns: list[str] | None = None,
) -> str | None:
    """Resolve the dataframe column containing lookup values."""
    if use_mapped_columns and df_columns and api_field in df_columns:
        return api_field

    for row in mapping_rows:
        if row.get("confirmed_api_field") != api_field:
            continue
        if row.get("status") == MAPPING_STATUS_EXCLUDED or row.get("action") == "exclude":
            continue
        uploaded = str(row.get("uploaded_column") or row.get("dit_column") or "").strip()
        if uploaded:
            return uploaded
    return api_field if df_columns and api_field in df_columns else None


def infer_matching_method(
    *,
    lookup_field: str,
    uploaded_value: str,
    referenced_object: str,
    adapter: SfdxMetadataAdapter | None = None,
    dependency_hint: str | None = None,
) -> tuple[str, str | None]:
    """
    Infer how a lookup value should be matched.

    Returns (matching_method, suggested_identifier_field).
    """
    adapter = adapter or get_adapter()
    value = str(uploaded_value or "").strip()
    if not value:
        return LOOKUP_METHOD_UNKNOWN, None

    if _looks_like_salesforce_id(value):
        return LOOKUP_METHOD_SALESFORCE_ID, "Id"

    if dependency_hint:
        return LOOKUP_METHOD_EXTERNAL_ID, dependency_hint

    lowered_field = lookup_field.lower()
    if lowered_field.endswith("id") and lookup_field != "Id":
        if lowered_field.endswith("extid__c") or "external" in lowered_field:
            return LOOKUP_METHOD_EXTERNAL_ID, lookup_field
        if lookup_field.endswith("Id"):
            return LOOKUP_METHOD_SALESFORCE_ID, "Id"

    identifier_fields = discover_identifier_fields(referenced_object, adapter)
    external_ids = [
        field["field_api_name"]
        for field in identifier_fields
        if IDENTIFIER_KIND_EXTERNAL_ID in field.get("identifier_kinds", [])
    ]
    if external_ids:
        if len(external_ids) == 1:
            return LOOKUP_METHOD_EXTERNAL_ID, external_ids[0]
        for candidate in external_ids:
            if candidate.lower() in lowered_field:
                return LOOKUP_METHOD_EXTERNAL_ID, candidate
        return LOOKUP_METHOD_EXTERNAL_ID, external_ids[0]

    if lowered_field.endswith("__c") and not lowered_field.endswith("id__c"):
        return LOOKUP_METHOD_BUSINESS_KEY, lookup_field

    if lookup_field == "Name" or lowered_field.endswith("name"):
        return LOOKUP_METHOD_NAME, "Name"

    return LOOKUP_METHOD_UNKNOWN, None


def is_plausible_lookup_value(value: str, matching_method: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if matching_method == LOOKUP_METHOD_SALESFORCE_ID:
        return bool(_SALESFORCE_ID_PATTERN.match(text))
    if matching_method in {LOOKUP_METHOD_EXTERNAL_ID, LOOKUP_METHOD_BUSINESS_KEY, LOOKUP_METHOD_NAME}:
        return len(text) <= 255
    return True


def _retained_api_fields(mapping_rows: list[dict[str, Any]]) -> set[str]:
    retained: set[str] = set()
    for row in mapping_rows:
        if row.get("status") == MAPPING_STATUS_EXCLUDED or row.get("action") == "exclude":
            continue
        api_field = row.get("confirmed_api_field")
        if api_field:
            retained.add(str(api_field))
    return retained


def _lookup_field_entry(
    *,
    source_object: str,
    field_def: FieldDefinition,
    mapping_rows: list[dict[str, Any]],
    metadata_source: str,
) -> dict[str, Any]:
    uploaded_column = resolve_lookup_column(field_def.api_name, mapping_rows)
    return {
        "source_object": source_object,
        "field_api_name": field_def.api_name,
        "field_label": field_def.label,
        "referenced_object": field_def.reference_to or "Unknown",
        "relationship_type": relationship_type(field_def),
        "required": field_def.required,
        "uses_salesforce_id": field_def.api_name.endswith("Id") and field_def.api_name != "Id",
        "metadata_source": metadata_source,
        "uploaded_column": uploaded_column,
    }


def _looks_like_salesforce_id(value: str) -> bool:
    return bool(_SALESFORCE_ID_PATTERN.match(str(value).strip()))
