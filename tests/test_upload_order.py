"""Tests for upload order and dependency graph guidance."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from services.constants import PREREQ_STATUS_ALREADY_LOADED, PREREQ_STATUS_NOT_LOADED
from services.upload_order_service import build_upload_order_plan, get_prerequisites_for_template
from services.data_import_preparation_service import apply_data_import_preparation
from workflow.copilot import build_dit_mapping_rows


class UploadOrderServiceTests(unittest.TestCase):
    @patch("services.upload_order_service.resolve_template")
    @patch("services.upload_order_service.get_adapter")
    def test_12_parent_before_child_upload_order(self, mock_get_adapter, mock_resolve):
        mock_resolve.side_effect = lambda name: MagicMock(
            salesforce_object={
                "Customers": "Account",
                "Contact": "Contact",
            }.get(name, name),
            template_definition=None,
            metadata_available=True,
            fallback_config=None,
            metadata_message=None,
            record_type_name=None,
            required_type_value=None,
            account_type_valid=True,
            account_type_error=None,
            is_account_template=name == "Customers",
            template_name=name,
        )
        mock_get_adapter.return_value.get_object_fields.return_value = {}

        plan = build_upload_order_plan(["Contact", "Customers"])
        templates = [step["template"] for step in plan["steps"]]
        self.assertLess(templates.index("Customers"), templates.index("Contact"))

    @patch("services.upload_order_service.resolve_template")
    @patch("services.upload_order_service.get_adapter")
    def test_13_topological_ordering_works(self, mock_get_adapter, mock_resolve):
        mock_resolve.side_effect = lambda name: MagicMock(
            salesforce_object={
                "Order": "Order",
                "Order Item": "OrderItem",
                "Products": "Product2",
            }.get(name, name),
            template_definition=None,
            metadata_available=True,
            fallback_config=None,
            metadata_message=None,
            record_type_name=None,
            required_type_value=None,
            account_type_valid=True,
            account_type_error=None,
            is_account_template=False,
            template_name=name,
        )
        mock_get_adapter.return_value.get_object_fields.return_value = {}

        plan = build_upload_order_plan(["Order Item", "Order", "Products"])
        ordered = [step["template"] for step in plan["steps"]]
        self.assertLess(ordered.index("Products"), ordered.index("Order Item"))
        self.assertLess(ordered.index("Order"), ordered.index("Order Item"))

    @patch("services.upload_order_service.resolve_template")
    @patch("services.upload_order_service.get_adapter")
    def test_14_missing_parent_reported(self, mock_get_adapter, mock_resolve):
        mock_resolve.side_effect = lambda name: MagicMock(
            salesforce_object="CustomerToRoute__c" if name == "Customer to Route" else "Account",
            template_definition=None,
            metadata_available=True,
            fallback_config=None,
            metadata_message=None,
            record_type_name=None,
            required_type_value=None,
            account_type_valid=True,
            account_type_error=None,
            is_account_template=name == "Customers",
            template_name=name,
        )
        mock_get_adapter.return_value.get_object_fields.return_value = {}

        prereq = get_prerequisites_for_template(
            "Customer to Route",
            prerequisite_status={"Customers": PREREQ_STATUS_NOT_LOADED},
        )
        self.assertTrue(prereq["prerequisites"] or prereq["issues"])

    @patch("services.upload_order_service.resolve_template")
    @patch("services.upload_order_service.get_adapter")
    def test_15_circular_dependency_detected(self, mock_get_adapter, mock_resolve):
        mock_resolve.side_effect = lambda name: MagicMock(
            salesforce_object=name,
            template_definition=None,
            metadata_available=True,
            fallback_config=None,
            metadata_message=None,
            record_type_name=None,
            required_type_value=None,
            account_type_valid=True,
            account_type_error=None,
            is_account_template=False,
            template_name=name,
        )
        mock_get_adapter.return_value.get_object_fields.return_value = {}

        with patch("services.upload_order_service.load_dependency_rules") as mock_rules:
            mock_rules.return_value = [
                {
                    "id": "cycle_a",
                    "type": "object_load_order",
                    "parent_template": "Template B",
                    "child_template": "Template A",
                    "parent_object": "B",
                    "child_object": "A",
                },
                {
                    "id": "cycle_b",
                    "type": "object_load_order",
                    "parent_template": "Template A",
                    "child_template": "Template B",
                    "parent_object": "A",
                    "child_object": "B",
                },
            ]
            plan = build_upload_order_plan(["Template A", "Template B"])
            self.assertTrue(plan["cycles"])
            self.assertIn("circular dependency", plan["message"].lower())

    def test_19_original_df_remains_unchanged(self):
        original = pd.DataFrame({"*Name": ["Acme"]})
        original_copy = original.copy(deep=True)
        correction_plan = {
            "changes": [],
            "proposed_renames": [],
            "has_fixable_changes": False,
            "has_blocking_manual_review": False,
        }
        result = apply_data_import_preparation(
            original,
            list(original.columns),
            "Customers",
            correction_plan,
            set(),
        )
        pd.testing.assert_frame_equal(original, original_copy)
        self.assertIsNot(result["corrected_df"], original)

    def test_20_final_download_uses_corrected_df(self):
        original = pd.DataFrame({"*Name": ["Acme"]})
        correction_plan = {
            "changes": [{
                "change_id": "whitespace_1",
                "category": "whitespace",
                "source_column": "*Name",
                "target_column": "*Name",
                "safe": True,
            }],
            "proposed_renames": [],
            "has_fixable_changes": True,
            "has_blocking_manual_review": False,
        }
        row_plan = {
            "issues": [{
                "issue_id": "whitespace_1",
                "category": "whitespace",
                "column": "*Name",
                "safe": True,
            }],
            "corrections_applied": True,
        }
        result = apply_data_import_preparation(
            original,
            list(original.columns),
            "Customers",
            correction_plan,
            {"whitespace_1"},
            row_correction_plan=row_plan,
            enabled_row_issue_ids={"whitespace_1"},
        )
        self.assertIsNotNone(result.get("corrected_df"))
        self.assertIsNot(result["corrected_df"], original)

    @patch("services.upload_order_service.resolve_template")
    @patch("services.upload_order_service.get_adapter")
    def test_prerequisite_already_loaded_unblocks_step(self, mock_get_adapter, mock_resolve):
        mock_resolve.side_effect = lambda name: MagicMock(
            salesforce_object="CustomerToRoute__c" if name == "Customer to Route" else "Account",
            template_definition=None,
            metadata_available=True,
            fallback_config=None,
            metadata_message=None,
            record_type_name=None,
            required_type_value=None,
            account_type_valid=True,
            account_type_error=None,
            is_account_template=name == "Customers",
            template_name=name,
        )
        mock_get_adapter.return_value.get_object_fields.return_value = {}

        plan = build_upload_order_plan(
            ["Customer to Route"],
            prerequisite_status={"Customers": PREREQ_STATUS_ALREADY_LOADED},
        )
        step = next(item for item in plan["steps"] if item["template"] == "Customer to Route")
        self.assertIn(step["readiness"], {"Ready", "Needs Review"})


if __name__ == "__main__":
    unittest.main()
