"""Tests for template name alias resolution."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from services.template_service import TEMPLATE_NAME_ALIASES, resolve_template


class TemplateAliasTests(unittest.TestCase):
    @patch("services.template_service.get_adapter")
    def test_retail_sales_geo_resolves_to_route_sales_geo_object(self, adapter_mock):
        adapter_mock.return_value.get_template.return_value = None
        with patch("services.template_service._load_fallback_config", return_value=None):
            context = resolve_template("Retail Sales Geo")
        self.assertIsNotNone(context)
        adapter_mock.return_value.get_template.assert_called_with("routes sales geo")

    @patch("services.template_service.get_adapter")
    def test_units_of_measure_resolves_via_alias(self, adapter_mock):
        adapter_mock.return_value.get_template.return_value = None
        with patch("services.template_service._load_fallback_config", return_value=None):
            resolve_template("Units of Measure")
        adapter_mock.return_value.get_template.assert_called_with("unit of measure(uom)")

    @patch("services.template_service.get_adapter")
    def test_account_object_resolves_via_alias(self, adapter_mock):
        adapter_mock.return_value.get_template.return_value = None
        with patch("services.template_service._load_fallback_config", return_value=None):
            resolve_template("Account Object")
        adapter_mock.return_value.get_template.assert_called_with("accountobject")

    def test_alias_map_covers_dropdown_labels(self):
        self.assertIn("account object", TEMPLATE_NAME_ALIASES)
        self.assertIn("retail sales geo", TEMPLATE_NAME_ALIASES)
        self.assertIn("units of measure", TEMPLATE_NAME_ALIASES)


if __name__ == "__main__":
    unittest.main()
