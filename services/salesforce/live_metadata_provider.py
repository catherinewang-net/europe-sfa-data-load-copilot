"""Live Salesforce metadata via REST Describe and UI API (OAuth session)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

from adapters.sfdx_metadata.models import FieldDefinition, PicklistValue, TemplateDefinition
from core.config import get_salesforce_api_version
from services.salesforce_oauth_service import get_session_auth, mark_metadata_refreshed

_SF_TYPE_LABELS: dict[str, str] = {
    "string": "Text",
    "textarea": "LongTextArea",
    "boolean": "Checkbox",
    "int": "Number",
    "double": "Number",
    "currency": "Currency",
    "percent": "Percent",
    "date": "Date",
    "datetime": "DateTime",
    "email": "Email",
    "phone": "Phone",
    "url": "Url",
    "picklist": "Picklist",
    "multipicklist": "MultiselectPicklist",
    "reference": "Lookup",
    "id": "Id",
    "address": "Address",
    "location": "Location",
}


class LiveSalesforceMetadataProvider:
    """Read-only metadata from the connected user's Salesforce org."""

    def __init__(
        self,
        session_state: dict[str, Any],
        *,
        fallback_repo_root: Path,
    ) -> None:
        self._session_state = session_state
        self._fallback_repo_root = fallback_repo_root.resolve()
        self._describe_cache: dict[str, dict[str, Any]] = {}
        self._global_describe: dict[str, Any] | None = None
        self._record_type_id_cache: dict[tuple[str, str], str] = {}
        self._rt_picklist_cache: dict[tuple[str, str, str], tuple[str, ...]] = {}

    @property
    def repo_root(self) -> Path:
        return self._fallback_repo_root

    @property
    def skipped_files(self) -> list[str]:
        return []

    def clear_cache(self) -> None:
        self._describe_cache.clear()
        self._global_describe = None
        self._record_type_id_cache.clear()
        self._rt_picklist_cache.clear()

    def refresh_metadata(self) -> None:
        self.clear_cache()
        mark_metadata_refreshed(self._session_state)

    def get_template(self, template_name: str) -> TemplateDefinition | None:
        return None

    def list_templates(self) -> list[TemplateDefinition]:
        return []

    def get_object_fields(self, object_name: str) -> dict[str, FieldDefinition]:
        if not object_name:
            return {}
        describe = self._get_object_describe(object_name)
        fields: dict[str, FieldDefinition] = {}
        for raw in describe.get("fields") or []:
            if not raw.get("name"):
                continue
            field = self._field_from_describe(raw)
            fields[field.api_name] = field
        return fields

    def get_picklist_values(self, object_name: str, field_name: str) -> list[str]:
        return [
            value.api_name
            for value in self.get_picklist_value_details(object_name, field_name)
            if value.is_active
        ]

    def get_picklist_value_details(
        self,
        object_name: str,
        field_name: str,
    ) -> list[PicklistValue]:
        describe = self._get_object_describe(object_name)
        for raw in describe.get("fields") or []:
            if raw.get("name") != field_name:
                continue
            return self._picklist_values_from_field(raw)
        return []

    def get_allowed_values_for_record_type(
        self,
        object_name: str,
        record_type: str,
        field_name: str,
    ) -> list[str]:
        cache_key = (object_name, self._normalize_record_type_name(record_type), field_name)
        cached = self._rt_picklist_cache.get(cache_key)
        if cached is not None:
            return list(cached)

        record_type_id = self._resolve_record_type_id(object_name, record_type)
        if not record_type_id:
            return self.get_picklist_values(object_name, field_name)

        auth = get_session_auth(self._session_state)
        if auth is None:
            return []

        url = (
            f"{auth['instance_url']}/services/data/{auth['api_version']}/"
            f"ui-api/object-info/{object_name}/picklist-values/{record_type_id}/{field_name}"
        )
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {auth['access_token']}"},
            timeout=30,
        )
        if response.status_code >= 400:
            values = tuple(self.get_picklist_values(object_name, field_name))
        else:
            payload = response.json()
            values = tuple(
                str(item.get("value"))
                for item in (payload.get("values") or [])
                if item.get("value") is not None
            )
        self._rt_picklist_cache[cache_key] = values
        return list(values)

    def get_record_type_names(self, object_name: str) -> list[str]:
        describe = self._get_object_describe(object_name)
        names: set[str] = set()
        for info in describe.get("recordTypeInfos") or []:
            if info.get("available") and info.get("name"):
                names.add(str(info["name"]))
        return sorted(names)

    def has_record_type_picklist_restriction(
        self,
        object_name: str,
        record_type_name: str,
        field_name: str,
    ) -> bool:
        object_values = set(self.get_picklist_values(object_name, field_name))
        allowed = set(
            self.get_allowed_values_for_record_type(object_name, record_type_name, field_name)
        )
        if not object_values or not allowed:
            return False
        return allowed != object_values

    def _auth_headers(self) -> tuple[str, str, str]:
        auth = get_session_auth(self._session_state)
        if auth is None:
            raise ConnectionError("Salesforce session is not connected.")
        return auth["access_token"], auth["instance_url"], auth["api_version"]

    def _get_global_describe(self) -> dict[str, Any]:
        if self._global_describe is not None:
            return self._global_describe
        token, instance_url, api_version = self._auth_headers()
        response = requests.get(
            f"{instance_url}/services/data/{api_version}/sobjects/",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if response.status_code >= 400:
            raise ConnectionError("Unable to describe Salesforce org.")
        self._global_describe = response.json()
        return self._global_describe

    def _get_object_describe(self, object_name: str) -> dict[str, Any]:
        cached = self._describe_cache.get(object_name)
        if cached is not None:
            return cached
        token, instance_url, api_version = self._auth_headers()
        response = requests.get(
            f"{instance_url}/services/data/{api_version}/sobjects/{object_name}/describe/",
            headers={"Authorization": f"Bearer {token}"},
            timeout=60,
        )
        if response.status_code >= 400:
            raise ConnectionError(f"Unable to describe Salesforce object {object_name}.")
        payload = response.json()
        self._describe_cache[object_name] = payload
        return payload

    def _resolve_record_type_id(self, object_name: str, record_type: str) -> str | None:
        normalized = self._normalize_record_type_name(record_type)
        cache_key = (object_name, normalized)
        if cache_key in self._record_type_id_cache:
            return self._record_type_id_cache[cache_key] or None

        describe = self._get_object_describe(object_name)
        record_type_id = ""
        for info in describe.get("recordTypeInfos") or []:
            name = str(info.get("name") or "").strip().lower()
            developer = str(info.get("developerName") or "").strip().lower()
            if name == normalized or developer == normalized.replace(" ", "_"):
                record_type_id = str(info.get("recordTypeId") or "")
                break
        self._record_type_id_cache[cache_key] = record_type_id
        return record_type_id or None

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

    @staticmethod
    def _field_from_describe(raw: dict[str, Any]) -> FieldDefinition:
        sf_type = str(raw.get("type") or "string").lower()
        field_type = _SF_TYPE_LABELS.get(sf_type, sf_type.title())
        reference_to = None
        refs = raw.get("referenceTo") or []
        if refs:
            reference_to = str(refs[0])

        inline_values = tuple(
            str(item.get("value"))
            for item in (raw.get("picklistValues") or [])
            if item.get("value") is not None
        )
        createable = bool(raw.get("createable", True))
        nillable = bool(raw.get("nillable", True))
        defaulted = bool(raw.get("defaultedOnCreate", False))
        required = createable and not nillable and not defaulted

        return FieldDefinition(
            api_name=str(raw.get("name") or ""),
            label=str(raw.get("label") or raw.get("name") or ""),
            field_type=field_type,
            required=required,
            reference_to=reference_to,
            external_id=bool(raw.get("externalId")),
            unique=bool(raw.get("unique")),
            id_lookup=bool(raw.get("idLookup")),
            inline_picklist_values=inline_values,
        )

    @staticmethod
    def _picklist_values_from_field(raw: dict[str, Any]) -> list[PicklistValue]:
        return [
            PicklistValue(
                api_name=str(item.get("value") or ""),
                label=str(item.get("label") or item.get("value") or ""),
                is_active=bool(item.get("active", True)),
            )
            for item in (raw.get("picklistValues") or [])
            if item.get("value") is not None
        ]
