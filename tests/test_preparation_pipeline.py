"""Tests for shared preparation pipeline across DIT and Workbench."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from core.config import PREPARATION_TASKS, READINESS_STATUS
from services.preparation_flow_service import evaluate_preparation_readiness
from services.preparation_orchestrator import (
    build_validation_summary,
    evaluate_shared_download_readiness,
    merge_picklist_change_log,
)
from services.preparation_task_service import (
    is_preparation_only,
    resolve_load_operation,
)
from workflow.copilot import build_dit_mapping_rows


class SharedPreparationPipelineTests(unittest.TestCase):
    def test_merge_picklist_change_log(self):
        result = {
            "change_log": [{"category": "whitespace", "row": 2, "field": "Name"}],
        }
        picklist_plan = {
            "change_log": [{
                "category": "picklist_replacement",
                "row": 2,
                "api_field": "L1_Channel__c",
                "correction_type": "picklist_replacement",
            }],
        }
        merged = merge_picklist_change_log(result, picklist_plan)
        self.assertEqual(len(merged["change_log"]), 2)
        self.assertEqual(merged["change_log"][1]["category"], "picklist_replacement")

    def test_merge_picklist_change_log_noop_without_plan(self):
        result = {"change_log": [{"category": "dates"}]}
        self.assertIs(merge_picklist_change_log(result, None), result)

    def test_build_validation_summary(self):
        summary = build_validation_summary(
            {
                "upload_method": "Data Import Tool",
                "template": "Customers",
                "has_blocking_issues": False,
                "picklist_validation": {"valid_count": 5, "invalid_count": 0, "has_blocking_issues": False},
                "dependencies": {"checked": True, "blocking_count": 0, "manual_review": []},
                "manual_review": [],
                "issues": [],
            },
            {"change_log": [{"category": "whitespace"}], "manual_review": [], "date_unresolved": []},
        )
        self.assertEqual(summary["upload_method"], "Data Import Tool")
        self.assertEqual(summary["change_log_count"], 1)

    def test_shared_download_readiness_dit_blocks_picklist(self):
        with patch("services.preparation_orchestrator.evaluate_download_readiness") as readiness_mock:
            readiness_mock.return_value = (False, "Unresolved picklist validation errors remain", {})
            allowed, message = evaluate_shared_download_readiness(
                upload_method="Data Import Tool",
                template="Customers",
                mapping_rows=build_dit_mapping_rows(["*Name"], "Customers"),
                type_confirmed=True,
                load_operation=None,
                preparation_result={"corrected_df": pd.DataFrame(), "manual_review": [], "date_unresolved": []},
                validation_result={"picklist_validation": {"has_blocking_issues": True}},
            )
        self.assertFalse(allowed)
        self.assertIn("picklist", message.lower())

    def test_shared_download_readiness_workbench_blocks_row_plan(self):
        with patch("services.preparation_orchestrator.evaluate_download_readiness") as readiness_mock:
            readiness_mock.return_value = (False, "Resolve blocking row-level data quality issues", {})
            allowed, message = evaluate_shared_download_readiness(
                upload_method="Workbench",
                template="Customers",
                mapping_rows=[{"confirmed_api_field": "Name", "status": "Confirmed"}],
                type_confirmed=True,
                load_operation="Insert",
                preparation_result={"corrected_df": pd.DataFrame(), "manual_review": [], "date_unresolved": []},
                validation_result={},
                row_correction_plan={"has_blocking_manual_review": True},
            )
        self.assertFalse(allowed)
        self.assertIn("row-level", message.lower())

    def test_three_prep_tasks_share_same_load_operation_resolution(self):
        self.assertIsNone(resolve_load_operation("Prepare and Validate File"))
        self.assertTrue(is_preparation_only("Prepare and Validate File"))
        self.assertEqual(resolve_load_operation("Prepare for Insert"), "Insert")
        self.assertEqual(resolve_load_operation("Prepare for Update"), "Update")
        self.assertFalse(is_preparation_only("Prepare for Insert"))

    def test_preparation_task_config_has_three_tasks(self):
        self.assertEqual(
            set(PREPARATION_TASKS.keys()),
            {"Prepare and Validate File", "Prepare for Insert", "Prepare for Update"},
        )

    def test_readiness_not_ready_for_dependencies(self):
        readiness = evaluate_preparation_readiness(
            header_review_complete=True,
            preparation_result={
                "corrected_df": pd.DataFrame({"Name": ["A"]}),
                "manual_review": [],
                "date_unresolved": [],
            },
            row_correction_plan={"corrections_applied": True},
            workbench_plan=None,
            validation_result={
                "dependencies": {
                    "manual_review": [{"blocking": True, "reason": "Missing parent load"}],
                },
                "picklist_validation": {"has_blocking_issues": False},
            },
            preparation_task="Insert",
            upload_method="Data Import Tool",
        )
        self.assertEqual(readiness["status"], READINESS_STATUS["NOT_READY"])

    def test_dit_mapping_rows_resolve_friendly_headers(self):
        rows = build_dit_mapping_rows(["*L1 Channel", "*Name"], "Customers")
        mapping = {row["uploaded_column"]: row["confirmed_api_field"] for row in rows}
        self.assertIn("*L1 Channel", mapping)
        self.assertNotEqual(mapping["*L1 Channel"], "*L1 Channel")


if __name__ == "__main__":
    unittest.main()
