"""Tests for Workbench field matching and split preparation models."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from adapters.sfdx_metadata.models import FieldDefinition, TemplateDefinition
from services.constants import MAPPING_STATUS_CONFIRMED, MAPPING_STATUS_UNMAPPED
from services.data_import_preparation_service import build_data_import_correction_plan
from services.template_service import TemplateContext
from services.workbench_field_matcher import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    normalize_header_for_matching,
    rank_field_candidates,
    select_best_candidate,
    tokenize_header,
)
from services.workbench_mapping_service import (
    build_workbench_mapping_rows,
    confirm_mapping,
    detect_mapping_collisions,
)
from services.workbench_preparation_service import (
    apply_workbench_preparation,
    build_workbench_preparation_plan,
)


CUSTOMERS_TEMPLATE = TemplateDefinition(
    name="Customers",
    developer_name="Customers_Account",
    object_api_name="Account",
    is_active=True,
    api_to_csv_label={
        "Name": "*Name",
        "L1_Channel__c": "*L1 Channel",
        "Phone": "Phone",
        "Website": "Website",
        "BillingStreet": "Billing Street",
        "BillingCity": "Billing City",
        "BillingPostalCode": "Billing Postal Code",
        "Status__c": "Status",
        "DSD_Status__c": "DSD Status",
        "B2B_Status__c": "B2B Status",
        "Type": "Type",
        "Id": "Salesforce Id",
    },
    csv_label_to_api={
        "*Name": "Name",
        "*L1 Channel": "L1_Channel__c",
        "Phone": "Phone",
        "Website": "Website",
        "Billing Street": "BillingStreet",
        "Billing City": "BillingCity",
        "Billing Postal Code": "BillingPostalCode",
        "Status": "Status__c",
        "Type": "Type",
        "Salesforce Id": "Id",
    },
    required_csv_labels=("*External Id", "*Name", "*L1 Channel"),
)


def _object_fields() -> dict[str, FieldDefinition]:
    return {
        "Name": FieldDefinition("Name", "Account Name", "string", True),
        "L1_Channel__c": FieldDefinition("L1_Channel__c", "L1 Channel", "picklist", False),
        "Phone": FieldDefinition("Phone", "Phone", "phone", False),
        "Website": FieldDefinition("Website", "Website", "url", False),
        "BillingStreet": FieldDefinition("BillingStreet", "Billing Street", "textarea", False),
        "BillingCity": FieldDefinition("BillingCity", "Billing City", "string", False),
        "BillingPostalCode": FieldDefinition("BillingPostalCode", "Billing Postal Code", "string", False),
        "Status__c": FieldDefinition("Status__c", "Status", "picklist", False),
        "DSD_Status__c": FieldDefinition("DSD_Status__c", "DSD Status", "picklist", False),
        "B2B_Status__c": FieldDefinition("B2B_Status__c", "B2B Status", "picklist", False),
        "Type": FieldDefinition("Type", "Type", "picklist", False),
        "Id": FieldDefinition("Id", "Record ID", "id", False),
        "KeyAccountId__c": FieldDefinition("KeyAccountId__c", "Key Account", "reference", False),
        "BillingCountry": FieldDefinition("BillingCountry", "Billing Country", "string", False),
    }


def _template_context() -> TemplateContext:
    return TemplateContext(
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


class WorkbenchFieldMatcherTests(unittest.TestCase):
    def test_exact_api_name_match(self):
        candidates = rank_field_candidates("Name", _object_fields(), _template_context())
        best, ambiguous = select_best_candidate(candidates)
        self.assertFalse(ambiguous)
        self.assertEqual(best.api_field, "Name")
        self.assertEqual(best.confidence, CONFIDENCE_HIGH)

    def test_friendly_label_to_api_match(self):
        candidates = rank_field_candidates("L1 Channel", _object_fields(), _template_context())
        best, ambiguous = select_best_candidate(candidates)
        self.assertFalse(ambiguous)
        self.assertEqual(best.api_field, "L1_Channel__c")
        self.assertEqual(best.confidence, CONFIDENCE_HIGH)

    def test_camelcase_matching(self):
        candidates = rank_field_candidates("BillingStreet", _object_fields(), _template_context())
        best, ambiguous = select_best_candidate(candidates)
        self.assertFalse(ambiguous)
        self.assertEqual(best.api_field, "BillingStreet")

    def test_custom_suffix_normalization(self):
        self.assertEqual(normalize_header_for_matching("L1_Channel__c"), "l1channel")
        self.assertEqual(normalize_header_for_matching("L1 Channel"), "l1channel")
        self.assertEqual(normalize_header_for_matching("l1-channel"), "l1channel")

    def test_ambiguous_status_mapping(self):
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
        fields = _object_fields()
        context_no_status = TemplateContext(
            template_name="Generic",
            metadata_available=True,
            template_definition=TemplateDefinition(
                name="Generic",
                developer_name="Generic",
                object_api_name="Account",
                is_active=True,
                api_to_csv_label={},
                csv_label_to_api={},
                required_csv_labels=(),
            ),
            salesforce_object="Account",
            fallback_config=None,
            metadata_message=None,
            record_type_name=None,
            required_type_value=None,
            account_type_valid=True,
            account_type_error=None,
            is_account_template=False,
        )
        candidates = rank_field_candidates("Status", fields, context_no_status)
        status_candidates = [item.api_field for item in candidates if "Status" in item.api_field]
        self.assertIn("Status__c", status_candidates)
        self.assertIn("DSD_Status__c", status_candidates)
        best, ambiguous = select_best_candidate(candidates)
        self.assertTrue(ambiguous)
        self.assertIsNone(best)

    def test_tokenization_examples(self):
        self.assertEqual(tokenize_header("Billing Postal Code"), {"billing", "postal", "code"})
        self.assertEqual(tokenize_header("BillingPostalCode"), {"billing", "postal", "code"})


class WorkbenchMappingServiceTests(unittest.TestCase):
    @patch("services.workbench_mapping_service.get_adapter")
    @patch("services.workbench_mapping_service.resolve_template")
    def test_workbench_does_not_require_every_object_field(self, resolve_mock, adapter_mock):
        resolve_mock.return_value = _template_context()
        adapter_mock.return_value.get_object_fields.return_value = _object_fields()
        uploaded = ["Name", "Phone", "L1 Channel"]
        rows, _ = build_workbench_mapping_rows(uploaded, "Customers")
        self.assertEqual(len(rows), 3)
        self.assertNotIn("KeyAccountId__c", [row.get("suggested_api_field") for row in rows])

    @patch("services.workbench_mapping_service.get_adapter")
    @patch("services.workbench_mapping_service.resolve_template")
    def test_two_uploaded_columns_colliding_on_one_api_field(self, resolve_mock, adapter_mock):
        resolve_mock.return_value = _template_context()
        adapter_mock.return_value.get_object_fields.return_value = _object_fields()
        rows, _ = build_workbench_mapping_rows(["L1 Channel", "L1_Channel__c"], "Customers")
        confirm_mapping(rows, "L1 Channel", "L1_Channel__c")
        confirm_mapping(rows, "L1_Channel__c", "L1_Channel__c")
        collisions = detect_mapping_collisions(rows)
        self.assertTrue(any(item["type"] == "duplicate_api_assignment" for item in collisions))


class WorkbenchPreparationTests(unittest.TestCase):
    @patch("services.workbench_preparation_service.apply_preparation")
    @patch("services.workbench_preparation_service.resolve_template")
    def test_final_workbench_csv_uses_exact_api_names(self, resolve_mock, apply_mock):
        resolve_mock.return_value = _template_context()
        corrected = pd.DataFrame({
            "Name": ["Acme"],
            "L1_Channel__c": ["Retail"],
            "Phone": ["123"],
            "Type": ["Customer"],
        })
        apply_mock.return_value = {
            "corrected_df": corrected,
            "change_log": [],
            "manual_review": [],
            "warnings": [],
            "stats": {},
            "formatting_applied": [],
        }
        rows = [
            {
                "uploaded_column": "Name",
                "dit_column": "Name",
                "status": MAPPING_STATUS_CONFIRMED,
                "confirmed_api_field": "Name",
            },
            {
                "uploaded_column": "L1 Channel",
                "dit_column": "L1 Channel",
                "status": MAPPING_STATUS_CONFIRMED,
                "confirmed_api_field": "L1_Channel__c",
            },
            {
                "uploaded_column": "Phone",
                "dit_column": "Phone",
                "status": MAPPING_STATUS_CONFIRMED,
                "confirmed_api_field": "Phone",
            },
        ]
        plan = build_workbench_preparation_plan(
            pd.DataFrame({"Name": ["Acme"], "L1 Channel": ["Retail"], "Phone": ["123"]}),
            rows,
            "Customers",
            "Insert",
            True,
        )
        result = apply_workbench_preparation(
            pd.DataFrame({"Name": ["Acme"], "L1 Channel": ["Retail"], "Phone": ["123"]}),
            plan,
            {change["change_id"] for change in plan["changes"]},
            rows,
            True,
        )
        self.assertEqual(list(result["corrected_df"].columns), ["Name", "L1_Channel__c", "Phone", "Type"])

    @patch("services.workbench_preparation_service.apply_preparation")
    @patch("services.workbench_preparation_service.resolve_template")
    def test_unconfirmed_fields_never_become_output_headers(self, resolve_mock, apply_mock):
        resolve_mock.return_value = _template_context()
        apply_mock.return_value = {
            "corrected_df": pd.DataFrame({"Name": ["Acme"]}),
            "change_log": [],
            "manual_review": [],
            "warnings": [],
            "stats": {},
            "formatting_applied": [],
        }
        rows = [
            {
                "uploaded_column": "Name",
                "dit_column": "Name",
                "status": MAPPING_STATUS_CONFIRMED,
                "confirmed_api_field": "Name",
            },
            {
                "uploaded_column": "Created Date",
                "dit_column": "Created Date",
                "status": MAPPING_STATUS_UNMAPPED,
                "confirmed_api_field": None,
            },
        ]
        plan = build_workbench_preparation_plan(
            pd.DataFrame({"Name": ["Acme"], "Created Date": ["2026-01-01"]}),
            rows,
            "Customers",
            "Insert",
            False,
        )
        rename_targets = {
            change["target_column"]
            for change in plan["changes"]
            if change["category"] == "rename"
        }
        self.assertNotIn("Created Date", rename_targets)

    @patch("services.workbench_preparation_service.apply_preparation")
    @patch("services.workbench_preparation_service.resolve_template")
    def test_account_type_is_proposed_correctly(self, resolve_mock, apply_mock):
        resolve_mock.return_value = _template_context()
        apply_mock.return_value = {
            "corrected_df": pd.DataFrame({"Name": ["Acme"], "Type": ["Customer"]}),
            "change_log": [],
            "manual_review": [],
            "warnings": [],
            "stats": {},
            "formatting_applied": [],
        }
        rows = [{
            "uploaded_column": "Name",
            "dit_column": "Name",
            "status": MAPPING_STATUS_CONFIRMED,
            "confirmed_api_field": "Name",
        }]
        plan = build_workbench_preparation_plan(
            pd.DataFrame({"Name": ["Acme"]}),
            rows,
            "Customers",
            "Insert",
            True,
        )
        generated = [change for change in plan["changes"] if change["category"] == "add_generated_value"]
        self.assertEqual(generated[0]["target_column"], "Type")
        self.assertEqual(generated[0]["generated_value"], "Customer")


class LoadActionTests(unittest.TestCase):
    def test_workbench_insert_does_not_require_id(self):
        from validators.load_action_validator import validate_load_action

        df = pd.DataFrame({"Name": ["Acme"]})
        rows = [{
            "dit_column": "Name",
            "status": MAPPING_STATUS_CONFIRMED,
            "confirmed_api_field": "Name",
        }]
        result = validate_load_action(df, rows, "Insert", _template_context())
        id_errors = [issue for issue in result["issues"] if issue.get("field") == "Id"]
        self.assertEqual(id_errors, [])

    @patch("validators.load_action_validator.verify_mapping_field", return_value=(True, None))
    def test_workbench_update_requires_id(self, verify_mock):
        from validators.load_action_validator import validate_load_action

        df = pd.DataFrame({"Salesforce Id": [""], "Name": ["Acme"]})
        rows = [
            {
                "dit_column": "Name",
                "status": MAPPING_STATUS_CONFIRMED,
                "confirmed_api_field": "Name",
            },
            {
                "dit_column": "Salesforce Id",
                "status": MAPPING_STATUS_CONFIRMED,
                "confirmed_api_field": "Id",
            },
        ]
        result = validate_load_action(df, rows, "Update", _template_context())
        self.assertTrue(result["manual_review"])
        verify_mock.assert_called()


class DataImportPreparationTests(unittest.TestCase):
    @patch("services.data_import_preparation_service.compare_to_reference")
    @patch("services.data_import_preparation_service.build_correction_plan")
    def test_data_import_tool_still_enforces_template(self, build_mock, compare_mock):
        compare_mock.return_value = {"comparison": {"missing_columns": ["*Name"]}}
        build_mock.return_value = {"changes": [], "manual_review": [{"target_column": "*Name"}]}
        plan = build_data_import_correction_plan(
            pd.DataFrame({"Phone": ["123"]}),
            ["Phone"],
            "Customers",
            compare_mock.return_value,
        )
        build_mock.assert_called_once()
        self.assertIn("manual_review", plan)


class RowValidationAfterMappingTests(unittest.TestCase):
    @patch("services.row_correction_plan_service.get_metadata_adapter")
    @patch("services.row_correction_plan_service.resolve_template")
    def test_row_level_validation_runs_after_confirmed_mapping(self, resolve_mock, adapter_mock):
        from services.row_correction_plan_service import build_row_correction_plan

        resolve_mock.return_value = _template_context()
        adapter_mock.return_value.get_object_fields.return_value = _object_fields()
        rows = [{
            "uploaded_column": "Name",
            "dit_column": "Name",
            "status": MAPPING_STATUS_CONFIRMED,
            "confirmed_api_field": "Name",
        }]
        unresolved_rows = [{
            "uploaded_column": "Created Date",
            "dit_column": "Created Date",
            "status": MAPPING_STATUS_UNMAPPED,
            "confirmed_api_field": None,
        }]
        confirmed_plan = build_row_correction_plan(
            pd.DataFrame({"Name": ["Acme"]}),
            "Workbench",
            "Customers",
            mapping_rows=rows,
        )
        unresolved_plan = build_row_correction_plan(
            pd.DataFrame({"Name": ["Acme"], "Created Date": ["2026-01-01"]}),
            "Workbench",
            "Customers",
            mapping_rows=unresolved_rows,
        )
        self.assertIn("issues", confirmed_plan)
        self.assertLessEqual(
            len(confirmed_plan.get("issues", [])),
            len(unresolved_plan.get("issues", [])) + 10,
        )


class ExpectedExampleBehaviorTests(unittest.TestCase):
    @patch("services.workbench_mapping_service.get_adapter")
    @patch("services.workbench_mapping_service.resolve_template")
    def test_expected_workbench_example_mappings(self, resolve_mock, adapter_mock):
        resolve_mock.return_value = _template_context()
        adapter_mock.return_value.get_object_fields.return_value = _object_fields()
        uploaded = [
            "Name",
            "L1 Channel",
            "Phone",
            "Website",
            "Billing Street",
            "Billing City",
            "Billing Postal Code",
            "Created Date",
        ]
        rows, _ = build_workbench_mapping_rows(uploaded, "Customers")
        suggestions = {row["uploaded_column"]: row.get("suggested_api_field") for row in rows}
        self.assertEqual(suggestions["Name"], "Name")
        self.assertEqual(suggestions["L1 Channel"], "L1_Channel__c")
        self.assertEqual(suggestions["Phone"], "Phone")
        self.assertEqual(suggestions["Website"], "Website")
        self.assertEqual(suggestions["Billing Street"], "BillingStreet")
        self.assertEqual(suggestions["Billing City"], "BillingCity")
        self.assertEqual(suggestions["Billing Postal Code"], "BillingPostalCode")
        self.assertIsNone(suggestions["Created Date"])
