"""Tests for Data Import Tool UX improvements (16 scenarios)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from adapters.sfdx_metadata.models import TemplateDefinition
from services.constants import (
    PICKLIST_STATUS_INVALID,
    PICKLIST_STATUS_NEEDS_REVIEW,
    PICKLIST_STATUS_NEEDS_USER_ACTION,
    PICKLIST_STATUS_VALID,
    PREREQ_STATUS_ALREADY_LOADED,
    PREREQ_STATUS_NOT_LOADED,
    PREREQ_STATUS_UNKNOWN,
)
from services.dit_ux_service import (
    DEFAULT_PICKLIST_FILTERS,
    HEADER_ACTION_EXCLUDE,
    HEADER_ACTION_KEEP,
    HEADER_ACTION_RENAME,
    HEADER_ACTION_SKIP_OPTIONAL,
    OPTIONAL_BADGE,
    REQUIRED_BADGE,
    SESSION_HEADER_DECISIONS,
    SESSION_OPTIONAL_EXCLUSIONS,
    SESSION_PICKLIST_FILTER,
    SESSION_PREREQ_CONFIRMED,
    approve_all_high_confidence_headers,
    available_header_actions,
    build_dit_header_review_rows,
    build_picklist_review_rows,
    build_picklist_status_summary,
    build_structure_change_lines,
    build_template_readiness_summary,
    evaluate_prerequisite_gate,
    exclude_all_optional_unmapped,
    filter_picklist_issues,
    format_reorder_message,
    group_repeated_picklist_mismatches,
    is_required_dit_header,
    optional_exclusions_block_readiness,
    requiredness_badge,
    resolve_header_decisions_to_change_ids,
)
from services.file_preparation_service import apply_correction_changes, prepare_file
from services.template_service import TemplateContext
from ui.upload_order import (
    STATUS_BLOCKED,
    STATUS_DISPLAY,
    STATUS_NEEDS_CONFIRMATION,
    STATUS_UPLOADED,
    build_upload_order_view_model,
    map_prereq_to_ui_status,
)

RETAIL_PROMOTION_TEMPLATE = TemplateDefinition(
    name="Retail Promotion",
    developer_name="Retail_Promotion",
    object_api_name="RetailPromotion__c",
    is_active=True,
    api_to_csv_label={
        "Name": "*Promotion Name",
        "Market__c": "*Market",
    },
    csv_label_to_api={
        "*Promotion Name": "Name",
        "*Market": "Market__c",
        "Key Account/Banner Value": "KeyAccountBannerValue__c",
    },
    required_csv_labels=("*Promotion Name", "*Market"),
)


def _template_context() -> TemplateContext:
    return TemplateContext(
        template_name="Retail Promotion",
        metadata_available=True,
        template_definition=RETAIL_PROMOTION_TEMPLATE,
        salesforce_object="RetailPromotion__c",
        fallback_config=None,
        metadata_message=None,
        record_type_name=None,
        required_type_value=None,
        account_type_valid=True,
        account_type_error=None,
        is_account_template=False,
    )


def _sample_correction_plan(**overrides) -> dict:
    plan = {
        "upload_method": "Data Import Tool",
        "template": "Retail Promotion",
        "target_headers": [
            "*Promotion Name",
            "*Market",
            "Key Account/Banner Value",
        ],
        "proposed_renames": [{
            "source_column": "Promotion Name",
            "target_column": "*Promotion Name",
            "confidence": "High",
            "match_type": "normalized",
        }],
        "comparison_result": {
            "comparison": {
                "matching_headers": ["*Market"],
                "missing_columns": [],
                "optional_missing_columns": ["Key Account/Banner Value"],
                "extra_columns": ["Extra Notes"],
                "proposed_renames": [{
                    "source_column": "Promotion Name",
                    "target_column": "*Promotion Name",
                }],
            },
        },
        "changes": [
            {
                "change_id": "rename:Promotion Name->*Promotion Name",
                "category": "rename",
                "source_column": "Promotion Name",
                "target_column": "*Promotion Name",
                "safe": False,
                "requires_confirmation": True,
            },
            {
                "change_id": "exclude:Extra Notes",
                "category": "exclude_extra_column",
                "source_column": "Extra Notes",
                "requiredness": "Optional",
                "safe": False,
                "requires_confirmation": True,
            },
            {
                "change_id": "reorder:columns",
                "category": "reorder_columns",
                "safe": True,
                "requires_confirmation": False,
            },
            {
                "change_id": "empty:Key Account/Banner Value",
                "category": "add_empty_optional_column",
                "target_column": "Key Account/Banner Value",
                "safe": False,
                "requires_confirmation": True,
            },
        ],
        "manual_review": [],
        "safe_changes": [
            {
                "change_id": "reorder:columns",
                "category": "reorder_columns",
                "safe": True,
            },
        ],
        "summary": {
            "rename": 1,
            "reorder_columns": 1,
            "exclude_extra_column": 1,
            "add_empty_optional_column": 1,
            "manual_review": 0,
        },
    }
    plan.update(overrides)
    return plan


class DitUxTests(unittest.TestCase):
    def test_01_required_vs_optional_badges(self):
        ctx = _template_context()
        self.assertTrue(is_required_dit_header("*Promotion Name", ctx))
        self.assertFalse(is_required_dit_header("Key Account/Banner Value", ctx))
        self.assertEqual(requiredness_badge("*Market", ctx), REQUIRED_BADGE)
        self.assertEqual(requiredness_badge("Key Account/Banner Value", ctx), OPTIONAL_BADGE)

    def test_02_optional_exclusions_do_not_block_readiness(self):
        plan = _sample_correction_plan()
        enabled = {"exclude:Extra Notes", "reorder:columns"}
        self.assertFalse(optional_exclusions_block_readiness(plan, enabled))

        blocking_plan = _sample_correction_plan(manual_review=[{
            "category": "required_data_missing",
            "target_column": "*Promotion Name",
        }])
        self.assertTrue(optional_exclusions_block_readiness(blocking_plan, set()))

    def test_03_header_review_rows_include_required_optional_and_actions(self):
        rows = build_dit_header_review_rows(_sample_correction_plan(), _template_context())
        rename_row = next(row for row in rows if row["uploaded_header"] == "Promotion Name")
        self.assertEqual(rename_row["target_header"], "*Promotion Name")
        self.assertEqual(rename_row["requiredness"], REQUIRED_BADGE)
        self.assertIn(HEADER_ACTION_RENAME, rename_row["actions"])
        self.assertIn(HEADER_ACTION_KEEP, rename_row["actions"])

        exclude_row = next(row for row in rows if row["uploaded_header"] == "Extra Notes")
        self.assertEqual(exclude_row["requiredness"], OPTIONAL_BADGE)
        self.assertIn(HEADER_ACTION_EXCLUDE, exclude_row["actions"])

        optional_missing = next(
            row for row in rows if row["target_header"] == "Key Account/Banner Value"
        )
        self.assertIn(HEADER_ACTION_SKIP_OPTIONAL, optional_missing["actions"])

    def test_04_reorder_wording_is_business_friendly(self):
        message = format_reorder_message("Retail Promotion", 1)
        self.assertIn("Column order will be updated", message)
        self.assertIn("Retail Promotion", message)
        self.assertNotIn("Reorder columns: 1", message)

        lines = build_structure_change_lines({"reorder_columns": 1}, "Retail Promotion")
        self.assertEqual(len(lines), 1)
        self.assertIn("Retail Promotion", lines[0])

    def test_05_picklist_review_shows_allowed_values_not_count(self):
        validation = {
            "field_summaries": [{
                "uploaded_column": "*Market",
                "salesforce_field": "Market__c",
                "allowed_value_count": 5,
                "allowed_values": ["DE", "FR", "UK"],
            }],
            "issues": [{
                "issue_id": "m1",
                "row": 2,
                "uploaded_column": "*Market",
                "salesforce_api_field": "Market__c",
                "uploaded_value": "INVALID",
                "allowed_values": ["DE", "FR", "UK"],
                "reason": "Value not in picklist",
                "status": PICKLIST_STATUS_NEEDS_USER_ACTION,
            }],
        }
        rows = build_picklist_review_rows(validation)
        self.assertEqual(rows[0]["allowed_values_display"], "DE, FR, UK")
        self.assertNotIn("allowed_value_count", rows[0])

    def test_06_picklist_summary_uses_actionable_language(self):
        validation = {
            "field_summaries": [{"valid_row_count": 3}],
            "issues": [
                {"status": PICKLIST_STATUS_VALID},
                {"status": PICKLIST_STATUS_NEEDS_REVIEW},
                {"status": PICKLIST_STATUS_NEEDS_USER_ACTION},
            ],
        }
        summary = build_picklist_status_summary(validation)
        self.assertIn("Valid", summary)
        self.assertIn("Needs Review", summary)
        self.assertIn("Needs User Action", summary)
        self.assertIn("Not Checked", summary)

    def test_07_default_picklist_filter_is_needs_review_and_invalid(self):
        issues = [
            {"status": PICKLIST_STATUS_VALID},
            {"status": PICKLIST_STATUS_NEEDS_REVIEW},
            {"status": PICKLIST_STATUS_NEEDS_USER_ACTION},
        ]
        filtered = filter_picklist_issues(issues)
        statuses = {issue["status"] for issue in filtered}
        self.assertIn(PICKLIST_STATUS_NEEDS_REVIEW, statuses)
        self.assertIn(PICKLIST_STATUS_NEEDS_USER_ACTION, statuses)
        self.assertNotIn(PICKLIST_STATUS_VALID, statuses)
        self.assertEqual(set(DEFAULT_PICKLIST_FILTERS), {
            PICKLIST_STATUS_NEEDS_REVIEW,
            PICKLIST_STATUS_NEEDS_USER_ACTION,
            PICKLIST_STATUS_INVALID,
            "Multipicklist Value Invalid",
        })

    def test_08_repeated_whitespace_trims_group_for_bulk_actions(self):
        corrections = [
            {
                "correction_id": "a",
                "salesforce_api_field": "Market__c",
                "uploaded_value": " BAD ",
                "is_whitespace_trim": True,
                "proposed_value": "BAD",
            },
            {
                "correction_id": "b",
                "salesforce_api_field": "Market__c",
                "uploaded_value": " BAD ",
                "is_whitespace_trim": True,
                "proposed_value": "BAD",
            },
            {
                "correction_id": "c",
                "salesforce_api_field": "Market__c",
                "uploaded_value": "OTHER",
                "is_whitespace_trim": False,
            },
        ]
        groups = group_repeated_picklist_mismatches(corrections)
        self.assertEqual(len(groups[("Market__c", " BAD ")]), 2)
        self.assertEqual(len(groups), 1)

    def test_09_corrected_csv_flow_applies_header_and_picklist_changes(self):
        df = pd.DataFrame({
            "Promotion Name": ["Promo A"],
            "*Market": ["INVALID"],
            "Extra Notes": ["note"],
        })
        plan = _sample_correction_plan()
        enabled = resolve_header_decisions_to_change_ids(
            plan,
            {
                "Promotion Name": HEADER_ACTION_RENAME,
                "Extra Notes": HEADER_ACTION_EXCLUDE,
                "Key Account/Banner Value": HEADER_ACTION_SKIP_OPTIONAL,
            },
        )
        corrected = apply_correction_changes(df, plan, enabled)
        self.assertIn("*Promotion Name", corrected.columns)
        self.assertNotIn("Extra Notes", corrected.columns)
        self.assertNotIn("Promotion Name", corrected.columns)

    def test_10_single_file_upload_prerequisites_mode(self):
        plan = {
            "steps": [{
                "step": 1,
                "template": "Customer to Route",
                "object": "CustomerToRoute__c",
                "reason": "Depends on Customers.",
                "required_parent": "Customers",
                "dependency_field": "Customer__c",
                "readiness": "Blocked",
                "prerequisite_status": PREREQ_STATUS_NOT_LOADED,
                "parents": [{
                    "template": "Customers",
                    "object": "Account",
                    "dependency_field": "Customer__c",
                    "reason": "Lookup parent.",
                }],
            }],
            "cycles": [],
            "missing_parents": [],
            "issues": [],
        }
        view = build_upload_order_view_model(
            plan,
            deployment_templates=["Customer to Route"],
            current_template="Customer to Route",
            prerequisite_status={"Customers": PREREQ_STATUS_NOT_LOADED},
        )
        self.assertTrue(view["single_file"])

    def test_11_multi_file_recommended_upload_order_mode(self):
        plan = {
            "steps": [
                {"step": 1, "template": "Customers", "object": "Account", "reason": "First.", "readiness": "Ready", "parents": []},
                {"step": 2, "template": "Contact", "object": "Contact", "reason": "Second.", "readiness": "Ready", "parents": []},
            ],
            "cycles": [],
            "missing_parents": [],
            "issues": [],
        }
        view = build_upload_order_view_model(
            plan,
            deployment_templates=["Customers", "Contact"],
            current_template="Contact",
            prerequisite_status={},
        )
        self.assertFalse(view["single_file"])
        self.assertEqual(len(view["steps"]), 2)

    def test_12_prerequisite_status_icons_and_labels(self):
        self.assertEqual(map_prereq_to_ui_status(PREREQ_STATUS_ALREADY_LOADED), STATUS_UPLOADED)
        self.assertEqual(STATUS_DISPLAY[STATUS_UPLOADED]["label"], "Confirmed Uploaded")
        self.assertEqual(STATUS_DISPLAY[STATUS_UPLOADED]["icon"], "✅")
        self.assertEqual(STATUS_DISPLAY[STATUS_NEEDS_CONFIRMATION]["icon"], "🟡")
        self.assertEqual(STATUS_DISPLAY[STATUS_BLOCKED]["label"], "Not Uploaded")
        self.assertEqual(STATUS_DISPLAY[STATUS_BLOCKED]["icon"], "🔴")

    def test_13_prerequisite_gate_requires_confirmation_checkbox(self):
        dependencies = [{"template": "Customers"}]
        can_continue, message = evaluate_prerequisite_gate(
            dependencies,
            {"Customers": PREREQ_STATUS_UNKNOWN},
            confirmed=False,
        )
        self.assertFalse(can_continue)
        self.assertIn("confirm", message.lower())

        can_continue_confirmed, _ = evaluate_prerequisite_gate(
            dependencies,
            {"Customers": PREREQ_STATUS_UNKNOWN},
            confirmed=True,
        )
        self.assertTrue(can_continue_confirmed)

    def test_14_template_readiness_summary_metrics(self):
        summary = build_template_readiness_summary(
            correction_plan=_sample_correction_plan(),
            picklist_validation={"issues": [{"status": PICKLIST_STATUS_NEEDS_USER_ACTION}]},
            prerequisite_status={"Customers": PREREQ_STATUS_NOT_LOADED},
            upload_order_plan={"message": "Order ready."},
            enabled_change_ids={"exclude:Extra Notes"},
            picklist_corrections_applied=2,
            template="Retail Promotion",
        )
        self.assertIn("required_present", summary)
        self.assertIn("optional_excluded", summary)
        self.assertEqual(summary["picklist_corrections_applied"], 2)
        self.assertIn("next_action", summary)

    def test_15_session_state_keys_are_defined(self):
        self.assertEqual(SESSION_OPTIONAL_EXCLUSIONS, "dit_optional_exclusions")
        self.assertEqual(SESSION_HEADER_DECISIONS, "dit_header_review_decisions")
        self.assertEqual(SESSION_PICKLIST_FILTER, "picklist_filter_statuses")
        self.assertEqual(SESSION_PREREQ_CONFIRMED, "upload_prerequisites_confirmed")

    def test_16_header_decision_helpers_and_bulk_approvals(self):
        plan = _sample_correction_plan()
        ctx = _template_context()

        high_confidence = approve_all_high_confidence_headers(plan)
        self.assertIn("rename:Promotion Name->*Promotion Name", high_confidence)
        self.assertIn("reorder:columns", high_confidence)

        optional_only = exclude_all_optional_unmapped(plan, ctx)
        self.assertIn("exclude:Extra Notes", optional_only)
        self.assertIn("rename:Promotion Name->*Promotion Name", optional_only)

        required_actions = available_header_actions(required=True, has_rename=True, is_extra=False)
        self.assertNotIn(HEADER_ACTION_EXCLUDE, required_actions)

        enabled = resolve_header_decisions_to_change_ids(
            plan,
            {
                "Promotion Name": HEADER_ACTION_RENAME,
                "Extra Notes": HEADER_ACTION_EXCLUDE,
                "Key Account/Banner Value": HEADER_ACTION_SKIP_OPTIONAL,
                "*Market": HEADER_ACTION_KEEP,
            },
        )
        self.assertIn("rename:Promotion Name->*Promotion Name", enabled)
        self.assertIn("exclude:Extra Notes", enabled)
        self.assertNotIn("empty:Key Account/Banner Value", enabled)


if __name__ == "__main__":
    unittest.main()
