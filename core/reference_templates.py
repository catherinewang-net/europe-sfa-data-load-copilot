"""Reference template path resolution and header loading."""

from __future__ import annotations

from pathlib import Path

from core.config import TEMPLATES
from core.csv_loader import read_csv_headers

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REFERENCE_ROOT = PROJECT_ROOT / "reference_templates"

UPLOAD_METHOD_FOLDERS = {
    "Data Import Tool": "data_import_tool",
    "Workbench": "workbench",
}

TEMPLATE_SLUGS = {
    "Account Relationship": "account_relationship",
    "Assortment": "assortment",
    "Assortment Assignment": "assortment_assignment",
    "Assortment Product": "assortment_product",
    "Contact": "contact",
    "Contract": "contract",
    "Customer to Route": "customer_to_route",
    "Customers": "customers",
    "Employee to Route": "employee_to_route",
    "Order": "order",
    "Order Item": "order_item",
    "Key Account": "key_account",
    "Payers": "payers",
    "Pricelist Master": "pricelist_master",
    "Products": "products",
    "Prospects": "prospects",
    "Retail Promotion": "retail_promotion",
    "Retail Sales Geo": "retail_sales_geo",
    "Routing Import": "routing_import",
    "Store Assortment": "store_assortment",
    "Store Product": "store_product",
    "Units of Measure": "units_of_measure",
    "Wholesalers": "wholesalers",
}


def get_reference_path(upload_method: str, template: str) -> Path:
    """Build the path to a reference template CSV."""
    folder = UPLOAD_METHOD_FOLDERS[upload_method]
    slug = TEMPLATE_SLUGS[template]
    return REFERENCE_ROOT / folder / f"{slug}.csv"


def load_reference_headers(upload_method: str, template: str) -> tuple[list[str], Path]:
    """Load expected headers from the matching reference CSV."""
    path = get_reference_path(upload_method, template)

    if path.exists():
        return read_csv_headers(path), path

    if upload_method == "Workbench":
        headers = _load_workbench_headers_from_mappings(template)
        if headers:
            # Only return confirmed-style API names, never status placeholders
            clean = [h for h in headers if not h.startswith("UNCONFIRMED")]
            return clean, path

    raise FileNotFoundError(path.name)


def _load_workbench_headers_from_mappings(template: str) -> list[str] | None:
    """Build expected Workbench headers from confirmed mappings only."""
    try:
        from engines.field_mapping import get_template_mapping, load_tool_mappings

        config = load_tool_mappings()
        template_config = get_template_mapping(config, template)
        if not template_config:
            return None

        column_mappings = template_config.get("column_mappings", {})
        headers = []
        for cfg in column_mappings.values():
            if cfg.get("default_status") == "confirmed" and cfg.get("suggested_api_field"):
                headers.append(cfg["suggested_api_field"])

        if template_config.get("required_type"):
            headers.append("Type")

        return headers or None
    except (FileNotFoundError, ValueError, KeyError):
        return None


def get_other_upload_method(upload_method: str) -> str:
    """Return the alternate upload method."""
    return "Workbench" if upload_method == "Data Import Tool" else "Data Import Tool"
