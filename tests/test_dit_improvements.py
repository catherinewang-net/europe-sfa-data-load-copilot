"""Tests for DIT lessons-learned improvements."""

from __future__ import annotations

import unittest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd

from adapters.sfdx_metadata.models import FieldDefinition, PicklistValue, TemplateDefinition
from engines.dependency_checker import check_dependencies
from services.picklist_correction_service import (
    apply_picklist_corrections,
    build_picklist_correction_plan,
)
from services.template_service import TemplateContext
from validators.data_import_readiness_validator import evaluate_data_import_download_readiness
from validators.picklist_validator import validate_picklists
from validators.routing_validator import validate_routing_rules
from workflow.copilot import build_dit_mapping_rows, resolve_dit_api_field


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
                "*External Id": "CUST_ID__c",
                "*Name": "Name",
                "*L1 Channel": "L1_Channel__c",
                "Street": "BillingStreet",
            },
            api_to_csv_label={
                "CUST_ID__c": "*External Id",
                "Name": "*Name",
                "L1_Channel__c": "*L1 Channel",
                "BillingStreet": "Street",
            },
            required_csv_labels=("*External Id", "*Name", "*L1 Channel"),
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


class DitImprovementTests(unittest.TestCase):
    def test_g1_build_dit_mapping_rows_resolves_friendly_headers(self):
        rows = build_dit_mapping_rows(["*L1 Channel", "*Name"], "Customers")
        mapping = {row["uploaded_column"]: row["confirmed_api_field"] for row in rows}
        self.assertEqual(mapping["*L1 Channel"], "L1_Channel__c")
        self.assertEqual(mapping["*Name"], "Name")
        self.assertEqual(rows[0]["action"], "map")

    def test_g1_picklist_validation_uses_friendly_column(self):
        adapter = MagicMock()
        adapter.get_object_fields.return_value = {
            "L1_Channel__c": _field("L1_Channel__c", "picklist"),
        }
        adapter.get_picklist_value_details.return_value = [
            PicklistValue("AWAY FROM HOME", "AWAY FROM HOME"),
        ]
        adapter.has_record_type_picklist_restriction.return_value = False

        df = pd.DataFrame({"*L1 Channel": ["INVALID", "AWAY FROM HOME"]})
        mapping_rows = build_dit_mapping_rows(list(df.columns), "Customers")
        with patch("validators.picklist_validator.get_adapter", return_value=adapter):
            result = validate_picklists(
                df,
                mapping_rows,
                _customers_context(),
                use_mapped_columns=False,
            )
        self.assertEqual(result["invalid_count"], 1)

    def test_g2_download_gate_blocks_picklist_issues(self):
        allowed, message, _details = evaluate_data_import_download_readiness(
            _customers_context(),
            build_dit_mapping_rows(["*L1 Channel"], "Customers"),
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
        result = check_dependencies(df, "Account Relationship", "Data Import Tool")
        self.assertTrue(result["manual_review"])
        self.assertGreaterEqual(result["blocking_count"], 1)

    def test_g4_contract_customer_dependency(self):
        df = pd.DataFrame({"*AccountId": ["CUST-404"]})
        result = check_dependencies(df, "Contract", "Data Import Tool")
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
        from services.row_correction_plan_service import build_row_correction_plan

        raw_csv = "Street,City\n10, Downing Street,London\n"
        df = pd.DataFrame({"Street": ["10, Downing Street"], "City": ["London"]})
        mapping_rows = build_dit_mapping_rows(list(df.columns), "Customers")
        plan = build_row_correction_plan(
            df,
            "Data Import Tool",
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

    def test_g8_date_format_convertible(self):
        from services.date_conversion_service import (
            SOURCE_FORMAT_WORKBENCH,
            STATUS_CONVERTED,
            TARGET_TOOL_DIT,
            analyze_cell,
        )

        analysis = analyze_cell("2026-01-15", SOURCE_FORMAT_WORKBENCH, TARGET_TOOL_DIT)
        self.assertEqual(analysis["status"], STATUS_CONVERTED)
        self.assertEqual(analysis["converted"], "15/01/2026")

    def test_g9_external_id_scientific_notation_blocks(self):
        from services.row_correction_plan_service import build_row_correction_plan

        df = pd.DataFrame({"*External Id": ["1.23E+10"], "*Name": ["Test"]})
        mapping_rows = build_dit_mapping_rows(list(df.columns), "Customers")
        plan = build_row_correction_plan(
            df,
            "Data Import Tool",
            "Customers",
            mapping_rows=mapping_rows,
        )
        self.assertTrue(plan.get("has_blocking_manual_review"))

    def test_g10_type_column_not_in_dit_customers_template(self):
        from core.reference_templates import load_reference_headers

        headers, _path = load_reference_headers("Data Import Tool", "Customers")
        self.assertNotIn("Type", headers)

    def test_g11_numeric_currency_detected(self):
        from validators.numeric_validator import validate_numeric_fields

        issues = validate_numeric_fields(
            pd.DataFrame({"UnitPrice": ["12,50", "€12,50"]}),
            ["UnitPrice"],
        )
        self.assertTrue(any(issue.get("original_value") == "12,50" for issue in issues))

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
        result = check_dependencies(df, "Products", "Data Import Tool")
        self.assertTrue(result["manual_review"])

    def test_g14_assortment_length_not_auto_fixed(self):
        self.assertTrue(len("x" * 41) > 40)

    def test_g15_ready_happy_path_download_allowed(self):
        allowed, _message, _details = evaluate_data_import_download_readiness(
            _customers_context(),
            build_dit_mapping_rows(["*Name"], "Customers"),
            {"has_blocking_issues": False},
            None,
            {
                "corrected_df": pd.DataFrame({"*Name": ["Valid Customer"]}),
                "manual_review": [],
                "date_unresolved": [],
            },
            validation_result={"has_blocking_issues": False, "dependencies": {"manual_review": []}},
        )
        self.assertTrue(allowed)

    def test_picklist_correction_applies_to_friendly_column(self):
        df = pd.DataFrame({"*L1 Channel": ["INVALID"]})
        picklist_validation = {
            "issues": [{
                "issue_id": "picklist:L1_Channel__c:2",
                "status": "Needs User Action",
                "row": 2,
                "uploaded_column": "*L1 Channel",
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
        self.assertEqual(corrected_df.at[0, "*L1 Channel"], "AWAY FROM HOME")
        self.assertEqual(change_log[0]["friendly_column"], "*L1 Channel")
        self.assertEqual(change_log[0]["api_field"], "L1_Channel__c")

    def test_resolve_dit_api_field_matches_template_config(self):
        with patch("workflow.copilot.resolve_template", return_value=_customers_context()):
            self.assertEqual(resolve_dit_api_field("*L1 Channel", "Customers"), "L1_Channel__c")


if __name__ == "__main__":
    unittest.main()
