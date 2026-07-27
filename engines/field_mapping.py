"""Load and inspect field mapping configuration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.metadata_provider_factory import get_metadata_adapter

MAPPINGS_PATH = Path(__file__).resolve().parent.parent / "rules" / "tool_mappings.json"


def load_tool_mappings() -> dict[str, Any]:
    if not MAPPINGS_PATH.exists():
        raise FileNotFoundError(f"Mapping file not found: {MAPPINGS_PATH}")
    with open(MAPPINGS_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_account_templates(config: dict[str, Any]) -> list[str]:
    return config.get("account_templates", [])


def get_template_mapping(config: dict[str, Any], template: str) -> dict[str, Any] | None:
    return config.get("templates", {}).get(template)


def is_mapping_configured(config: dict[str, Any], template: str) -> bool:
    return get_template_mapping(config, template) is not None


def get_salesforce_object_fields(template_config: dict[str, Any]) -> list[str]:
    """Return API field options from Salesforce object metadata via the adapter."""
    obj = template_config.get("salesforce_object", "Account")
    adapter = get_metadata_adapter()
    return sorted(adapter.get_object_fields(obj).keys())


def get_fields_to_add(template_config: dict[str, Any]) -> list[str]:
    fields = []
    if template_config.get("required_type"):
        fields.append("Type")
    fields.append("Id")
    return fields
