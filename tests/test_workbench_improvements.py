"""Tests for Workbench lessons-learned improvements (parallel to DIT scenarios)."""

from __future__ import annotations

import unittest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd

from adapters.sfdx_metadata.models import FieldDefinition, PicklistValue, TemplateDefinition
from engines.dependency_checker import check_dependencies
from services.constants import MAPPING_ACTION_KEEP, MAPPING_STATUS_CONFIRMED
from services.picklist_correction_service import apply_picklist_corrections, build_picklist_correction_plan
from services.row_correction_plan_service import build_row_correction_plan
from services.template_service import TemplateContext
from validators.data_import_readiness_validator import evaluate_data_import_download_readiness
from validators.picklist_validator import validate_picklists
from validators.routing_validator import validate_routing_rules
from validators.workbench_readiness_validator import evaluate_workbench_readiness


def _field(api_name: str, field_type: str, *, required: bool = False) -> FieldDefinition:
    return FieldDefinition(api_name, api_name, field_type, required)


def _customers_context() -> TemplateContext:
    return TemplateContext(
        template_name="Customers",
        salesforce_object="Account",
        template_definition=TemplateDefinition(
            name="Customers",
            developer_name="Customers_Account",
            object_api_name="Account",
            is_active=True,
            csv_label_to_api={
                "CUST_ID__c": "CUST_ID__c",
                "Name": "Name",
                "L1_Channel__c": "L1_Channel__c",
                "BillingStreet": "BillingStreet",
            },
            api_to_csv_label={
                "CUST_ID__c": "CUST_ID__c",
                "Name": "Name",
                "L1_Channel__c": "L1_Channel__c",
                "BillingStreet": "BillingStreet",
            },
            required_csv_labels=("CUST_ID__c", "Name", "L1_Channel__c"),
        ),
        metadata_available=True,
        metadata_message=None,
        fallback_config=None,
        record_type_name="Customer",
        required_type_value="Customer",
        account_type_valid=True,
        account_type_error=None,
        is_account_template=True,
    )


def _mapping_rows(columns: list[str]) -> list[dict]:
    return [
        {
            "uploaded_column": column,
            "confirmed_api_field": column,
            "status": MAPPING_STATUS_CONFIRMED,
            "action": MAPPING_ACTION_KEEP,
        }
        for column in columns
    ]


