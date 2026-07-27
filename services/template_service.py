"""Template metadata access through the SFDX Metadata Adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.metadata_provider_factory import CopilotMetadataAdapter, get_metadata_adapter
from adapters.sfdx_metadata.models import TemplateDefinition
from engines.field_mapping import get_template_mapping, load_tool_mappings
from services.constants import (
    ACCOUNT_TEMPLATE_RECORD_TYPES,
    ACCOUNT_TEMPLATE_TYPE_VALUES,
)


@dataclass(frozen=True)
class TemplateDropdownResult:
    options: list[str]
    warning: str | None = None


@dataclass(frozen=True)
class TemplateContext:
    template_name: str
    metadata_available: bool
    template_definition: TemplateDefinition | None
    salesforce_object: str | None
    fallback_config: dict[str, Any] | None
    metadata_message: str | None
    record_type_name: str | None
    required_type_value: str | None
    account_type_valid: bool
    account_type_error: str | None
    is_account_template: bool


def get_adapter() -> CopilotMetadataAdapter:
    return get_metadata_adapter()


# App dropdown labels that differ from Template_Config__mdt Template_Label__c values.
TEMPLATE_NAME_ALIASES: dict[str, str] = {
    "account object": "accountobject",
    "retail sales geo": "routes sales geo",
    "route sales geo": "routes sales geo",
    "units of measure": "unit of measure(uom)",
}


def _resolve_template_lookup_name(template_name: str) -> str:
    normalized = template_name.strip().lower()
    return TEMPLATE_NAME_ALIASES.get(normalized, normalized)


_DROPDOWN_CACHE: TemplateDropdownResult | None = None


def _reset_template_dropdown_cache() -> None:
    global _DROPDOWN_CACHE
    _DROPDOWN_CACHE = None


def _template_name_from_item(item: Any) -> str | None:
    if isinstance(item, str):
        name = item.strip()
        return name or None
    if isinstance(item, dict):
        for key in ("name", "label", "template_name", "developer_name"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None
    name = getattr(item, "name", None)
    if isinstance(name, str) and name.strip():
        return name.strip()
    developer_name = getattr(item, "developer_name", None)
    if isinstance(developer_name, str) and developer_name.strip():
        return developer_name.strip()
    return None


def _fallback_template_names() -> list[str]:
    try:
        config = load_tool_mappings()
    except (FileNotFoundError, ValueError):
        return []
    names = set(config.get("templates", {}).keys())
    names.update(config.get("account_templates", []))
    return sorted(names)


def resolve_template_dropdown_options() -> TemplateDropdownResult:
    """Return active template labels for the Streamlit dropdown."""
    warning: str | None = None
    try:
        adapter = get_metadata_adapter()
        templates = adapter.list_templates()
        names = {
            name
            for item in templates
            if (name := _template_name_from_item(item))
        }
        if names:
            return TemplateDropdownResult(options=sorted(names))
        warning = "No active templates were found in local Salesforce metadata."
    except Exception as exc:
        warning = (
            f"Template metadata could not be loaded ({exc}). "
            "Using manual configuration fallback."
        )

    fallback = _fallback_template_names()
    if not fallback:
        return TemplateDropdownResult(
            options=[],
            warning=warning or "No template options are available.",
        )
    if warning is None:
        warning = "Template metadata is unavailable. Using manual configuration fallback."
    return TemplateDropdownResult(options=fallback, warning=warning)


def get_template_dropdown_options() -> list[str]:
    """Return cached active template labels for the Streamlit dropdown."""
    global _DROPDOWN_CACHE
    if _DROPDOWN_CACHE is None:
        _DROPDOWN_CACHE = resolve_template_dropdown_options()
    return list(_DROPDOWN_CACHE.options)


def get_template_dropdown_warning() -> str | None:
    """Return a user-facing warning when template metadata loading failed."""
    global _DROPDOWN_CACHE
    if _DROPDOWN_CACHE is None:
        _DROPDOWN_CACHE = resolve_template_dropdown_options()
    return _DROPDOWN_CACHE.warning


def list_template_names() -> list[str]:
    """Return active template labels from Template_Config__mdt."""
    adapter = get_adapter()
    return sorted({template.name for template in adapter.list_templates()})


def resolve_template(template_name: str | None) -> TemplateContext | None:
    if not template_name:
        return None

    adapter = get_adapter()
    lookup_name = _resolve_template_lookup_name(template_name)
    template_def = adapter.get_template(lookup_name)
    fallback_config = _load_fallback_config(template_name)
    is_account_template = template_name in ACCOUNT_TEMPLATE_TYPE_VALUES

    if template_def is None:
        salesforce_object = (
            fallback_config.get("salesforce_object")
            if fallback_config and is_account_template
            else None
        )
        type_value, type_valid, type_error = _evaluate_account_type(
            adapter,
            template_name,
            is_account_template,
        )
        return TemplateContext(
            template_name=template_name,
            metadata_available=False,
            template_definition=None,
            salesforce_object=salesforce_object,
            fallback_config=fallback_config,
            metadata_message=(
                "Template metadata is not available in the local Salesforce project."
            ),
            record_type_name=ACCOUNT_TEMPLATE_RECORD_TYPES.get(template_name),
            required_type_value=type_value,
            account_type_valid=type_valid,
            account_type_error=type_error,
            is_account_template=is_account_template,
        )

    type_value, type_valid, type_error = _evaluate_account_type(
        adapter,
        template_name,
        is_account_template,
    )
    return TemplateContext(
        template_name=template_name,
        metadata_available=True,
        template_definition=template_def,
        salesforce_object=template_def.object_api_name,
        fallback_config=fallback_config,
        metadata_message=None,
        record_type_name=ACCOUNT_TEMPLATE_RECORD_TYPES.get(template_name),
        required_type_value=type_value,
        account_type_valid=type_valid,
        account_type_error=type_error,
        is_account_template=is_account_template,
    )


def get_template(template_name: str) -> TemplateDefinition | None:
    return get_adapter().get_template(_resolve_template_lookup_name(template_name))


def get_metadata_source_info(template_name: str | None) -> dict[str, Any]:
    context = resolve_template(template_name)
    adapter = get_adapter()
    if context is None:
        return {
            "repository_mode": "Local SFDX Metadata",
            "template_source": None,
            "salesforce_object": None,
            "record_type": None,
            "metadata_load_status": "No template selected",
            "skipped_xml_files": len(adapter.skipped_files),
            "metadata_available": False,
        }

    return {
        "repository_mode": "Local SFDX Metadata",
        "template_source": (
            context.template_definition.developer_name
            if context.template_definition
            else "Unavailable"
        ),
        "salesforce_object": context.salesforce_object,
        "record_type": context.record_type_name,
        "metadata_load_status": (
            "Loaded"
            if context.metadata_available
            else context.metadata_message
        ),
        "skipped_xml_files": len(adapter.skipped_files),
        "metadata_available": context.metadata_available,
    }


def get_relevant_skipped_files(
    template_context: TemplateContext | None,
    object_name: str | None,
    mapped_api_fields: set[str],
) -> list[str]:
    adapter = get_adapter()
    relevant: list[str] = []
    for skipped in adapter.skipped_files:
        normalized = skipped.replace("\\", "/")
        if object_name and f"/objects/{object_name}/" in normalized:
            relevant.append(skipped)
            continue
        for api_field in mapped_api_fields:
            marker = f"/fields/{api_field}.field-meta.xml"
            if marker in normalized:
                relevant.append(skipped)
                break
    return relevant


def _load_fallback_config(template_name: str) -> dict[str, Any] | None:
    try:
        config = load_tool_mappings()
    except (FileNotFoundError, ValueError):
        return None
    return get_template_mapping(config, template_name)


def _evaluate_account_type(
    adapter: CopilotMetadataAdapter,
    template_name: str,
    is_account_template: bool,
) -> tuple[str | None, bool, str | None]:
    if not is_account_template:
        return None, True, None

    expected = ACCOUNT_TEMPLATE_TYPE_VALUES[template_name]
    allowed = {value.lower() for value in adapter.get_picklist_values("Account", "Type")}
    if expected.lower() in allowed:
        return expected, True, None
    return (
        expected,
        False,
        (
            f"Account.Type does not contain '{expected}' in local Salesforce metadata."
        ),
    )
