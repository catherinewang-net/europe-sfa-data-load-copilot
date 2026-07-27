"""Tests for upload order UI view model and session helpers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from services.constants import (
    PREREQ_STATUS_ALREADY_LOADED,
    PREREQ_STATUS_INCLUDED,
    PREREQ_STATUS_NOT_LOADED,
    PREREQ_STATUS_UNKNOWN,
)
from ui.upload_order import (
    STATUS_BLOCKED,
    STATUS_DISPLAY,
    STATUS_NEEDS_CONFIRMATION,
    STATUS_READY,
    STATUS_UPLOADED,
    build_dependency_table_rows,
    build_step_dependencies,
    build_upload_order_view_model,
    compute_next_recommended_action,
    map_prereq_to_ui_status,
    merge_prerequisite_updates,
    sync_deployment_prerequisites,
)


def _sample_plan(
    *,
    readiness: str = "Blocked",
    parent_template: str = "Customers",
    child_template: str = "Customer to Route",
) -> dict:
    return {
        "steps": [{
            "step": 1,
            "template": child_template,
            "object": "CustomerToRoute__c",
            "reason": f"{child_template} references {parent_template}.",
            "required_parent": parent_template,
            "dependency_field": "Customer__c",
            "readiness": readiness,
            "prerequisite_status": PREREQ_STATUS_NOT_LOADED,
            "parents": [{
                "template": parent_template,
                "object": "Account",
                "dependency_field": "Customer__c",
                "reason": f"{child_template} lookup references {parent_template}.",
            }],
        }],
        "cycles": [],
        "missing_parents": [],
        "issues": [],
        "message": "Recommended upload order calculated from metadata and business rules.",
    }


class UploadOrderUiTests(unittest.TestCase):
    def test_01_uploaded_dependencies_show_success_status(self):
        status = map_prereq_to_ui_status(PREREQ_STATUS_ALREADY_LOADED)
        self.assertEqual(status, STATUS_UPLOADED)
        self.assertEqual(STATUS_DISPLAY[status]["label"], "Confirmed Uploaded")
        self.assertIn("icon", STATUS_DISPLAY[status])

        plan = _sample_plan(readiness="Ready")
        view = build_upload_order_view_model(
            plan,
            deployment_templates=["Customer to Route"],
            current_template="Customer to Route",
            prerequisite_status={plan["steps"][0]["parents"][0]["template"]: PREREQ_STATUS_ALREADY_LOADED},
        )
        dep = view["steps"][0]["dependencies"][0]
        self.assertEqual(dep["status"], STATUS_UPLOADED)

    def test_02_missing_dependencies_show_blocked_status(self):
        plan = _sample_plan(readiness="Blocked")
        view = build_upload_order_view_model(
            plan,
            deployment_templates=["Customer to Route"],
            current_template="Customer to Route",
            prerequisite_status={"Customers": PREREQ_STATUS_NOT_LOADED},
        )
        step = view["steps"][0]
        self.assertEqual(step["status"], STATUS_BLOCKED)
        self.assertEqual(step["missing"], ["Customers"])

    def test_03_all_prerequisites_complete_changes_status_to_ready(self):
        plan = _sample_plan(readiness="Ready")
        view = build_upload_order_view_model(
            plan,
            deployment_templates=["Customer to Route"],
            current_template="Customer to Route",
            prerequisite_status={"Customers": PREREQ_STATUS_ALREADY_LOADED},
        )
        self.assertEqual(view["steps"][0]["status"], STATUS_READY)

    def test_04_unsure_status_creates_needs_confirmation(self):
        status = map_prereq_to_ui_status(PREREQ_STATUS_UNKNOWN)
        self.assertEqual(status, STATUS_NEEDS_CONFIRMATION)

        plan = _sample_plan(readiness="Needs Review")
        view = build_upload_order_view_model(
            plan,
            deployment_templates=["Customer to Route"],
            current_template="Customer to Route",
            prerequisite_status={"Customers": PREREQ_STATUS_UNKNOWN},
        )
        self.assertEqual(view["steps"][0]["status"], STATUS_NEEDS_CONFIRMATION)

    @patch("ui.upload_order.st.session_state", new_callable=dict)
    def test_05_session_state_preserves_checkbox_selections(self, session_state):
        session_state["upload_order_deployment_key"] = ("Customer to Route",)
        session_state["upload_prerequisites"] = {"Customers": PREREQ_STATUS_ALREADY_LOADED}

        stored = sync_deployment_prerequisites(["Customer to Route"], None)
        self.assertEqual(stored["Customers"], PREREQ_STATUS_ALREADY_LOADED)

        merged = merge_prerequisite_updates(
            stored,
            {"Products": PREREQ_STATUS_INCLUDED},
        )
        self.assertEqual(merged["Customers"], PREREQ_STATUS_ALREADY_LOADED)
        self.assertEqual(merged["Products"], PREREQ_STATUS_INCLUDED)

    def test_06_next_recommended_action_updates_dynamically(self):
        blocked_plan = _sample_plan(readiness="Blocked")
        blocked_view = build_upload_order_view_model(
            blocked_plan,
            deployment_templates=["Customer to Route"],
            current_template="Customer to Route",
            prerequisite_status={"Customers": PREREQ_STATUS_NOT_LOADED},
        )
        blocked_action = blocked_view["next_action"]
        self.assertIn("Customers", blocked_action["headline"])

        ready_plan = _sample_plan(readiness="Ready")
        ready_view = build_upload_order_view_model(
            ready_plan,
            deployment_templates=["Customer to Route"],
            current_template="Customer to Route",
            prerequisite_status={"Customers": PREREQ_STATUS_ALREADY_LOADED},
        )
        ready_action = ready_view["next_action"]
        self.assertIn("Customer to Route", ready_action["headline"])
        self.assertNotEqual(blocked_action["headline"], ready_action["headline"])

    def test_07_single_file_mode_renders_correctly(self):
        plan = _sample_plan(readiness="Blocked")
        view = build_upload_order_view_model(
            plan,
            deployment_templates=["Customer to Route"],
            current_template="Customer to Route",
            prerequisite_status={},
        )
        self.assertTrue(view["single_file"])
        self.assertEqual(view["current_template"], "Customer to Route")
        self.assertEqual(len(view["steps"]), 1)

    def test_08_multi_file_mode_renders_correctly(self):
        plan = {
            "steps": [
                {
                    "step": 1,
                    "template": "Customers",
                    "object": "Account",
                    "reason": "No parents.",
                    "required_parent": "None",
                    "dependency_field": "Metadata / business rule",
                    "readiness": "Ready",
                    "prerequisite_status": PREREQ_STATUS_INCLUDED,
                    "parents": [],
                },
                {
                    "step": 2,
                    "template": "Contact",
                    "object": "Contact",
                    "reason": "Contact references Customers.",
                    "required_parent": "Customers",
                    "dependency_field": "AccountId",
                    "readiness": "Ready",
                    "prerequisite_status": PREREQ_STATUS_INCLUDED,
                    "parents": [{
                        "template": "Customers",
                        "object": "Account",
                        "dependency_field": "AccountId",
                        "reason": "Contact lookup references Account.",
                    }],
                },
            ],
            "cycles": [],
            "missing_parents": [],
            "issues": [],
            "message": "Recommended upload order calculated.",
        }
        view = build_upload_order_view_model(
            plan,
            deployment_templates=["Customers", "Contact"],
            current_template="Contact",
            prerequisite_status={},
        )
        self.assertFalse(view["single_file"])
        self.assertEqual(len(view["steps"]), 2)
        self.assertEqual(view["steps"][0]["sequence"], 1)
        self.assertEqual(view["steps"][1]["sequence"], 2)

    def test_09_detailed_table_remains_available(self):
        plan = _sample_plan(readiness="Blocked")
        rows = build_dependency_table_rows(plan)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Template"], "Customer to Route")
        self.assertIn("Readiness", rows[0])
        self.assertIn("Required parent", rows[0])

    def test_10_status_labels_remain_visible_without_relying_only_on_color(self):
        for status_key, display in STATUS_DISPLAY.items():
            self.assertTrue(display.get("icon"), f"{status_key} missing icon")
            self.assertTrue(display.get("label"), f"{status_key} missing label")
            self.assertTrue(display.get("explanation"), f"{status_key} missing explanation")

    @patch("ui.upload_order.st.session_state", new_callable=dict)
    def test_deployment_change_resets_prerequisites(self, session_state):
        session_state["upload_order_deployment_key"] = ("Customers",)
        session_state["upload_prerequisites"] = {"Customers": PREREQ_STATUS_ALREADY_LOADED}

        stored = sync_deployment_prerequisites(["Customers", "Contact"], None)
        self.assertEqual(stored, {})
        self.assertEqual(session_state["upload_prerequisites"], {})

    def test_included_dependency_maps_to_included_status(self):
        deps = build_step_dependencies(
            {
                "parents": [{
                    "template": "Customers",
                    "object": "Account",
                    "dependency_field": "AccountId",
                    "reason": "Included in batch.",
                }],
            },
            included_templates={"Customers", "Contact"},
            prerequisite_status={},
        )
        self.assertEqual(deps[0]["prerequisite_status"], PREREQ_STATUS_INCLUDED)

    def test_cycle_next_action_warns_user(self):
        plan = _sample_plan()
        plan["cycles"] = [["Template A", "Template B", "Template A"]]
        plan["message"] = "Upload order could not be fully resolved because a circular dependency was detected."
        action = compute_next_recommended_action([], plan)
        self.assertIn("circular", action["headline"].lower())


if __name__ == "__main__":
    unittest.main()
