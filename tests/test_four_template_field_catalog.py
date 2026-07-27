"""Tests for Account Object, Pricelist, Products, and Retail Promotion field catalogs."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from adapters.sfdx_metadata.models import FieldDefinition
from core.config import EUSFA_SFDX_REPO_PATH
from services.template_service import resolve_template
from services.workbench_field_catalog_service import (
    ACCOUNT_VERIFICATION_CHECKLIST,
    PRICELIST_VERIFICATION_CHECKLIST,
    PRODUCTS_VERIFICATION_CHECKLIST,
    RETAIL_PROMOTION_VERIFICATION_CHECKLIST,
    build_field_metadata_debug_report,
    get_verification_checklist,
    get_workbench_field_catalog,
)


class FourTemplateChecklistRegistrationTests(unittest.TestCase):
    def test_checklists_registered_for_all_four_templates(self):
        self.assertEqual(get_verification_checklist("Account Object"), ACCOUNT_VERIFICATION_CHECKLIST)
        self.assertEqual(get_verification_checklist("AccountObject"), ACCOUNT_VERIFICATION_CHECKLIST)
        self.assertEqual(get_verification_checklist("Pricelist Master"), PRICELIST_VERIFICATION_CHECKLIST)
        self.assertEqual(get_verification_checklist("Products"), PRODUCTS_VERIFICATION_CHECKLIST)
        self.assertEqual(
            get_verification_checklist("Retail Promotion"),
            RETAIL_PROMOTION_VERIFICATION_CHECKLIST,
        )

    def test_products_checklist_preserves_currency_field_spellings(self):
        checklist = get_verification_checklist("Products")
        self.assertIn("CurrencyIsoCode", checklist)
        self.assertIn("CurrencyIsoCode__c", checklist)


class FourTemplateDebugReportTests(unittest.TestCase):
    @patch("services.workbench_field_catalog_service.get_picklist_fields")
    @patch("services.workbench_field_catalog_service.get_adapter")
    @patch("services.workbench_field_catalog_service.resolve_template")
    def test_products_debug_report_includes_type_and_validation_summaries(
        self,
        resolve_mock,
        adapter_mock,
        picklist_mock,
    ):
        from services.template_service import TemplateContext

        resolve_mock.return_value = TemplateContext(
            template_name="Products",
            metadata_available=True,
            template_definition=None,
            salesforce_object="Product2",
            fallback_config=None,
            metadata_message=None,
            record_type_name=None,
            required_type_value=None,
            account_type_valid=True,
            account_type_error=None,
            is_account_template=False,
        )
        adapter_mock.return_value.get_object_fields.return_value = {
            "Name": FieldDefinition("Name", "Product Name", "Text", False),
            "IsActive": FieldDefinition("IsActive", "Active", "Boolean", False),
            "Family": FieldDefinition("Family", "Product Family", "Picklist", False),
            "BasedOnId": FieldDefinition("BasedOnId", "Based On", "Reference", False, reference_to="Product2"),
            "DisplayUrl": FieldDefinition("DisplayUrl", "Display URL", "URL", False),
            "External_Id__c": FieldDefinition(
                "External_Id__c", "External Id", "Text", False, external_id=True,
            ),
            "EndOfLifeDate": FieldDefinition("EndOfLifeDate", "End Of Life Date", "Date", False),
        }
        picklist_mock.return_value = [
            {
                "field_api_name": "Family",
                "field_label": "Product Family",
                "field_type": "Picklist",
                "value_set_source": "Inline Field Values",
                "value_set_name": None,
                "allowed_values": ["Food"],
                "metadata_available": True,
            },
        ]
        report = build_field_metadata_debug_report("Products", "Insert")
        self.assertEqual(report["object_name"], "Product2")
        self.assertIn("Name", report["checklist_fields_found"])
        self.assertIn("Picklist", report["field_type_summary"])
        self.assertIn("Boolean", report["field_type_summary"])
        self.assertTrue(report["date_fields_discovered"])
        self.assertTrue(report["boolean_fields_discovered"])
        self.assertTrue(report["external_id_fields_discovered"])
        validation_types = {item["validation_type"] for item in report["special_validation_hints"]}
        self.assertTrue({"picklist", "boolean", "date", "lookup", "url", "external_id"} <= validation_types)


@unittest.skipUnless(
    (EUSFA_SFDX_REPO_PATH / "force-app" / "main" / "default").is_dir(),
    "EUSFA SFDX metadata repo not available",
)
class FourTemplateFieldCatalogIntegrationTests(unittest.TestCase):
    def test_account_object_resolves_to_account(self):
        context = resolve_template("Account Object")
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context.salesforce_object, "Account")
        self.assertTrue(context.metadata_available)

    def test_pricelist_master_checklist_fully_covered(self):
        report = build_field_metadata_debug_report("Pricelist Master", "Insert")
        self.assertEqual(report["object_name"], "Pricing_Condition__c")
        self.assertEqual(report["missing_checklist_fields"], [])

    def test_products_catalog_includes_supplemented_standard_fields(self):
        _, object_fields, object_name = get_workbench_field_catalog("Products", "Insert")
        self.assertEqual(object_name, "Product2")
        for field_name in ("Name", "IsActive", "ProductCode", "CurrencyIsoCode"):
            self.assertIn(field_name, object_fields)

    def test_retail_promotion_catalog_includes_supplemented_standard_fields(self):
        _, object_fields, object_name = get_workbench_field_catalog("Retail Promotion", "Insert")
        self.assertEqual(object_name, "Promotion")
        for field_name in ("Name", "OwnerId", "StartDate", "EndDate", "IsActive"):
            self.assertIn(field_name, object_fields)

    def test_account_object_reuses_account_catalog_path(self):
        account_options, account_fields, account_object = get_workbench_field_catalog("Customers", "Insert")
        object_options, object_fields, object_name = get_workbench_field_catalog("AccountObject", "Insert")
        self.assertEqual(account_object, "Account")
        self.assertEqual(object_name, "Account")
        self.assertEqual(len(object_fields), len(account_fields))
        self.assertEqual({option.api_name for option in account_options}, {option.api_name for option in object_options})


if __name__ == "__main__":
    unittest.main()
