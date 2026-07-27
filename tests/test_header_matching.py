"""Tests for header normalization and matching."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from adapters.sfdx_metadata.models import TemplateDefinition
from services.header_matching_service import (
    analyze_header_matching,
    enrich_template_comparison,
    normalize_header_for_matching,
)
from services.template_service import TemplateContext
from validators.template_validator import validate_template


CUSTOMERS_TEMPLATE = TemplateDefinition(
    name="Customers",
    developer_name="Customers_Account",
    object_api_name="Account",
    is_active=True,
    api_to_csv_label={
        "Name": "*Name",
        "L1_Channel__c": "*L1 Channel",
        "BillingStreet": "Street",
        "BillingCity": "City",
        "BillingPostalCode": "Postal Code",
        "Type": "Type",
    },
    csv_label_to_api={
        "*Name": "Name",
        "*L1 Channel": "L1_Channel__c",
        "Street": "BillingStreet",
        "City": "BillingCity",
        "Postal Code": "BillingPostalCode",
        "Type": "Type",
    },
    required_csv_labels=("*External Id", "*Name", "*L1 Channel"),
)


class HeaderMatchingTests(unittest.TestCase):
    def test_normalization_examples(self):
        self.assertEqual(normalize_header_for_matching("L1 Channel"), "l1channel")
        self.assertEqual(normalize_header_for_matching("L1_Channel__c"), "l1channel")
        self.assertEqual(normalize_header_for_matching("Billing Street"), "billingstreet")
        self.assertEqual(normalize_header_for_matching("BillingStreet"), "billingstreet")
        self.assertEqual(
            normalize_header_for_matching("Billing Postal Code"),
            "billingpostalcode",
        )
        self.assertEqual(normalize_header_for_matching("BillingPostalCode"), "billingpostalcode")

    @patch("services.header_matching_service.load_header_aliases")
    def test_friendly_and_api_headers_proposed_as_renames(self, aliases_mock):
        aliases_mock.return_value = {
            "L1 Channel": "L1_Channel__c",
            "Billing Street": "BillingStreet",
            "Billing City": "BillingCity",
            "Billing Postal Code": "BillingPostalCode",
        }
        uploaded = ["Name", "Phone", "L1 Channel", "Billing Street", "Billing City", "Billing Postal Code"]
        expected = [
            "Name",
            "Phone",
            "L1_Channel__c",
            "BillingStreet",
            "BillingCity",
            "BillingPostalCode",
            "Type",
        ]
        context = TemplateContext(
            template_name="Customers",
            metadata_available=True,
            template_definition=CUSTOMERS_TEMPLATE,
            salesforce_object="Account",
            fallback_config=None,
            metadata_message=None,
            record_type_name="Customer",
            required_type_value="Customer",
            account_type_valid=True,
            account_type_error=None,
            is_account_template=True,
        )
        valid_fields = {
            "Name",
            "Phone",
            "L1_Channel__c",
            "BillingStreet",
            "BillingCity",
            "BillingPostalCode",
            "Type",
        }

        analysis = analyze_header_matching(
            uploaded,
            expected,
            "Workbench",
            context,
            "Insert",
            valid_object_fields=valid_fields,
        )

        rename_map = {
            item["source_column"]: item["target_column"]
            for item in analysis["proposed_renames"]
        }
        self.assertEqual(rename_map["L1 Channel"], "L1_Channel__c")
        self.assertEqual(rename_map["Billing Street"], "BillingStreet")
        self.assertEqual(rename_map["Billing City"], "BillingCity")
        self.assertEqual(rename_map["Billing Postal Code"], "BillingPostalCode")
        self.assertNotIn("L1 Channel", analysis["unmatched_uploaded"])
        self.assertNotIn("L1_Channel__c", analysis["unmatched_target_required"])

    @patch("services.header_matching_service.load_header_aliases")
    def test_enriched_comparison_hides_resolved_missing_and_extra(self, aliases_mock):
        aliases_mock.return_value = {
            "L1 Channel": "L1_Channel__c",
            "Billing Street": "BillingStreet",
        }
        uploaded = ["Name", "L1 Channel", "Billing Street"]
        expected = ["Name", "L1_Channel__c", "BillingStreet"]
        base = validate_template(uploaded, expected)
        context = TemplateContext(
            template_name="Customers",
            metadata_available=True,
            template_definition=CUSTOMERS_TEMPLATE,
            salesforce_object="Account",
            fallback_config=None,
            metadata_message=None,
            record_type_name="Customer",
            required_type_value="Customer",
            account_type_valid=True,
            account_type_error=None,
            is_account_template=True,
        )
        analysis = analyze_header_matching(
            uploaded,
            expected,
            "Workbench",
            context,
            "Insert",
            valid_object_fields={"Name", "L1_Channel__c", "BillingStreet", "Type"},
        )
        enriched = enrich_template_comparison(base, analysis)

        self.assertEqual(enriched["extra_columns"], [])
        self.assertNotIn("L1_Channel__c", enriched["missing_columns"])
        self.assertEqual(len(enriched["proposed_renames"]), 2)

    @patch("services.header_matching_service.load_header_aliases")
    def test_id_not_required_for_insert(self, aliases_mock):
        aliases_mock.return_value = {}
        uploaded = ["Name"]
        expected = ["Id", "Name", "Type"]
        context = TemplateContext(
            template_name="Customers",
            metadata_available=True,
            template_definition=CUSTOMERS_TEMPLATE,
            salesforce_object="Account",
            fallback_config=None,
            metadata_message=None,
            record_type_name="Customer",
            required_type_value="Customer",
            account_type_valid=True,
            account_type_error=None,
            is_account_template=True,
        )
        analysis = analyze_header_matching(
            uploaded,
            expected,
            "Workbench",
            context,
            "Insert",
            valid_object_fields={"Id", "Name", "Type"},
        )
        self.assertNotIn("Id", analysis["unmatched_target_required"])
        self.assertEqual(analysis["generated_fields"][0]["field"], "Type")


if __name__ == "__main__":
    unittest.main()
