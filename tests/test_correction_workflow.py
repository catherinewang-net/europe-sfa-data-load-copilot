"""Tests for correction-plan and preparation workflow."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from adapters.sfdx_metadata.models import TemplateDefinition
from core.config import READINESS_STATUS
from engines.validation_engine import run_validation
from services.correction_plan_service import build_correction_plan, detect_file_style
from services.file_preparation_service import apply_correction_changes, prepare_file
from services.readiness_service import evaluate_upload_readiness
from services.template_service import TemplateContext


CUSTOMERS_TEMPLATE = TemplateDefinition(
    name="Customers",
    developer_name="Customers_Account",
    object_api_name="Account",
    is_active=True,
    api_to_csv_label={
        "Id": "Salesforce Id",
        "Name": "*Name",
        "L1_Channel__c": "*L1 Channel",
        "BillingStreet": "Street",
        "BillingCity": "City",
        "BillingCountry": "Country",
        "BillingPostalCode": "Postal Code",
        "KeyAccountId__c": "Key Account",
        "Type": "Type",
    },
    csv_label_to_api={
        "Salesforce Id": "Id",
        "*Name": "Name",
        "*L1 Channel": "L1_Channel__c",
        "Street": "BillingStreet",
        "City": "BillingCity",
        "Country": "BillingCountry",
        "Postal Code": "BillingPostalCode",
        "Key Account": "KeyAccountId__c",
        "Type": "Type",
    },
    required_csv_labels=("*External Id", "*Name", "*L1 Channel"),
)


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


def _comparison(missing=None, extra=None, order_diffs=None, template_match=False):
    return {
        "comparison": {
            "template_match": template_match,
            "missing_columns": missing or [],
            "extra_columns": extra or [],
            "duplicate_columns": [],
            "order_differences": order_diffs or [],
            "matching_headers": [],
            "match_percentage": 0,
            "uploaded_column_count": 0,
            "expected_column_count": 0,
        },
        "reference_path": MagicMock(name="customers.csv"),
        "mismatch_warning": None,
        "upload_method": "Workbench",
        "template": "Customers",
    }


class CorrectionWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.dit_headers = [
            "Salesforce Id",
            "*External Id",
            "*Name",
            "Street",
            "City",
            "Country",
            "Postal Code",
            "Key Account",
            "*L1 Channel",
        ]
        self.df = pd.DataFrame({header: ["value"] for header in self.dit_headers})

    @patch("services.correction_plan_service.resolve_template")
    @patch("services.correction_plan_service.load_reference_headers")
    @patch("services.correction_plan_service.compare_to_reference")
    def test_workbench_insert_does_not_require_id(
        self,
        compare_mock,
        load_headers_mock,
        resolve_mock,
    ):
        resolve_mock.return_value = _template_context()
        load_headers_mock.return_value = (
            ["Id", "Name", "L1_Channel__c", "Type"],
            MagicMock(),
        )
        compare_mock.return_value = _comparison(missing=["Id", "L1_Channel__c", "Type"])

        plan = build_correction_plan(
            self.df,
            self.dit_headers,
            "Workbench",
            "Customers",
            "Insert",
            compare_mock.return_value,
        )

        categories = {change["target_column"]: change["category"] for change in plan["changes"] if change.get("target_column")}
        self.assertNotIn("Id", categories)
        self.assertEqual(categories.get("Type"), "add_generated_value")

    @patch("services.correction_plan_service.resolve_template")
    @patch("services.correction_plan_service.load_reference_headers")
    @patch("services.correction_plan_service.compare_to_reference")
    def test_workbench_update_requires_id_manual_review(
        self,
        compare_mock,
        load_headers_mock,
        resolve_mock,
    ):
        resolve_mock.return_value = _template_context()
        load_headers_mock.return_value = (["Id", "Name"], MagicMock())
        compare_mock.return_value = _comparison(missing=["Id"])

        plan = build_correction_plan(
            self.df,
            self.dit_headers,
            "Workbench",
            "Customers",
            "Update",
            compare_mock.return_value,
        )

        id_changes = [change for change in plan["changes"] if change.get("target_column") == "Id"]
        self.assertEqual(len(id_changes), 1)
        self.assertEqual(id_changes[0]["category"], "rename")

    @patch("services.correction_plan_service.resolve_template")
    @patch("services.correction_plan_service.load_reference_headers")
    @patch("services.correction_plan_service.compare_to_reference")
    def test_type_is_proposed_for_customers(
        self,
        compare_mock,
        load_headers_mock,
        resolve_mock,
    ):
        resolve_mock.return_value = _template_context()
        load_headers_mock.return_value = (["Type"], MagicMock())
        compare_mock.return_value = _comparison(missing=["Type"])

        plan = build_correction_plan(
            self.df,
            self.dit_headers,
            "Workbench",
            "Customers",
            "Insert",
            compare_mock.return_value,
        )

        type_change = next(change for change in plan["changes"] if change.get("target_column") == "Type")
        self.assertEqual(type_change["category"], "add_generated_value")
        self.assertEqual(type_change["generated_value"], "Customer")

    @patch("services.correction_plan_service.resolve_template")
    @patch("services.correction_plan_service.load_reference_headers")
    @patch("services.correction_plan_service.compare_to_reference")
    def test_header_order_is_auto_fixable(
        self,
        compare_mock,
        load_headers_mock,
        resolve_mock,
    ):
        resolve_mock.return_value = _template_context()
        load_headers_mock.return_value = (["Name", "L1_Channel__c"], MagicMock())
        compare_mock.return_value = _comparison(
            order_diffs=[{"header": "Name", "expected_position": 2, "actual_position": 1}],
        )

        plan = build_correction_plan(
            pd.DataFrame({"Name": [1], "L1_Channel__c": [2]}),
            ["Name", "L1_Channel__c"],
            "Workbench",
            "Customers",
            "Insert",
            compare_mock.return_value,
        )

        reorder = next(change for change in plan["changes"] if change["category"] == "reorder_columns")
        self.assertTrue(reorder["safe"])

    @patch("services.correction_plan_service.resolve_template")
    @patch("services.correction_plan_service.load_reference_headers")
    @patch("services.correction_plan_service.compare_to_reference")
    def test_friendly_headers_convert_to_api_names(
        self,
        compare_mock,
        load_headers_mock,
        resolve_mock,
    ):
        resolve_mock.return_value = _template_context()
        load_headers_mock.return_value = (["L1_Channel__c"], MagicMock())
        compare_mock.return_value = _comparison(missing=["L1_Channel__c"])

        plan = build_correction_plan(
            self.df,
            self.dit_headers,
            "Workbench",
            "Customers",
            "Insert",
            compare_mock.return_value,
        )

        rename = next(
            change for change in plan["changes"]
            if change["category"] == "rename" and change["target_column"] == "L1_Channel__c"
        )
        self.assertEqual(rename["source_column"], "*L1 Channel")

    @patch("services.correction_plan_service.resolve_template")
    @patch("services.correction_plan_service.load_reference_headers")
    @patch("services.correction_plan_service.compare_to_reference")
    def test_optional_missing_columns_do_not_block(
        self,
        compare_mock,
        load_headers_mock,
        resolve_mock,
    ):
        resolve_mock.return_value = _template_context()
        load_headers_mock.return_value = (["KeyAccountId__c"], MagicMock())
        compare_mock.return_value = _comparison(missing=["KeyAccountId__c"])

        plan = build_correction_plan(
            pd.DataFrame({"*Name": ["Acme"]}),
            ["*Name"],
            "Workbench",
            "Customers",
            "Insert",
            compare_mock.return_value,
        )

        optional = next(change for change in plan["changes"] if change["target_column"] == "KeyAccountId__c")
        self.assertEqual(optional["category"], "add_empty_optional_column")
        self.assertFalse(optional["blocking"])

    @patch("services.correction_plan_service.resolve_template")
    @patch("services.correction_plan_service.load_reference_headers")
    @patch("services.correction_plan_service.compare_to_reference")
    def test_required_missing_business_data_blocks_after_correction(
        self,
        compare_mock,
        load_headers_mock,
        resolve_mock,
    ):
        resolve_mock.return_value = _template_context()
        load_headers_mock.return_value = (["Name"], MagicMock())
        compare_mock.return_value = _comparison(missing=["Name"])

        plan = build_correction_plan(
            pd.DataFrame({"Phone": ["123"]}),
            ["Phone"],
            "Workbench",
            "Customers",
            "Insert",
            compare_mock.return_value,
        )

        self.assertTrue(plan["has_blocking_manual_review"])
        readiness = evaluate_upload_readiness(
            correction_plan={**plan, "corrections_applied": True},
            preparation_result={"manual_review": plan["manual_review"]},
        )
        self.assertEqual(readiness["status"], READINESS_STATUS["NOT_READY"])

    def test_corrected_dataframe_is_separate_from_original(self):
        original = pd.DataFrame({"*Name": ["Acme"], "*L1 Channel": ["AWAY FROM HOME"]})
        plan = {
            "changes": [
                {
                    "change_id": "rename:*L1 Channel->L1_Channel__c",
                    "category": "rename",
                    "source_column": "*L1 Channel",
                    "target_column": "L1_Channel__c",
                }
            ]
        }
        corrected = apply_correction_changes(original, plan, {plan["changes"][0]["change_id"]})
        self.assertIn("L1_Channel__c", corrected.columns)
        self.assertIn("*L1 Channel", original.columns)

    @patch("services.file_preparation_service.resolve_template")
    @patch("services.correction_plan_service.resolve_template")
    @patch("services.correction_plan_service.load_reference_headers")
    @patch("services.correction_plan_service.compare_to_reference")
    def test_revalidation_runs_after_changes_are_applied(
        self,
        compare_mock,
        load_headers_mock,
        resolve_template_mock,
        file_resolve_mock,
    ):
        context = _template_context()
        resolve_template_mock.return_value = context
        file_resolve_mock.return_value = context
        load_headers_mock.return_value = (["Name", "L1_Channel__c"], MagicMock())
        compare_mock.return_value = _comparison(missing=["Name"], template_match=False)

        plan = build_correction_plan(
            self.df,
            self.dit_headers,
            "Workbench",
            "Customers",
            "Insert",
            compare_mock.return_value,
        )
        enabled = {
            change["change_id"]
            for change in plan["changes"]
            if change["category"] == "rename"
        }
        self.assertTrue(enabled)
        result = prepare_file(
            self.df,
            self.dit_headers,
            "Workbench",
            "Customers",
            "Insert",
            plan,
            enabled,
        )

        with patch("engines.validation_engine.compare_to_reference") as validation_compare:
            validation_compare.return_value = _comparison(template_match=True)
            with patch("engines.validation_engine.resolve_template", return_value=context):
                bundle = run_validation(
                    self.df,
                    self.dit_headers,
                    "Data Import Tool",
                    "Customers",
                    preparation_result=result,
                    correction_plan=plan,
                )
        validation_compare.assert_called_once()
        called_headers = validation_compare.call_args[0][0]
        self.assertIn("L1_Channel__c", called_headers)

    @patch("services.file_preparation_service.resolve_template")
    @patch("services.correction_plan_service.resolve_template")
    @patch("services.correction_plan_service.load_reference_headers")
    @patch("services.correction_plan_service.compare_to_reference")
    def test_download_uses_corrected_df(
        self,
        compare_mock,
        load_headers_mock,
        resolve_template_mock,
        file_resolve_mock,
    ):
        context = _template_context()
        resolve_template_mock.return_value = context
        file_resolve_mock.return_value = context
        load_headers_mock.return_value = (["Type"], MagicMock())
        compare_mock.return_value = _comparison(missing=["Type"])

        plan = build_correction_plan(
            self.df,
            self.dit_headers,
            "Workbench",
            "Customers",
            "Insert",
            compare_mock.return_value,
        )
        type_change = next(change for change in plan["changes"] if change["target_column"] == "Type")
        result = prepare_file(
            self.df,
            self.dit_headers,
            "Workbench",
            "Customers",
            "Insert",
            plan,
            {type_change["change_id"]},
        )
        self.assertIn("Type", result["corrected_df"].columns)
        self.assertTrue((result["corrected_df"]["Type"] == "Customer").all())

    def test_status_before_approval_is_needs_user_action(self):
        plan = {
            "has_fixable_changes": True,
            "corrections_applied": False,
            "corrections_declined": False,
            "summary": {"rename": 3, "manual_review": 0},
        }
        readiness = evaluate_upload_readiness(correction_plan=plan)
        self.assertEqual(readiness["status"], READINESS_STATUS["NEEDS_USER_ACTION"])

    def test_status_after_successful_correction_is_ready_with_warnings(self):
        readiness = evaluate_upload_readiness(
            correction_plan={"corrections_applied": True, "has_fixable_changes": True},
            preparation_result={"manual_review": [], "warnings": ["Optional warning"]},
            comparison_result=_comparison(template_match=True),
            validation_result={"issues": []},
        )
        self.assertIn(
            readiness["status"],
            {READINESS_STATUS["READY"], READINESS_STATUS["READY_WITH_WARNINGS"]},
        )

    def test_not_ready_only_for_unresolved_blocking_issues(self):
        readiness = evaluate_upload_readiness(
            correction_plan={"corrections_applied": True, "has_blocking_manual_review": True, "manual_review": [
                {"blocking": True, "description": "Required field Name has no matching source column."}
            ]},
            preparation_result={"manual_review": [{"row": 2, "field": "Name", "reason": "missing"}]},
        )
        self.assertEqual(readiness["status"], READINESS_STATUS["NOT_READY"])

    @patch("services.correction_plan_service.load_reference_headers")
    def test_detect_file_style_identifies_dit_upload(self, load_headers_mock):
        def _headers(method, template):
            if method == "Data Import Tool":
                return (self.dit_headers, MagicMock())
            return (["Id", "Name"], MagicMock())

        load_headers_mock.side_effect = _headers
        style = detect_file_style(self.dit_headers, "Customers")
        self.assertEqual(style["style"], "Data Import Tool")


if __name__ == "__main__":
    unittest.main()
