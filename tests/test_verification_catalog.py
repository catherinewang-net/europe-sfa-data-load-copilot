"""Tests for template verification checklists and mismatch reporting."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from adapters.sfdx_metadata.models import FieldDefinition
from services.workbench_field_catalog_service import (
    ASSORTMENT_VERIFICATION_CHECKLIST,
    CONTACT_VERIFICATION_CHECKLIST,
    CUSTOMER_TO_ROUTE_VERIFICATION_CHECKLIST,
    FREQUENCY_FIELD_INVALID_XML_MESSAGE,
    TEMPLATE_VERIFICATION_CHECKLISTS,
    build_field_metadata_debug_report,
    get_verification_checklist,
)


class VerificationChecklistTests(unittest.TestCase):
    def test_all_templates_have_checklists(self):
        expected = {
            "Assortment",
            "Assortment Assignment",
            "Assortment Product",
            "Contact",
            "Contract",
            "Customer to Route",
            "Order",
            "Order Item",
            "Retail Sales Geo",
            "Units of Measure",
            "Account Relationship",
        }
        self.assertTrue(expected <= set(TEMPLATE_VERIFICATION_CHECKLISTS))

    def test_assortment_checklist_preserves_producttname_spelling(self):
        self.assertIn("ProducttName__c", TEMPLATE_VERIFICATION_CHECKLISTS["Assortment Product"])

    def test_account_relationship_preserves_externaiid_spelling(self):
        checklist = get_verification_checklist("Account Relationship")
        self.assertIn("Related_Account_ExternaIId__c", checklist)

    def test_contract_checklist_includes_both_currency_fields(self):
        checklist = get_verification_checklist("Contract")
        self.assertIn("CurrencyIsoCode", checklist)
        self.assertIn("CurrencyISOCode__c", checklist)


class VerificationMismatchReportTests(unittest.TestCase):
    @patch("services.workbench_field_catalog_service.get_workbench_field_catalog")
    @patch("services.workbench_field_catalog_service.resolve_template")
    @patch("services.workbench_field_catalog_service.get_adapter")
    def test_frequency_invalid_xml_classified(self, adapter_mock, resolve_mock, catalog_mock):
        resolve_mock.return_value = MagicMock(
            metadata_available=True,
            template_definition=MagicMock(object_api_name="CustomerToRoute__c"),
        )
        adapter = adapter_mock.return_value
        adapter.get_object_fields.return_value = {
            "Market__c": FieldDefinition("Market__c", "Market", "picklist", False),
        }
        adapter.skipped_files = [
            "force-app/main/default/objects/CustomerToRoute__c/fields/Frequency__c.field-meta.xml"
        ]
        catalog_mock.return_value = ([], adapter.get_object_fields.return_value, "CustomerToRoute__c")

        report = build_field_metadata_debug_report(
            "Customer to Route",
            "Insert",
            checklist=CUSTOMER_TO_ROUTE_VERIFICATION_CHECKLIST,
        )
        frequency = next(
            item for item in report["verification_mismatches"]
            if item["field"] == "Frequency__c"
        )
        self.assertEqual(frequency["classification"], "Invalid XML")
        self.assertEqual(frequency["detail"], FREQUENCY_FIELD_INVALID_XML_MESSAGE)
        self.assertEqual(report["invalid_xml_fields"][0]["api_name"], "Frequency__c")

    @patch("services.workbench_field_catalog_service.get_workbench_field_catalog")
    @patch("services.workbench_field_catalog_service.resolve_template")
    @patch("services.workbench_field_catalog_service.get_adapter")
    def test_spelling_mismatch_detected(self, adapter_mock, resolve_mock, catalog_mock):
        resolve_mock.return_value = MagicMock(
            metadata_available=True,
            template_definition=MagicMock(object_api_name="Contract"),
        )
        fields = {
            "CurrencyISOCode__c": FieldDefinition("CurrencyISOCode__c", "Currency Code", "picklist", False),
        }
        adapter_mock.return_value.get_object_fields.return_value = fields
        adapter_mock.return_value.skipped_files = []
        catalog_mock.return_value = ([], fields, "Contract")

        report = build_field_metadata_debug_report(
            "Contract",
            "Insert",
            checklist=("CurrencyIsoCode", "CurrencyISOCode__c"),
        )
        iso_missing = next(
            item for item in report["verification_mismatches"]
            if item["field"] == "CurrencyIsoCode"
        )
        self.assertEqual(iso_missing["classification"], "Possible spelling mismatch")
        self.assertIn("CurrencyISOCode__c", iso_missing["detail"])

    @patch("services.workbench_field_catalog_service.get_workbench_field_catalog")
    @patch("services.workbench_field_catalog_service.resolve_template")
    @patch("services.workbench_field_catalog_service.get_adapter")
    def test_found_fields_classified(self, adapter_mock, resolve_mock, catalog_mock):
        resolve_mock.return_value = MagicMock(
            metadata_available=True,
            template_definition=MagicMock(object_api_name="Assortment"),
        )
        fields = {
            "AssortmentExtID__c": FieldDefinition("AssortmentExtID__c", "Assortment Ext ID", "Text", False),
        }
        adapter_mock.return_value.get_object_fields.return_value = fields
        adapter_mock.return_value.skipped_files = []
        catalog_mock.return_value = ([], fields, "Assortment")

        report = build_field_metadata_debug_report(
            "Assortment",
            "Insert",
            checklist=ASSORTMENT_VERIFICATION_CHECKLIST,
        )
        found = next(
            item for item in report["verification_mismatches"]
            if item["field"] == "AssortmentExtID__c"
        )
        self.assertEqual(found["classification"], "Found in metadata")

    @patch("services.workbench_field_catalog_service.get_workbench_field_catalog")
    @patch("services.workbench_field_catalog_service.resolve_template")
    @patch("services.workbench_field_catalog_service.get_adapter")
    def test_object_resolution_failed_classification(self, adapter_mock, resolve_mock, catalog_mock):
        resolve_mock.return_value = MagicMock(
            metadata_available=False,
            template_definition=None,
        )
        adapter_mock.return_value.get_object_fields.return_value = {}
        adapter_mock.return_value.skipped_files = []
        catalog_mock.return_value = ([], {}, None)

        report = build_field_metadata_debug_report(
            "Unknown Template XYZ",
            "Insert",
            checklist=("Name",),
        )
        self.assertTrue(report["object_resolution_failed"])
        self.assertEqual(
            report["verification_mismatches"][0]["classification"],
            "Object resolution failed",
        )


if __name__ == "__main__":
    unittest.main()
