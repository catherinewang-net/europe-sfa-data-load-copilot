"""Tests for preparation task workflow modes."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from services.preparation_task_service import (
    is_preparation_only,
    preparation_only_message,
    resolve_load_operation,
)
from validators.load_action_validator import not_evaluated_load_action_result, validate_load_action
from validators.workbench_readiness_validator import evaluate_workbench_readiness


class PreparationTaskTests(unittest.TestCase):
    def test_resolve_load_operation(self):
        self.assertIsNone(resolve_load_operation("Prepare and Validate File"))
        self.assertEqual(resolve_load_operation("Prepare for Insert"), "Insert")
        self.assertEqual(resolve_load_operation("Prepare for Update"), "Update")

    def test_is_preparation_only(self):
        self.assertTrue(is_preparation_only("Prepare and Validate File"))
        self.assertFalse(is_preparation_only("Prepare for Insert"))

    def test_preparation_only_message(self):
        self.assertIn("Insert or Update requirements were not checked", preparation_only_message("Workbench"))

    def test_load_action_not_evaluated_when_no_operation(self):
        result = validate_load_action(pd.DataFrame(), [], None, MagicMock())
        self.assertFalse(result["evaluated"])
        self.assertEqual(result["status"], "Not Evaluated")
        self.assertFalse(result["blocks_download"])

    def test_not_evaluated_helper(self):
        result = not_evaluated_load_action_result()
        self.assertEqual(result["status"], "Not Evaluated")

    @patch("validators.workbench_readiness_validator.detect_mapping_collisions", return_value=[])
    @patch("validators.workbench_readiness_validator.get_invalid_rows", return_value=[])
    @patch("validators.workbench_readiness_validator.get_unresolved_rows", return_value=[])
    @patch("validators.workbench_readiness_validator.get_relevant_skipped_files", return_value=[])
    def test_preparation_only_does_not_block_on_update_rules(self, *_mocks):
        context = MagicMock()
        context.metadata_available = True
        context.fallback_config = {}
        context.salesforce_object = "Account"
        context.is_account_template = False
        context.account_type_valid = True
        allowed, _message, details = evaluate_workbench_readiness(
            context,
            [],
            True,
            None,
            {"has_blocking_issues": False},
            not_evaluated_load_action_result(),
            preparation_only=True,
        )
        self.assertTrue(allowed)
        self.assertIn("Load-action-specific checks were not performed", details["warnings"][0])
