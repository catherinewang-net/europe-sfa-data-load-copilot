"""Tests for data preparation warnings."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from core.config import READINESS_STATUS
from services.constants import (
    PREREQ_STATUS_ALREADY_LOADED,
    PREREQ_STATUS_NOT_LOADED,
    PREREQ_STATUS_UNKNOWN,
)
from services.preparation_flow_service import evaluate_preparation_readiness
from services.upload_order_service import (
    build_preparation_warnings,
    is_preparation_warning_acknowledged,
    preparation_warnings_fully_acknowledged,
)
from ui.data_preparation_warnings import (
    _acknowledgement_checkbox_label,
    preparation_warnings_ready,
)


def _contact_prerequisite_plan() -> dict:
    return {
        "steps": [],
        "missing_parents": [{
            "child_template": "Contact",
            "child_object": "Contact",
            "parent_template": "Customers",
            "parent_object": "Account",
            "dependency_field": "AccountId",
            "reason": "Contacts require their parent Customer account.",
            "recommended_action": "Load Customers first or mark as already loaded.",
            "status": PREREQ_STATUS_UNKNOWN,
        }],
        "issues": [],
        "cycles": [],
    }


def _contact_prerequisites() -> list[dict]:
    return [{
        "template": "Customers",
        "object": "Account",
        "dependency_field": "AccountId",
        "reason": "Contacts require their parent Customer account.",
        "status": PREREQ_STATUS_UNKNOWN,
    }]


class DataPreparationWarningsTests(unittest.TestCase):
    @patch("services.upload_order_service.get_prerequisites_for_template")
    @patch("services.upload_order_service.build_upload_order_plan")
    def test_contact_template_includes_customer_prerequisite(
        self,
        mock_build_plan,
        mock_get_prerequisites,
    ):
        mock_build_plan.return_value = _contact_prerequisite_plan()
        mock_get_prerequisites.return_value = {
            "current_template": "Contact",
            "prerequisites": _contact_prerequisites(),
            "steps": [],
            "issues": [],
            "message": "ok",
        }

        warnings = build_preparation_warnings("Contact")
        parent_templates = {warning["parent_template"] for warning in warnings}
        self.assertIn("Customers", parent_templates)
        self.assertTrue(all(warning["message"] for warning in warnings))
        self.assertEqual(
            warnings[0]["message"],
            "Customers should be uploaded before Contact.",
        )

    @patch("services.upload_order_service.get_prerequisites_for_template")
    @patch("services.upload_order_service.build_upload_order_plan")
    def test_already_loaded_prerequisite_counts_as_acknowledged(
        self,
        mock_build_plan,
        mock_get_prerequisites,
    ):
        mock_build_plan.return_value = _contact_prerequisite_plan()
        mock_get_prerequisites.return_value = {
            "current_template": "Contact",
            "prerequisites": _contact_prerequisites(),
            "steps": [],
            "issues": [],
            "message": "ok",
        }

        warnings = build_preparation_warnings(
            "Contact",
            prerequisite_status={"Customers": PREREQ_STATUS_ALREADY_LOADED},
        )
        self.assertTrue(warnings[0]["already_satisfied"])
        self.assertTrue(
            is_preparation_warning_acknowledged(
                warnings[0],
                prerequisite_status={"Customers": PREREQ_STATUS_ALREADY_LOADED},
                preparation_warnings_acknowledged={},
            )
        )

    @patch("services.upload_order_service.get_prerequisites_for_template")
    @patch("services.upload_order_service.build_upload_order_plan")
    def test_unacknowledged_warning_requires_checkbox(
        self,
        mock_build_plan,
        mock_get_prerequisites,
    ):
        mock_build_plan.return_value = _contact_prerequisite_plan()
        mock_get_prerequisites.return_value = {
            "current_template": "Contact",
            "prerequisites": _contact_prerequisites(),
            "steps": [],
            "issues": [],
            "message": "ok",
        }

        warnings = build_preparation_warnings(
            "Contact",
            prerequisite_status={"Customers": PREREQ_STATUS_NOT_LOADED},
        )
        self.assertFalse(
            preparation_warnings_fully_acknowledged(
                warnings,
                prerequisite_status={"Customers": PREREQ_STATUS_NOT_LOADED},
                preparation_warnings_acknowledged={},
            )
        )
        self.assertTrue(
            preparation_warnings_fully_acknowledged(
                warnings,
                prerequisite_status={"Customers": PREREQ_STATUS_NOT_LOADED},
                preparation_warnings_acknowledged={"Customers": True},
            )
        )

    def test_acknowledgement_checkbox_label_uses_parent_template(self):
        self.assertEqual(
            _acknowledgement_checkbox_label("Key Accounts"),
            "I understand Key Accounts must be uploaded first.",
        )
        self.assertEqual(
            _acknowledgement_checkbox_label(""),
            "I understand this prerequisite.",
        )

    @patch("services.upload_order_service.build_preparation_warnings")
    def test_preparation_warnings_ready_helper(self, mock_build_warnings):
        mock_build_warnings.return_value = []
        self.assertTrue(
            preparation_warnings_ready(
                "Products",
                prerequisite_status={},
                preparation_warnings_acknowledged={},
            )
        )

    @patch("services.upload_order_service.build_preparation_warnings")
    def test_readiness_needs_user_action_for_unacknowledged_prerequisites(
        self,
        mock_build_warnings,
    ):
        mock_build_warnings.return_value = [{
            "parent_template": "Customers",
            "required_prerequisite": "Customers",
            "message": "Customers should be uploaded before Contact.",
            "prerequisite_status": PREREQ_STATUS_UNKNOWN,
        }]

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

    @patch("services.upload_order_service.build_preparation_warnings")
    def test_readiness_ready_after_prerequisite_acknowledgement(
        self,
        mock_build_warnings,
    ):
        mock_build_warnings.return_value = [{
            "parent_template": "Customers",
            "required_prerequisite": "Customers",
            "message": "Customers should be uploaded before Contact.",
            "prerequisite_status": PREREQ_STATUS_ALREADY_LOADED,
        }]

        readiness = evaluate_preparation_readiness(
            header_review_complete=True,
            preparation_result={"corrected_df": object(), "manual_review": [], "warnings": []},
            row_correction_plan={"corrections_applied": True},
            workbench_plan=None,
            validation_result={"picklist_validation": {"has_blocking_issues": False}},
            template="Contact",
            deployment_templates=["Contact"],
            upload_prerequisites={"Customers": PREREQ_STATUS_ALREADY_LOADED},
            preparation_warnings_acknowledged={"Customers": True},
            prerequisites_confirmed=True,
        )
        self.assertIn(
            readiness["status"],
            {READINESS_STATUS["READY"], READINESS_STATUS["READY_WITH_WARNINGS"]},
        )


if __name__ == "__main__":
    unittest.main()
