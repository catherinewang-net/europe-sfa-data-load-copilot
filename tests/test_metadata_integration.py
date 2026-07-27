"""Integration tests for metadata-backed validation."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from adapters.sfdx_metadata.models import FieldDefinition, PicklistValue, TemplateDefinition
from services.constants import (
    MAPPING_SOURCE_SALESFORCE,
    MAPPING_STATUS_CONFIRMED,
    MAPPING_STATUS_INVALID,
    MAPPING_STATUS_NEEDS_CONFIRMATION,
    PICKLIST_STATUS_NEEDS_USER_ACTION,
    PICKLIST_STATUS_METADATA_UNAVAILABLE,
)
from services.download_readiness_service import evaluate_download_readiness
from services.field_mapping_service import (
    build_mapping_rows,
    confirm_mapping,
    get_confirmed_rename_map,
    is_valid_api_header,
)
from services.template_service import (
    TemplateContext,
    _reset_template_dropdown_cache,
    get_template_dropdown_options,
    get_template_dropdown_warning,
    resolve_template,
)
from validators.load_action_validator import validate_load_action
from validators.picklist_validator import validate_picklists


def _mock_adapter() -> MagicMock:
    adapter = MagicMock()
    adapter.skipped_files = [
        "force-app/main/default/objects/CustomerToRoute__c/fields/Frequency__c.field-meta.xml"
    ]
    adapter.get_template.return_value = TemplateDefinition(
        name="Customers",
        developer_name="Customers_Account",
        object_api_name="Account",
        is_active=True,
        api_to_csv_label={
            "Id": "Salesforce Id",
            "CUST_ID__c": "*External Id",
            "Name": "*Name",
            "L1_Channel__c": "*L1 Channel",
            "Type": "Type",
        },
        csv_label_to_api={
            "Salesforce Id": "Id",
            "*External Id": "CUST_ID__c",
            "*Name": "Name",
            "*L1 Channel": "L1_Channel__c",
            "Type": "Type",
        },
        required_csv_labels=("*External Id", "*Name", "*L1 Channel"),
    )
    adapter.get_object_fields.return_value = {
        "Id": FieldDefinition("Id", "Id", "Text", False),
        "CUST_ID__c": FieldDefinition("CUST_ID__c", "External Id", "Text", False),
        "Name": FieldDefinition("Name", "Name", "Text", True),
        "L1_Channel__c": FieldDefinition(
            "L1_Channel__c",
            "Channel",
            "Picklist",
            False,
            global_value_set="L1_Channel",
        ),
        "Type": FieldDefinition(
            "Type",
            "Type",
            "Picklist",
            False,
            standard_value_set="AccountType",
        ),
        "Invalid__c": FieldDefinition("Invalid__c", "Invalid", "Text", False),
    }
    adapter.get_picklist_value_details.side_effect = lambda obj, field: {
        "L1_Channel__c": [
            PicklistValue("AWAY FROM HOME", "AWAY FROM HOME"),
            PicklistValue("DISTRIBUTOR", "DISTRIBUTOR"),
        ],
        "Type": [
            PicklistValue("Customer", "Customer"),
            PicklistValue("Key Account", "Key Account"),
        ],
    }.get(field, [])
    adapter.get_picklist_values.side_effect = lambda obj, field: [
        value.api_name for value in adapter.get_picklist_value_details(obj, field)
    ]
    adapter.get_allowed_values_for_record_type.side_effect = (
        lambda obj, record_type, field: ["AWAY FROM HOME"]
        if record_type == "Customer" and field == "L1_Channel__c"
        else adapter.get_picklist_values(obj, field)
    )
    adapter.has_record_type_picklist_restriction.side_effect = (
        lambda obj, record_type, field: record_type == "Customer" and field == "L1_Channel__c"
    )
    return adapter


class MetadataIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = _mock_adapter()
        self.template_context = TemplateContext(
            template_name="Customers",
            metadata_available=True,
            template_definition=self.adapter.get_template("Customers"),
            salesforce_object="Account",
            fallback_config={"salesforce_object": "Account", "required_type": "Customer"},
            metadata_message=None,
            record_type_name="Customer",
            required_type_value="Customer",
            account_type_valid=True,
            account_type_error=None,
            is_account_template=True,
        )

    @patch("services.template_service.get_adapter")
    @patch("services.field_mapping_service.get_adapter")
    def test_customer_template_resolves_to_account(self, mapping_adapter, template_adapter):
        template_adapter.return_value = self.adapter
        mapping_adapter.return_value = self.adapter
        context = resolve_template("Customers")
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context.salesforce_object, "Account")

    @patch("services.field_mapping_service.get_adapter")
    def test_confirmed_api_mapping_exists_on_account(self, mapping_adapter):
        mapping_adapter.return_value = self.adapter
        rows, _context = build_mapping_rows(["*Name"], "Customers")
        confirm_mapping(rows, "*Name", "Name")
        self.assertEqual(rows[0]["status"], MAPPING_STATUS_CONFIRMED)

    @patch("services.field_mapping_service.get_adapter")
    def test_invalid_api_mapping_is_blocked(self, mapping_adapter):
        mapping_adapter.return_value = self.adapter
        rows, _context = build_mapping_rows(["*Name"], "Customers")
        confirm_mapping(rows, "*Name", "NotReal__c")
        self.assertEqual(rows[0]["status"], MAPPING_STATUS_INVALID)

    @patch("services.template_service.get_adapter")
    def test_customer_type_value_exists(self, template_adapter):
        template_adapter.return_value = self.adapter
        context = resolve_template("Customers")
        assert context is not None
        self.assertTrue(context.account_type_valid)
        self.assertEqual(context.required_type_value, "Customer")

    @patch("services.template_service.get_adapter")
    @patch("validators.picklist_validator.get_adapter")
    def test_invalid_account_type_value_is_flagged(self, picklist_adapter, template_adapter):
        template_adapter.return_value = self.adapter
        picklist_adapter.return_value = self.adapter
        rows, _context = build_mapping_rows(["Type"], "Customers")
        confirm_mapping(rows, "Type", "Type")
        df = pd.DataFrame({"Type": ["NotARealType"]})
        result = validate_picklists(df, rows, self.template_context)
        self.assertTrue(result["has_blocking_issues"])
        self.assertEqual(result["issues"][0]["status"], PICKLIST_STATUS_NEEDS_USER_ACTION)

    @patch("services.field_mapping_service.get_adapter")
    @patch("validators.picklist_validator.get_adapter")
    def test_valid_l1_picklist_value(self, picklist_adapter, mapping_adapter):
        picklist_adapter.return_value = self.adapter
        mapping_adapter.return_value = self.adapter
        rows, _context = build_mapping_rows(["*L1 Channel"], "Customers")
        confirm_mapping(rows, "*L1 Channel", "L1_Channel__c")
        df = pd.DataFrame({"*L1 Channel": ["AWAY FROM HOME"]})
        result = validate_picklists(df, rows, self.template_context)
        self.assertFalse(result["has_blocking_issues"])
        self.assertEqual(result["valid_count"], 1)

    @patch("services.field_mapping_service.get_adapter")
    @patch("validators.picklist_validator.get_adapter")
    def test_invalid_l1_picklist_value(self, picklist_adapter, mapping_adapter):
        picklist_adapter.return_value = self.adapter
        mapping_adapter.return_value = self.adapter
        rows, _context = build_mapping_rows(["*L1 Channel"], "Customers")
        confirm_mapping(rows, "*L1 Channel", "L1_Channel__c")
        df = pd.DataFrame({"*L1 Channel": ["NOT VALID"]})
        result = validate_picklists(df, rows, self.template_context)
        self.assertTrue(result["has_blocking_issues"])

    @patch("validators.picklist_validator.get_adapter")
    def test_customer_record_type_restrictions_applied(self, picklist_adapter):
        picklist_adapter.return_value = self.adapter
        rows = [{
            "dit_column": "*L1 Channel",
            "confirmed_api_field": "L1_Channel__c",
            "status": MAPPING_STATUS_CONFIRMED,
        }]
        df = pd.DataFrame({"*L1 Channel": ["DISTRIBUTOR"]})
        result = validate_picklists(df, rows, self.template_context)
        self.assertTrue(result["has_blocking_issues"])

    @patch("services.template_service.get_adapter")
    @patch("validators.picklist_validator.get_adapter")
    def test_key_account_falls_back_to_object_level_values(self, picklist_adapter, template_adapter):
        picklist_adapter.return_value = self.adapter
        template_adapter.return_value = self.adapter
        key_context = TemplateContext(
            template_name="Key Account",
            metadata_available=False,
            template_definition=None,
            salesforce_object="Account",
            fallback_config={"salesforce_object": "Account", "required_type": "Key Account"},
            metadata_message="Template metadata is not available in the local Salesforce project.",
            record_type_name=None,
            required_type_value="Key Account",
            account_type_valid=True,
            account_type_error=None,
            is_account_template=True,
        )
        rows = [{
            "dit_column": "*L1 Channel",
            "confirmed_api_field": "L1_Channel__c",
            "status": MAPPING_STATUS_CONFIRMED,
        }]
        df = pd.DataFrame({"*L1 Channel": ["DISTRIBUTOR"]})
        result = validate_picklists(df, rows, key_context)
        self.assertFalse(result["has_blocking_issues"])
        self.assertEqual(
            result["field_summaries"][0]["validation_source"],
            "Record Type Fallback Used",
        )

    @patch("services.template_service.get_adapter")
    @patch("validators.load_action_validator.get_adapter")
    def test_insert_does_not_require_id(self, load_adapter, template_adapter):
        load_adapter.return_value = self.adapter
        template_adapter.return_value = self.adapter
        rows = [{"dit_column": "*Name", "confirmed_api_field": "Name", "status": MAPPING_STATUS_CONFIRMED}]
        df = pd.DataFrame({"*Name": ["Acme"]})
        result = validate_load_action(df, rows, "Insert", self.template_context)
        self.assertFalse(result["blocks_download"])

    @patch("services.template_service.get_adapter")
    @patch("validators.load_action_validator.get_adapter")
    def test_update_requires_id(self, load_adapter, template_adapter):
        load_adapter.return_value = self.adapter
        template_adapter.return_value = self.adapter
        rows = [
            {"dit_column": "Salesforce Id", "confirmed_api_field": "Id", "status": MAPPING_STATUS_CONFIRMED},
            {"dit_column": "*Name", "confirmed_api_field": "Name", "status": MAPPING_STATUS_CONFIRMED},
        ]
        df = pd.DataFrame({"Salesforce Id": [""], "*Name": ["Acme"]})
        result = validate_load_action(df, rows, "Update", self.template_context)
        self.assertTrue(result["blocks_download"])
        self.assertEqual(result["manual_review"][0]["field"], "Id")

    def test_unconfirmed_never_appears_in_generated_headers(self):
        self.assertFalse(is_valid_api_header("UNCONFIRMED"))
        rename_map = get_confirmed_rename_map([
            {"dit_column": "*Name", "confirmed_api_field": "UNCONFIRMED", "status": MAPPING_STATUS_CONFIRMED}
        ])
        self.assertEqual(rename_map, {})

    @patch("services.field_mapping_service.get_adapter")
    @patch("validators.picklist_validator.get_adapter")
    def test_missing_metadata_produces_manual_review_not_false_invalid(self, picklist_adapter, mapping_adapter):
        picklist_adapter.return_value = self.adapter
        mapping_adapter.return_value = self.adapter
        self.adapter.get_picklist_value_details.side_effect = lambda obj, field: []
        rows = [{
            "dit_column": "*L1 Channel",
            "confirmed_api_field": "L1_Channel__c",
            "status": MAPPING_STATUS_CONFIRMED,
        }]
        df = pd.DataFrame({"*L1 Channel": ["AWAY FROM HOME"]})
        result = validate_picklists(df, rows, self.template_context)
        self.assertFalse(result["has_blocking_issues"])
        self.assertEqual(result["issues"][0]["status"], PICKLIST_STATUS_METADATA_UNAVAILABLE)

    @patch("services.template_service.get_adapter")
    def test_relevant_skipped_xml_warning(self, template_adapter):
        template_adapter.return_value = self.adapter
        rows = [{
            "dit_column": "Frequency",
            "confirmed_api_field": "Frequency__c",
            "status": MAPPING_STATUS_CONFIRMED,
        }]
        allowed, _message, details = evaluate_download_readiness(
            TemplateContext(
                template_name="Customer to Route",
                metadata_available=True,
                template_definition=None,
                salesforce_object="CustomerToRoute__c",
                fallback_config=None,
                metadata_message=None,
                record_type_name=None,
                required_type_value=None,
                account_type_valid=True,
                account_type_error=None,
                is_account_template=False,
            ),
            rows,
            True,
            "Insert",
            None,
            None,
            None,
        )
        self.assertTrue(any("Frequency__c" in warning for warning in details["warnings"]))

    @patch("validators.picklist_validator.get_adapter")
    def test_adapter_metadata_not_reloaded_per_row(self, picklist_adapter):
        picklist_adapter.return_value = self.adapter
        rows = [{
            "dit_column": "*L1 Channel",
            "confirmed_api_field": "L1_Channel__c",
            "status": MAPPING_STATUS_CONFIRMED,
        }]
        df = pd.DataFrame({"*L1 Channel": ["AWAY FROM HOME", "DISTRIBUTOR", "AWAY FROM HOME"]})
        validate_picklists(df, rows, self.template_context)
        picklist_adapter.assert_called_once()

    @patch("services.template_service.get_metadata_adapter")
    def test_template_dropdown_uses_metadata_templates(self, metadata_adapter):
        adapter = MagicMock()
        adapter.list_templates.return_value = [
            TemplateDefinition(
                name="Assortment",
                developer_name="Assortment_Object",
                object_api_name="Assortment__c",
                is_active=True,
                api_to_csv_label={},
                csv_label_to_api={},
                required_csv_labels=(),
            ),
            TemplateDefinition(
                name="Customers",
                developer_name="Customers_Account",
                object_api_name="Account",
                is_active=True,
                api_to_csv_label={},
                csv_label_to_api={},
                required_csv_labels=(),
            ),
        ]
        metadata_adapter.return_value = adapter
        _reset_template_dropdown_cache()

        self.assertEqual(
            get_template_dropdown_options(),
            ["Assortment", "Customers"],
        )
        self.assertIsNone(get_template_dropdown_warning())

    @patch("services.template_service.get_metadata_adapter")
    def test_template_dropdown_accepts_string_and_dict_items(self, metadata_adapter):
        adapter = MagicMock()
        adapter.list_templates.return_value = [
            "Route",
            {"name": "Customers"},
            {"developer_name": "Wholesalers_Account", "label": "Wholesalers"},
        ]
        metadata_adapter.return_value = adapter
        _reset_template_dropdown_cache()

        self.assertEqual(
            get_template_dropdown_options(),
            ["Customers", "Route", "Wholesalers"],
        )

    @patch("services.template_service.load_tool_mappings")
    @patch("services.template_service.get_metadata_adapter")
    def test_template_dropdown_falls_back_without_crashing(self, metadata_adapter, load_mappings):
        metadata_adapter.side_effect = RuntimeError("metadata repo unavailable")
        load_mappings.return_value = {
            "account_templates": ["Customers"],
            "templates": {"Assortment": {}, "Customers": {}},
        }
        _reset_template_dropdown_cache()

        self.assertEqual(get_template_dropdown_options(), ["Assortment", "Customers"])
        self.assertIn("manual configuration fallback", get_template_dropdown_warning().lower())


if __name__ == "__main__":
    unittest.main()
