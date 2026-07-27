"""Tests for Workbench field catalog and dropdown population."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from adapters.sfdx_metadata.models import FieldDefinition
from services.workbench_field_catalog_service import (
    ACCOUNT_RELATIONSHIP_VERIFICATION_CHECKLIST,
    ACCOUNT_VERIFICATION_CHECKLIST,
    build_field_metadata_debug_report,
    filter_field_options,
    get_verification_checklist,
    get_workbench_field_catalog,
    parse_api_field_from_display,
)
from services.workbench_mapping_service import build_workbench_mapping_rows
from services.template_service import TemplateContext


def _account_fields() -> dict[str, FieldDefinition]:
    return {
        "Name": FieldDefinition("Name", "Account Name", "string", True),
        "Phone": FieldDefinition("Phone", "Phone", "phone", False),
        "Website": FieldDefinition("Website", "Website", "url", False),
        "L1_Channel__c": FieldDefinition("L1_Channel__c", "L1 Channel", "picklist", False),
        "BillingStreet": FieldDefinition("BillingStreet", "Billing Street", "textarea", False),
        "BillingCity": FieldDefinition("BillingCity", "Billing City", "string", False),
        "BillingPostalCode": FieldDefinition("BillingPostalCode", "Billing Postal Code", "string", False),
        "OwnerId": FieldDefinition("OwnerId", "Owner", "Lookup", False, reference_to="User"),
        "ParentId": FieldDefinition("ParentId", "Parent Account", "Hierarchy", False, reference_to="Account"),
        "RecordTypeId": FieldDefinition("RecordTypeId", "Record Type ID", "Reference", False, reference_to="RecordType"),
        "CUST_ID__c": FieldDefinition("CUST_ID__c", "Customer ID", "string", False),
        "Account_Unified_Id__c": FieldDefinition("Account_Unified_Id__c", "Account Unified Id", "string", False),
        "Primary_Contact__c": FieldDefinition(
            "Primary_Contact__c",
            "Primary Contact",
            "Lookup",
            False,
            reference_to="Contact",
        ),
        "KeyAccountId__c": FieldDefinition(
            "KeyAccountId__c",
            "Key Account",
            "Lookup",
            False,
            reference_to="Account",
        ),
    }


def _context() -> TemplateContext:
    return TemplateContext(
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


class WorkbenchFieldCatalogTests(unittest.TestCase):
    @patch("services.workbench_field_catalog_service.get_adapter")
    @patch("services.workbench_field_catalog_service.resolve_template")
    def test_account_fields_loaded_from_get_object_fields(self, resolve_mock, adapter_mock):
        resolve_mock.return_value = _context()
        adapter_mock.return_value.get_object_fields.return_value = _account_fields()
        options, object_fields, object_name = get_workbench_field_catalog("Customers", "Insert")
        self.assertEqual(object_name, "Account")
        self.assertGreaterEqual(len(object_fields), len(_account_fields()))
        self.assertEqual(len(options), len(object_fields))

    @patch("services.workbench_field_catalog_service.get_adapter")
    @patch("services.workbench_field_catalog_service.resolve_template")
    def test_template_config_does_not_limit_dropdown(self, resolve_mock, adapter_mock):
        resolve_mock.return_value = _context()
        adapter_mock.return_value.get_object_fields.return_value = _account_fields()
        report = build_field_metadata_debug_report("Customers", "Insert")
        self.assertFalse(report["template_config_limits_dropdown"])
        self.assertEqual(report["removed_by_filtering"], [])

    @patch("services.workbench_field_catalog_service.get_adapter")
    @patch("services.workbench_field_catalog_service.resolve_template")
    def test_standard_custom_and_lookup_fields_appear(self, resolve_mock, adapter_mock):
        resolve_mock.return_value = _context()
        adapter_mock.return_value.get_object_fields.return_value = _account_fields()
        _, object_fields, _ = get_workbench_field_catalog("Customers", "Insert")
        for field_name in (
            "Name",
            "BillingCity",
            "BillingPostalCode",
            "L1_Channel__c",
            "OwnerId",
            "ParentId",
            "RecordTypeId",
            "CUST_ID__c",
            "Account_Unified_Id__c",
            "Primary_Contact__c",
        ):
            self.assertIn(field_name, object_fields)

    @patch("services.workbench_field_catalog_service.get_adapter")
    @patch("services.workbench_field_catalog_service.resolve_template")
    def test_search_finds_billing_postal_code(self, resolve_mock, adapter_mock):
        resolve_mock.return_value = _context()
        adapter_mock.return_value.get_object_fields.return_value = _account_fields()
        options, _, _ = get_workbench_field_catalog("Customers", "Insert")
        matches = filter_field_options(options, "billing postal")
        self.assertTrue(any(option.api_name == "BillingPostalCode" for option in matches))

    @patch("services.workbench_field_catalog_service.get_adapter")
    @patch("services.workbench_field_catalog_service.resolve_template")
    def test_dropdown_display_uses_api_label_type(self, resolve_mock, adapter_mock):
        resolve_mock.return_value = _context()
        adapter_mock.return_value.get_object_fields.return_value = _account_fields()
        options, _, _ = get_workbench_field_catalog("Customers", "Insert")
        billing = next(option for option in options if option.api_name == "BillingPostalCode")
        self.assertIn("BillingPostalCode — Billing Postal Code —", billing.display_label)
        self.assertEqual(parse_api_field_from_display(billing.display_label), "BillingPostalCode")

    @patch("services.workbench_mapping_service.get_workbench_field_catalog")
    @patch("services.workbench_mapping_service.resolve_template")
    def test_only_uploaded_columns_require_mappings(self, resolve_mock, catalog_mock):
        resolve_mock.return_value = _context()
        catalog_mock.return_value = (
            [],
            _account_fields(),
            "Account",
        )
        rows, _ = build_workbench_mapping_rows(["Name", "Phone"], "Customers", "Insert")
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["uploaded_column"] for row in rows}, {"Name", "Phone"})

    @patch("services.workbench_mapping_service.get_workbench_field_catalog")
    @patch("services.workbench_mapping_service.resolve_template")
    def test_ambiguous_customer_id_requires_confirmation(self, resolve_mock, catalog_mock):
        resolve_mock.return_value = _context()
        fields = dict(_account_fields())
        fields["Cust_ID_System_of_Record__c"] = FieldDefinition(
            "Cust_ID_System_of_Record__c",
            "Customer ID System of Record",
            "string",
            False,
        )
        catalog_mock.return_value = ([], fields, "Account")
        rows, _ = build_workbench_mapping_rows(["Customer ID"], "Customers", "Insert")
        self.assertTrue(rows[0].get("is_ambiguous") or rows[0]["status"] == "Unmapped")

    @patch("services.workbench_field_catalog_service.get_adapter")
    @patch("services.workbench_field_catalog_service.resolve_template")
    def test_unused_account_fields_not_treated_as_missing(self, resolve_mock, adapter_mock):
        resolve_mock.return_value = _context()
        adapter_mock.return_value.get_object_fields.return_value = _account_fields()
        report = build_field_metadata_debug_report("Customers", "Insert", checklist=("KeyAccountId__c",))
        self.assertIn("KeyAccountId__c", adapter_mock.return_value.get_object_fields.return_value)
        self.assertNotIn("KeyAccountId__c", report["missing_checklist_fields"])

    def test_account_relationship_checklist_registered(self):
        checklist = get_verification_checklist("Account Relationship")
        self.assertEqual(checklist, ACCOUNT_RELATIONSHIP_VERIFICATION_CHECKLIST)
        self.assertIn("Related_Account_ExternaIId__c", checklist)

    @patch("services.workbench_field_catalog_service.get_picklist_fields")
    @patch("services.workbench_field_catalog_service.get_adapter")
    @patch("services.workbench_field_catalog_service.resolve_template")
    def test_account_relationship_debug_report_includes_lookup_and_picklist_summary(
        self,
        resolve_mock,
        adapter_mock,
        picklist_mock,
    ):
        resolve_mock.return_value = TemplateContext(
            template_name="Account Relationship",
            metadata_available=True,
            template_definition=None,
            salesforce_object="Account_Relationship__c",
            fallback_config=None,
            metadata_message=None,
            record_type_name=None,
            required_type_value=None,
            account_type_valid=True,
            account_type_error=None,
            is_account_template=False,
        )
        adapter_mock.return_value.get_object_fields.return_value = {
            "Active__c": FieldDefinition("Active__c", "Active", "Checkbox", False),
            "Customer_Account__c": FieldDefinition(
                "Customer_Account__c",
                "Customer Account",
                "Lookup",
                False,
                reference_to="Account",
            ),
            "Market__c": FieldDefinition(
                "Market__c",
                "Market",
                "Picklist",
                False,
                global_value_set="Country_Markets",
            ),
            "Relationship_Type__c": FieldDefinition(
                "Relationship_Type__c",
                "Relationship Type",
                "Picklist",
                False,
                inline_picklist_values=("Wholesaler", "Payer", "3PL"),
            ),
            "OwnerId": FieldDefinition("OwnerId", "Owner", "Reference", False, reference_to="User"),
        }
        picklist_mock.return_value = [
            {
                "field_api_name": "Market__c",
                "field_label": "Market",
                "field_type": "Picklist",
                "value_set_source": "Global Value Set",
                "value_set_name": "Country_Markets",
                "allowed_values": ["DE", "FR"],
                "metadata_available": True,
            },
            {
                "field_api_name": "Relationship_Type__c",
                "field_label": "Relationship Type",
                "field_type": "Picklist",
                "value_set_source": "Inline Field Values",
                "value_set_name": None,
                "allowed_values": ["Wholesaler", "Payer", "3PL"],
                "metadata_available": True,
            },
        ]
        report = build_field_metadata_debug_report("Account Relationship", "Insert")
        self.assertEqual(report["object_name"], "Account_Relationship__c")
        self.assertIn("Customer_Account__c", report["checklist_fields_found"])
        self.assertIn("Is_Primary__c", report["missing_checklist_fields"])
        lookup_names = {item["api_name"] for item in report["lookup_fields_discovered"]}
        self.assertIn("Customer_Account__c", lookup_names)
        self.assertIn("OwnerId", lookup_names)
        picklist_names = {item["api_name"] for item in report["picklist_fields_discovered"]}
        self.assertIn("Market__c", picklist_names)
        self.assertIn("Relationship_Type__c", picklist_names)
        self.assertIn("Picklist", report["field_type_summary"])
