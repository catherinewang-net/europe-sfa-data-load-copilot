"""Tests for blank CSV header filtering."""

from __future__ import annotations

import io
import unittest
from unittest.mock import patch

import pandas as pd

from adapters.sfdx_metadata.models import FieldDefinition
from core.csv_loader import filter_blank_header_columns, is_blank_header
from services.template_service import TemplateContext
from services.workbench_mapping_service import build_workbench_mapping_rows


class BlankHeaderTests(unittest.TestCase):
    def test_is_blank_header(self):
        self.assertTrue(is_blank_header(""))
        self.assertTrue(is_blank_header("   "))
        self.assertTrue(is_blank_header("Unnamed: 0"))
        self.assertFalse(is_blank_header("Name"))

    def test_filter_blank_header_columns(self):
        df = pd.DataFrame([["", "Acme", "123"], ["", "Beta", "456"]])
        raw_headers = ["", "Name", "Phone"]
        filtered_df, filtered_headers, skipped = filter_blank_header_columns(df, raw_headers)
        self.assertEqual(filtered_headers, ["Name", "Phone"])
        self.assertEqual(skipped, [""])
        self.assertEqual(list(filtered_df.columns), ["Name", "Phone"])
        self.assertEqual(filtered_df.iloc[0]["Name"], "Acme")

    @patch("services.workbench_mapping_service.get_workbench_field_catalog")
    @patch("services.workbench_mapping_service.resolve_template")
    def test_blank_headers_not_in_mapping_rows(self, resolve_mock, catalog_mock):
        resolve_mock.return_value = TemplateContext(
            template_name="Customers",
            metadata_available=True,
            template_definition=None,
            salesforce_object="Account",
            fallback_config=None,
            metadata_message=None,
            record_type_name="Customer",
            required_type_value="Customer",
            account_type_valid=True,
            account_type_error=None,
            is_account_template=True,
        )
        catalog_mock.return_value = (
            [],
            {"Name": FieldDefinition("Name", "Account Name", "string", True)},
            "Account",
        )
        rows, _ = build_workbench_mapping_rows(["", "Name", "   "], "Customers", "Insert")
        self.assertEqual([row["uploaded_column"] for row in rows], ["Name"])
