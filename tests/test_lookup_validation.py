"""Tests for metadata and live lookup validation."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from adapters.sfdx_metadata.models import FieldDefinition
from clients.salesforce_client import UnavailableSalesforceClient
from services.constants import (
    LOOKUP_METHOD_EXTERNAL_ID,
    LOOKUP_METHOD_SALESFORCE_ID,
    LOOKUP_STATUS_NEEDS_REVIEW,
    LOOKUP_STATUS_NOT_FOUND,
    LOOKUP_STATUS_PARENT_FIRST,
    LOOKUP_STATUS_VALID,
    LOOKUP_STATUS_MULTIPLE,
    PREREQ_STATUS_UNKNOWN,
)
from services.lookup_field_detection_service import (
    discover_mapped_lookup_fields,
    infer_matching_method,
    is_lookup_field,
)
from services.template_service import TemplateContext
from validators.lookup_validator import validate_lookups
from workflow.copilot import build_dit_mapping_rows


def _field(
    api_name: str,
    field_type: str,
    *,
    required: bool = False,
    reference_to: str | None = None,
) -> FieldDefinition:
    return FieldDefinition(
        api_name,
        api_name,
        field_type,
        required,
        reference_to=reference_to,
    )


def _contact_fields() -> dict[str, FieldDefinition]:
    return {
        "AccountId": _field("AccountId", "Reference", reference_to="Account"),
        "LastName": _field("LastName", "Text", required=True),
    }


def _order_item_fields() -> dict[str, FieldDefinition]:
    return {
        "OrderId": _field("OrderId", "Reference", required=True, reference_to="Order"),
        "Product2Id": _field("Product2Id", "Reference", reference_to="Product2"),
        "Quantity": _field("Quantity", "Number"),
    }


def _assortment_product_fields() -> dict[str, FieldDefinition]:
    return {
        "AssortmentId": _field("AssortmentId", "Lookup", required=True, reference_to="Assortment__c"),
        "ProductId": _field("ProductId", "Lookup", required=True, reference_to="Product2"),
    }


def _customer_to_route_fields() -> dict[str, FieldDefinition]:
    return {
        "Customer_Account__c": _field("Customer_Account__c", "Lookup", required=True, reference_to="Account"),
        "Route_ID__c": _field("Route_ID__c", "Lookup", required=True, reference_to="Route__c"),
    }


def _account_fields_with_external_id() -> dict[str, FieldDefinition]:
    return {
        "Id": _field("Id", "Id"),
        "External_Id__c": _field(
            "External_Id__c",
            "Text",
            external_id=True,
        ),
        "Name": _field("Name", "Text", required=True),
    }


class LookupDetectionTests(unittest.TestCase):
    @patch("services.lookup_field_detection_service.get_adapter")
    def test_1_lookup_fields_detected_from_metadata(self, mock_get_adapter):
        adapter = MagicMock()
        adapter.get_object_fields.return_value = _contact_fields()
        mock_get_adapter.return_value = adapter

        mapping_rows = [{"confirmed_api_field": "AccountId", "uploaded_column": "AccountId", "status": "Confirmed"}]
        discovered = discover_mapped_lookup_fields("Contact", mapping_rows, adapter=adapter)

        self.assertEqual(len(discovered), 1)
        self.assertEqual(discovered[0]["field_api_name"], "AccountId")
        self.assertEqual(discovered[0]["referenced_object"], "Account")
        self.assertTrue(is_lookup_field(_contact_fields()["AccountId"]))

    @patch("services.lookup_field_detection_service.get_adapter")
    def test_2_contact_accountid_references_account(self, mock_get_adapter):
        adapter = MagicMock()
        adapter.get_object_fields.return_value = _contact_fields()
        mock_get_adapter.return_value = adapter

        discovered = discover_mapped_lookup_fields(
            "Contact",
            [{"confirmed_api_field": "AccountId", "uploaded_column": "AccountId", "status": "Confirmed"}],
            adapter=adapter,
        )
        self.assertEqual(discovered[0]["referenced_object"], "Account")

    @patch("services.lookup_field_detection_service.get_adapter")
    def test_3_orderitem_orderid_references_order(self, mock_get_adapter):
        adapter = MagicMock()
        adapter.get_object_fields.return_value = _order_item_fields()
        mock_get_adapter.return_value = adapter

        discovered = discover_mapped_lookup_fields(
            "OrderItem",
            [{"confirmed_api_field": "OrderId", "uploaded_column": "OrderId", "status": "Confirmed"}],
            adapter=adapter,
        )
        self.assertEqual(discovered[0]["referenced_object"], "Order")

    @patch("services.lookup_field_detection_service.get_adapter")
    def test_4_orderitem_product2id_references_product2(self, mock_get_adapter):
        adapter = MagicMock()
        adapter.get_object_fields.return_value = _order_item_fields()
        mock_get_adapter.return_value = adapter

        discovered = discover_mapped_lookup_fields(
            "OrderItem",
            [{"confirmed_api_field": "Product2Id", "uploaded_column": "Product2Id", "status": "Confirmed"}],
            adapter=adapter,
        )
        targets = {item["field_api_name"]: item["referenced_object"] for item in discovered}
        self.assertEqual(targets["Product2Id"], "Product2")

    @patch("services.lookup_field_detection_service.get_adapter")
    def test_5_assortment_product_requires_assortment_and_product(self, mock_get_adapter):
        adapter = MagicMock()
        adapter.get_object_fields.return_value = _assortment_product_fields()
        mock_get_adapter.return_value = adapter

        mapping_rows = [
            {"confirmed_api_field": "AssortmentId", "uploaded_column": "AssortmentId", "status": "Confirmed"},
            {"confirmed_api_field": "ProductId", "uploaded_column": "ProductId", "status": "Confirmed"},
        ]
        discovered = discover_mapped_lookup_fields("AssortmentProduct__c", mapping_rows, adapter=adapter)
        self.assertEqual({item["referenced_object"] for item in discovered}, {"Assortment__c", "Product2"})

    @patch("services.lookup_field_detection_service.get_adapter")
    def test_6_customer_to_route_requires_customer_and_route(self, mock_get_adapter):
        adapter = MagicMock()
        adapter.get_object_fields.return_value = _customer_to_route_fields()
        mock_get_adapter.return_value = adapter

        mapping_rows = [
            {"confirmed_api_field": "Customer_Account__c", "uploaded_column": "Customer", "status": "Confirmed"},
            {"confirmed_api_field": "Route_ID__c", "uploaded_column": "Route", "status": "Confirmed"},
        ]
        discovered = discover_mapped_lookup_fields("CustomerToRoute__c", mapping_rows, adapter=adapter)
        self.assertEqual({item["referenced_object"] for item in discovered}, {"Account", "Route__c"})


class LookupValidationTests(unittest.TestCase):
    def _template_context(self, object_name: str, template_name: str = "Contact") -> TemplateContext:
        return TemplateContext(
            template_name=template_name,
            metadata_available=True,
            template_definition=None,
            salesforce_object=object_name,
            fallback_config=None,
            metadata_message=None,
            record_type_name=None,
            required_type_value=None,
            account_type_valid=True,
            account_type_error=None,
            is_account_template=False,
        )

    @patch("validators.lookup_validator.get_adapter")
    def test_7_required_blank_lookup_flagged(self, mock_get_adapter):
        adapter = MagicMock()
        adapter.get_object_fields.return_value = {
            "AccountId": _field("AccountId", "Reference", required=True, reference_to="Account"),
        }
        mock_get_adapter.return_value = adapter

        df = pd.DataFrame({"AccountId": [""]})
        result = validate_lookups(
            df,
            [{"confirmed_api_field": "AccountId", "uploaded_column": "AccountId", "status": "Confirmed"}],
            self._template_context("Contact"),
            use_mapped_columns=True,
            client=UnavailableSalesforceClient(),
        )
        self.assertTrue(result["has_blocking_issues"])
        self.assertEqual(result["row_results"][0]["status"], LOOKUP_STATUS_NEEDS_REVIEW)

    @patch("validators.lookup_validator.get_adapter")
    def test_8_metadata_only_produces_needs_review(self, mock_get_adapter):
        adapter = MagicMock()
        adapter.get_object_fields.side_effect = lambda obj: _account_fields_with_external_id() if obj == "Account" else _contact_fields()
        adapter.get_object_fields.return_value = _contact_fields()
        mock_get_adapter.return_value = adapter

        df = pd.DataFrame({"AccountId": ["CUST-001"]})
        result = validate_lookups(
            df,
            [{"confirmed_api_field": "AccountId", "uploaded_column": "AccountId", "status": "Confirmed"}],
            self._template_context("Contact"),
            use_mapped_columns=True,
            client=UnavailableSalesforceClient(),
        )
        self.assertTrue(result["metadata_only"])
        self.assertEqual(result["row_results"][0]["status"], LOOKUP_STATUS_NEEDS_REVIEW)

    @patch("validators.lookup_validator.lookup_records_by_field")
    @patch("validators.lookup_validator.get_adapter")
    def test_9_one_live_match_produces_valid_lookup(self, mock_get_adapter, mock_lookup):
        adapter = MagicMock()
        adapter.get_object_fields.side_effect = lambda obj: (
            _account_fields_with_external_id() if obj == "Account" else _contact_fields()
        )
        mock_get_adapter.return_value = adapter
        mock_lookup.return_value = {
            "matches_by_value": {
                "001xx000003dgbqaaw": [{"Id": "001xx000003DGbQAAW", "External_Id__c": "CUST-001"}],
            },
        }

        client = MagicMock()
        client.test_connection.return_value = {"available": True, "status": "connected"}
        client.is_configured.return_value = True

        df = pd.DataFrame({"AccountId": ["001xx000003DGbQAAW"]})
        result = validate_lookups(
            df,
            [{"confirmed_api_field": "AccountId", "uploaded_column": "AccountId", "status": "Confirmed"}],
            self._template_context("Contact"),
            use_mapped_columns=True,
            client=client,
        )
        self.assertEqual(result["row_results"][0]["status"], LOOKUP_STATUS_VALID)

    @patch("validators.lookup_validator.lookup_records_by_field")
    @patch("validators.lookup_validator.get_adapter")
    def test_10_no_live_match_produces_record_not_found(self, mock_get_adapter, mock_lookup):
        adapter = MagicMock()
        adapter.get_object_fields.side_effect = lambda obj: (
            _account_fields_with_external_id() if obj == "Account" else _contact_fields()
        )
        mock_get_adapter.return_value = adapter
        mock_lookup.return_value = {"matches_by_value": {}}

        client = MagicMock()
        client.test_connection.return_value = {"available": True, "status": "connected"}

        df = pd.DataFrame({"AccountId": ["001xx000003DGbQAAW"]})
        result = validate_lookups(
            df,
            [{"confirmed_api_field": "AccountId", "uploaded_column": "AccountId", "status": "Confirmed"}],
            self._template_context("Contact"),
            use_mapped_columns=True,
            client=client,
        )
        self.assertEqual(result["row_results"][0]["status"], LOOKUP_STATUS_NOT_FOUND)

    @patch("validators.lookup_validator.lookup_records_by_field")
    @patch("validators.lookup_validator.get_adapter")
    def test_11_multiple_matches_produce_multiple_matches(self, mock_get_adapter, mock_lookup):
        adapter = MagicMock()
        adapter.get_object_fields.side_effect = lambda obj: (
            _account_fields_with_external_id() if obj == "Account" else _contact_fields()
        )
        mock_get_adapter.return_value = adapter
        mock_lookup.return_value = {
            "matches_by_value": {
                "001xx000003dgbqaaw": [
                    {"Id": "001xx000003DGbQAAW", "External_Id__c": "CUST-001"},
                    {"Id": "001xx000003DGbQAAX", "External_Id__c": "CUST-001"},
                ],
            },
        }

        client = MagicMock()
        client.test_connection.return_value = {"available": True, "status": "connected"}

        df = pd.DataFrame({"AccountId": ["001xx000003DGbQAAW"]})
        result = validate_lookups(
            df,
            [{"confirmed_api_field": "AccountId", "uploaded_column": "AccountId", "status": "Confirmed"}],
            self._template_context("Contact"),
            use_mapped_columns=True,
            client=client,
        )
        self.assertEqual(result["row_results"][0]["status"], LOOKUP_STATUS_MULTIPLE)

    @patch("validators.lookup_validator.get_adapter")
    def test_16_dit_keeps_friendly_headers(self, mock_get_adapter):
        adapter = MagicMock()
        adapter.get_object_fields.return_value = _contact_fields()
        mock_get_adapter.return_value = adapter

        df = pd.DataFrame({"*Account Id": ["001xx000003DGbQAAW"]})
        mapping_rows = build_dit_mapping_rows(list(df.columns), "Contact")
        mapping_rows[0]["confirmed_api_field"] = "AccountId"

        result = validate_lookups(
            df,
            mapping_rows,
            self._template_context("Contact", "Contact"),
            use_mapped_columns=False,
            client=UnavailableSalesforceClient(),
        )
        self.assertEqual(result["row_results"][0]["uploaded_column"], "*Account Id")

    @patch("validators.lookup_validator.get_adapter")
    def test_17_workbench_keeps_api_headers(self, mock_get_adapter):
        adapter = MagicMock()
        adapter.get_object_fields.return_value = _contact_fields()
        mock_get_adapter.return_value = adapter

        df = pd.DataFrame({"AccountId": ["001xx000003DGbQAAW"]})
        result = validate_lookups(
            df,
            [{"confirmed_api_field": "AccountId", "uploaded_column": "AccountId", "status": "Confirmed"}],
            self._template_context("Contact"),
            use_mapped_columns=True,
            client=UnavailableSalesforceClient(),
        )
        self.assertEqual(result["row_results"][0]["uploaded_column"], "AccountId")

    @patch("validators.lookup_validator.get_adapter")
    def test_18_preparation_warnings_affect_readiness(self, mock_get_adapter):
        from services.preparation_flow_service import evaluate_preparation_readiness
        from core.config import READINESS_STATUS

        readiness = evaluate_preparation_readiness(
            header_review_complete=True,
            preparation_result={"corrected_df": object(), "manual_review": [], "warnings": []},
            row_correction_plan={"corrections_applied": True},
            workbench_plan=None,
            validation_result={"picklist_validation": {"has_blocking_issues": False}},
            template="Contact",
            deployment_templates=["Contact"],
            upload_prerequisites={"Customers": PREREQ_STATUS_UNKNOWN},
            preparation_warnings_acknowledged={},
            prerequisites_confirmed=False,
        )
        self.assertEqual(readiness["status"], READINESS_STATUS["NEEDS_USER_ACTION"])

    def test_matching_method_salesforce_id(self):
        method, _ = infer_matching_method(
            lookup_field="AccountId",
            uploaded_value="001xx000003DGbQAAW",
            referenced_object="Account",
            adapter=MagicMock(),
        )
        self.assertEqual(method, LOOKUP_METHOD_SALESFORCE_ID)

    @patch("validators.lookup_validator.get_adapter")
    def test_dependency_rule_marks_parent_first(self, mock_get_adapter):
        adapter = MagicMock()
        adapter.get_object_fields.return_value = _customer_to_route_fields()
        mock_get_adapter.return_value = adapter

        df = pd.DataFrame({"Customer": ["CUST-001"], "Route": ["ROUTE-001"]})
        rules = [{
            "template": "Customer to Route",
            "field": "Customer",
            "parent_field": "*External Id",
            "parent_template": "Customers",
        }]
        result = validate_lookups(
            df,
            [
                {"confirmed_api_field": "Customer_Account__c", "uploaded_column": "Customer", "status": "Confirmed"},
                {"confirmed_api_field": "Route_ID__c", "uploaded_column": "Route", "status": "Confirmed"},
            ],
            self._template_context("CustomerToRoute__c", "Customer to Route"),
            use_mapped_columns=False,
            client=UnavailableSalesforceClient(),
            dependency_rules=rules,
        )
        statuses = {row["status"] for row in result["row_results"]}
        self.assertIn(LOOKUP_STATUS_PARENT_FIRST, statuses)


if __name__ == "__main__":
    unittest.main()