class WorkbenchImprovementTests(unittest.TestCase):
    def test_g1_picklist_validation_uses_api_columns(self):
        adapter = MagicMock()
        adapter.get_object_fields.return_value = {
            "L1_Channel__c": _field("L1_Channel__c", "picklist"),
        }
        adapter.get_picklist_value_details.return_value = [
            PicklistValue("AWAY FROM HOME", "AWAY FROM HOME"),
        ]
        adapter.has_record_type_picklist_restriction.return_value = False

        df = pd.DataFrame({"L1_Channel__c": ["INVALID", "AWAY FROM HOME"]})
        mapping_rows = _mapping_rows(list(df.columns))
        with patch("validators.picklist_validator.get_adapter", return_value=adapter):
            result = validate_picklists(
                df,
                mapping_rows,
                _customers_context(),
                use_mapped_columns=True,
            )
        self.assertEqual(result["invalid_count"], 1)

    def test_g2_download_gate_blocks_picklist_issues(self):
        allowed, message, _details = evaluate_workbench_readiness(
            _customers_context(),
            _mapping_rows(["L1_Channel__c"]),
            True,
            "Insert",
            {"has_blocking_issues": True},
            None,
            {"corrected_df": pd.DataFrame(), "manual_review": [], "date_unresolved": []},
        )
        self.assertFalse(allowed)
        self.assertIn("picklist", message.lower())

    def test_g3_account_relationship_dependency(self):
        df = pd.DataFrame({
            "*Customer External Id": ["MISSING-001"],
            "*Related Account External Id": ["MISSING-002"],
        })
        result = check_dependencies(df, "Account Relationship", "Workbench")
        self.assertTrue(result["manual_review"])

    def test_g4_contract_customer_dependency(self):
        df = pd.DataFrame({"*AccountId": ["CUST-404"]})
        result = check_dependencies(df, "Contract", "Workbench")
        self.assertTrue(any(item.get("field") == "*AccountId" for item in result["manual_review"]))

    def test_g5_routing_route_id_zero(self):
        df = pd.DataFrame({
            "*Customer External Id": ["C1"],
            "*Route": ["0"],
            "*Effective From(dd/MM/yyyy)": ["01/01/2026"],
            "*Effective To(dd/MM/yyyy)": ["31/12/2026"],
        })
        result = validate_routing_rules(df, "Routing Import")
        self.assertTrue(any("zero" in item["reason"].lower() for item in result["manual_review"]))

    def test_g6_customer_to_route_duplicate(self):
        df = pd.DataFrame({
            "*Customer External Id": ["C1", "C1"],
            "*Route External Id": ["R1", "R1"],
        })
        result = validate_routing_rules(df, "Customer to Route")
        self.assertTrue(any("duplicate" in item["reason"].lower() for item in result["manual_review"]))

    def test_g7_commas_in_street_detected_by_row_plan(self):
        raw_csv = "BillingStreet,City\n10, Downing Street,London\n"
        df = pd.DataFrame({"BillingStreet": ["10, Downing Street"], "City": ["London"]})
        mapping_rows = _mapping_rows(list(df.columns))
        with patch("services.row_correction_plan_service.get_metadata_adapter") as adapter_mock:
            adapter_mock.return_value.get_object_fields.return_value = {}
            plan = build_row_correction_plan(
                df,
                "Workbench",
                "Customers",
                mapping_rows=mapping_rows,
                raw_csv_content=raw_csv,
            )
        csv_issues = [
            issue for issue in plan.get("issues", [])
            if issue.get("category") == "csv_structure"
        ]
        self.assertTrue(csv_issues)
        self.assertTrue(plan.get("has_blocking_manual_review"))

    def test_g8_date_format_convertible_for_workbench(self):
        from services.date_conversion_service import (
            SOURCE_FORMAT_WORKBENCH,
            TARGET_TOOL_WORKBENCH,
            analyze_cell,
        )

        analysis = analyze_cell("2026-01-15", SOURCE_FORMAT_WORKBENCH, TARGET_TOOL_WORKBENCH)
        self.assertIn(analysis["status"], {"convertible", "already_correct", "valid"})

    def test_g9_external_id_scientific_notation_blocks(self):
        df = pd.DataFrame({"CUST_ID__c": ["1.23E+10"], "Name": ["Test"]})
        mapping_rows = _mapping_rows(list(df.columns))
        with patch("services.row_correction_plan_service.get_metadata_adapter") as adapter_mock:
            adapter_mock.return_value.get_object_fields.return_value = {}
            plan = build_row_correction_plan(
                df,
                "Workbench",
                "Customers",
                mapping_rows=mapping_rows,
            )
        self.assertTrue(plan.get("has_blocking_manual_review"))

    def test_g10_type_column_required_for_account_insert(self):
        allowed, message, _details = evaluate_workbench_readiness(
            _customers_context(),
            _mapping_rows(["Name"]),
            False,
            "Insert",
            {"has_blocking_issues": False},
            None,
            {"corrected_df": pd.DataFrame({"Name": ["Valid"]}), "manual_review": [], "date_unresolved": []},
        )
        self.assertFalse(allowed)
        self.assertIn("Type", message)

    def test_g11_numeric_currency_detected(self):
        from validators.numeric_validator import validate_numeric_fields

        issues = validate_numeric_fields(
            pd.DataFrame({"ListPrice__c": ["12,50"]}),
            ["ListPrice__c"],
        )
        self.assertTrue(issues)

    def test_g12_past_routing_end_date(self):
        past = (date.today() - timedelta(days=30)).strftime("%d/%m/%Y")
        df = pd.DataFrame({
            "*Customer External Id": ["C1"],
            "*Route": ["100"],
            "*Effective From(dd/MM/yyyy)": ["01/01/2020"],
            "*Effective To(dd/MM/yyyy)": [past],
        })
        result = validate_routing_rules(df, "Routing Import")
        self.assertTrue(any("past" in item["reason"].lower() for item in result["manual_review"]))

    def test_g13_product_hierarchy_dependency(self):
        df = pd.DataFrame({
            "*External ID": ["COMP-1"],
            "*Name": ["Competitor Cola"],
            "*Product Hierarchy Level": ["Competitor Brand"],
        })
        result = check_dependencies(df, "Products", "Workbench")
        self.assertTrue(result["manual_review"])

    def test_g15_ready_happy_path_download_allowed(self):
        allowed, _message, _details = evaluate_workbench_readiness(
            _customers_context(),
            _mapping_rows(["Name"]),
            True,
            "Insert",
            {"has_blocking_issues": False},
            {"issues": [], "manual_review": []},
            {
                "corrected_df": pd.DataFrame({"Name": ["Valid Customer"]}),
                "manual_review": [],
                "date_unresolved": [],
            },
        )
        self.assertTrue(allowed)

    def test_picklist_correction_applies_to_api_column(self):
        df = pd.DataFrame({"L1_Channel__c": ["INVALID"]})
        picklist_validation = {
            "issues": [{
                "issue_id": "picklist:L1_Channel__c:2",
                "status": "Needs User Action",
                "row": 2,
                "uploaded_column": "L1_Channel__c",
                "salesforce_api_field": "L1_Channel__c",
                "uploaded_value": "INVALID",
            }]
        }
        plan = build_picklist_correction_plan(picklist_validation, df)
        corrections = [
            {**item, "proposed_value": "AWAY FROM HOME"}
            for item in plan["corrections"]
        ]
        corrected_df, change_log, _original = apply_picklist_corrections(
            df,
            picklist_validation,
            corrections,
        )
        self.assertEqual(corrected_df.at[0, "L1_Channel__c"], "AWAY FROM HOME")
        self.assertEqual(change_log[0]["api_field"], "L1_Channel__c")

    def test_dit_download_gate_blocks_dependencies(self):
        allowed, message, _details = evaluate_data_import_download_readiness(
            _customers_context(),
            _mapping_rows(["Name"]),
            {"has_blocking_issues": False},
            None,
            {"corrected_df": pd.DataFrame(), "manual_review": [], "date_unresolved": []},
            validation_result={
                "has_blocking_issues": False,
                "dependencies": {
                    "manual_review": [{"blocking": True, "reason": "Missing parent"}],
                },
            },
        )
        self.assertFalse(allowed)
        self.assertIn("dependency", message.lower())


if __name__ == "__main__":
    unittest.main()
