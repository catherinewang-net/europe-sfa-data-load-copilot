"""Tests for unified preparation flow readiness and summaries."""

from __future__ import annotations

import unittest

from core.config import READINESS_STATUS
from services.preparation_flow_service import (
    build_data_preparation_summary,
    evaluate_preparation_readiness,
)


class TestPreparationFlow(unittest.TestCase):
    def test_needs_header_review_before_approval(self):
        readiness = evaluate_preparation_readiness(
            header_review_complete=False,
            preparation_result=None,
            row_correction_plan=None,
            workbench_plan=None,
            validation_result=None,
        )
        self.assertEqual(readiness["status"], READINESS_STATUS["NEEDS_HEADER_REVIEW"])

    def test_needs_user_action_for_pending_row_review(self):
        readiness = evaluate_preparation_readiness(
            header_review_complete=True,
            preparation_result=None,
            row_correction_plan={
                "has_fixable_issues": True,
                "corrections_applied": False,
                "corrections_declined": False,
            },
            workbench_plan=None,
            validation_result=None,
        )
        self.assertEqual(readiness["status"], READINESS_STATUS["NEEDS_USER_ACTION"])

    def test_ready_after_corrections_applied(self):
        readiness = evaluate_preparation_readiness(
            header_review_complete=True,
            preparation_result={"corrected_df": object(), "manual_review": [], "warnings": []},
            row_correction_plan={"corrections_applied": True},
            workbench_plan={"corrections_applied": True},
            validation_result={"picklist_validation": {"has_blocking_issues": False}},
            preparation_task="Prepare and Validate File",
            upload_method="Workbench",
        )
        self.assertIn(
            readiness["status"],
            {READINESS_STATUS["READY"], READINESS_STATUS["READY_WITH_WARNINGS"]},
        )

    def test_not_ready_not_shown_before_data_approval(self):
        readiness = evaluate_preparation_readiness(
            header_review_complete=True,
            preparation_result=None,
            row_correction_plan={"has_fixable_issues": True, "corrections_applied": False},
            workbench_plan=None,
            validation_result={"blocking_issues": True},
        )
        self.assertNotEqual(readiness["status"], READINESS_STATUS["NOT_READY"])

    def test_build_data_preparation_summary_counts(self):
        summary = build_data_preparation_summary(
            mapping_rows=[
                {"action": "exclude", "status": "Do Not Include"},
                {"action": "map", "status": "Confirmed"},
            ],
            row_correction_plan={
                "summary": {
                    "whitespace": {"issues": 2},
                    "dates": {"convertible": 2},
                    "identifiers": {"leading_zeroes": 1},
                    "csv_structure": {"malformed_rows": 0},
                    "phones": {"formatting": 1},
                    "addresses": {"whitespace": 1},
                }
            },
            workbench_plan={"summary": {"rename": 4, "exclude_extra_column": 1, "convert_dates": 1}},
            picklist_validation={"invalid_count": 2},
        )
        self.assertEqual(summary["headers_renamed"], 4)
        self.assertEqual(summary["columns_excluded"], 1)
        self.assertEqual(summary["dates_converted"], 3)
        self.assertEqual(summary["whitespace_fixes"], 3)
        self.assertEqual(summary["invalid_picklist_values"], 2)


if __name__ == "__main__":
    unittest.main()
