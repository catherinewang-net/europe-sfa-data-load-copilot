"""Tests for object-aware picklist validation after Workbench mapping."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from adapters.sfdx_metadata.models import FieldDefinition, PicklistValue, TemplateDefinition
from services.constants import (
    MAPPING_STATUS_CONFIRMED,
    PICKLIST_METADATA_SOURCE_LOCAL,
    PICKLIST_STATUS_BLANK_REQUIRED,
    PICKLIST_STATUS_INVALID,
    PICKLIST_STATUS_MULTI_INVALID,
    PICKLIST_STATUS_NEEDS_REVIEW,
    PICKLIST_STATUS_NEEDS_USER_ACTION,
    PICKLIST_STATUS_RECORD_TYPE_FALLBACK,
    PICKLIST_STATUS_VALID,
)
from services.picklist_correction_service import (
    apply_picklist_corrections,
    revalidate_picklists_after_corrections,
)
from services.picklist_field_catalog import get_picklist_fields
from services.row_correction_plan_service import _active_columns
from services.template_service import TemplateContext
from validators.picklist_validator import validate_picklists


def _field(
    api_name: str,
    field_type: str,
    *,
    required: bool = False,
    global_value_set: str | None = None,
) -> FieldDefinition:
    return FieldDefinition(
        api_name,
        api_name,
        field_type,
        required,
        global_value_set=global_value_set,
    )


def _mock_adapter() -> MagicMock:
    adapter = MagicMock()
    adapter.get_object_fields.side_effect = lambda obj: {
        "Account": {
            "Name": _field("Name", "string"),
            "L1_Channel__c": _field("L1_Channel__c", "picklist", global_value_set="L1"),
            "Trade_Type__c": _field("Trade_Type__c", "picklist"),
            "Type": _field("Type", "picklist"),
            "Tags__c": _field("Tags__c", "multipicklist"),
            "Status__c": _field("Status__c", "picklist", required=True),
        },
        "Product2": {
            "Family": _field("Family", "picklist"),
        },
        "Order": {
            "Status": _field("Status", "picklist"),
        },
        "Contact": {
            "LeadSource": _field("LeadSource", "picklist"),
        },
    }.get(obj, {})
    adapter.get_picklist_value_details.side_effect = lambda obj, field: {
        ("Account", "L1_Channel__c"): [
            PicklistValue("AWAY FROM HOME", "AWAY FROM HOME"),
            PicklistValue("DISTRIBUTOR", "DISTRIBUTOR"),
            PicklistValue("OLD VALUE", "OLD VALUE", is_active=False),
        ],
        ("Account", "Trade_Type__c"): [
            PicklistValue("TT", "Traditional Trade"),
        ],
        ("Account", "Type"): [
            PicklistValue("Customer", "Customer"),
            PicklistValue("Prospect", "Prospect"),
        ],
        ("Account", "Tags__c"): [
            PicklistValue("AWAY FROM HOME", "AWAY FROM HOME"),
            PicklistValue("DISTRIBUTOR", "DISTRIBUTOR"),
        ],
        ("Account", "Status__c"): [
            PicklistValue("Active", "Active"),
        ],
        ("Product2", "Family"): [PicklistValue("Food", "Food")],
        ("Order", "Status"): [PicklistValue("Draft", "Draft")],
        ("Contact", "LeadSource"): [PicklistValue("Web", "Web")],
    }.get((obj, field), [])
    adapter.get_picklist_values.side_effect = lambda obj, field: [
        value.api_name for value in adapter.get_picklist_value_details(obj, field) if value.is_active
    ]
    adapter.get_allowed_values_for_record_type.side_effect = (
        lambda obj, record_type, field: ["AWAY FROM HOME"]
        if obj == "Account" and record_type == "Customer" and field == "L1_Channel__c"
        else adapter.get_picklist_values(obj, field)
    )
    adapter.has_record_type_picklist_restriction.side_effect = (
        lambda obj, record_type, field: obj == "Account" and record_type == "Customer" and field == "L1_Channel__c"
    )
    return adapter


def _template_context(
    *,
    template_name: str = "Customers",
    object_name: str = "Account",
    record_type_name: str | None = "Customer",
) -> TemplateContext:
    return TemplateContext(
        template_name=template_name,
        metadata_available=True,
        template_definition=TemplateDefinition(
            name=template_name,
            developer_name=f"{template_name}_Account",
            object_api_name=object_name,
            is_active=True,
            api_to_csv_label={"L1_Channel__c": "L1 Channel", "Status__c": "Status"},
            csv_label_to_api={"L1 Channel": "L1_Channel__c", "Status": "Status__c"},
            required_csv_labels=("Status",),
        ),
        salesforce_object=object_name,
        fallback_config=None,
        metadata_message=None,
        record_type_name=record_type_name,
        required_type_value="Customer" if template_name == "Customers" else None,
        account_type_valid=True,
        account_type_error=None,
        is_account_template=template_name in {"Customers", "Prospects", "Wholesalers", "Payers", "Key Account"},
    )


def _rows(*entries: tuple[str, str]) -> list[dict]:
    return [
        {
            "uploaded_column": uploaded,
            "dit_column": uploaded,
            "confirmed_api_field": api_field,
            "status": MAPPING_STATUS_CONFIRMED,
            "resolved": True,
            "action": "map",
        }
        for uploaded, api_field in entries
    ]


class PicklistValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = _mock_adapter()
        self.context = _template_context()

    @patch("validators.picklist_validator.get_adapter")
    def test_non_picklist_fields_are_skipped(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        rows = _rows(("Name", "Name"))
        result = validate_picklists(
            pd.DataFrame({"Name": ["Acme"]}),
            rows,
            self.context,
            use_mapped_columns=True,
        )
        self.assertEqual(result["field_summaries"], [])

    @patch("services.picklist_field_catalog.get_adapter")
    def test_account_l1_channel_is_detected_as_picklist(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        fields = get_picklist_fields("Account", "Customer", self.adapter)
        self.assertIn("L1_Channel__c", [field["field_api_name"] for field in fields])

    @patch("services.picklist_field_catalog.get_adapter")
    def test_account_type_is_detected_as_picklist(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        fields = get_picklist_fields("Account", "Customer", self.adapter)
        self.assertIn("Type", [field["field_api_name"] for field in fields])

    @patch("services.picklist_field_catalog.get_adapter")
    def test_product2_picklists_detected_dynamically(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        fields = get_picklist_fields("Product2", None, self.adapter)
        self.assertEqual([field["field_api_name"] for field in fields], ["Family"])

    @patch("services.picklist_field_catalog.get_adapter")
    def test_order_picklists_detected_dynamically(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        fields = get_picklist_fields("Order", None, self.adapter)
        self.assertEqual([field["field_api_name"] for field in fields], ["Status"])

    @patch("validators.picklist_validator.get_adapter")
    def test_valid_stored_value_passes(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        rows = _rows(("L1 Channel", "L1_Channel__c"))
        result = validate_picklists(
            pd.DataFrame({"L1_Channel__c": ["AWAY FROM HOME"]}),
            rows,
            self.context,
            use_mapped_columns=True,
        )
        self.assertFalse(result["has_blocking_issues"])

    @patch("validators.picklist_validator.get_adapter")
    def test_invalid_value_is_flagged(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        rows = _rows(("L1 Channel", "L1_Channel__c"))
        result = validate_picklists(
            pd.DataFrame({"L1_Channel__c": ["FAKE CHANNEL"]}),
            rows,
            self.context,
            use_mapped_columns=True,
        )
        self.assertTrue(result["has_blocking_issues"])
        self.assertEqual(result["issues"][0]["status"], PICKLIST_STATUS_NEEDS_USER_ACTION)

    @patch("validators.picklist_validator.get_adapter")
    def test_whitespace_around_valid_value_proposed_for_cleanup(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        rows = _rows(("L1 Channel", "L1_Channel__c"))
        result = validate_picklists(
            pd.DataFrame({"L1_Channel__c": ["  AWAY FROM HOME  "]}),
            rows,
            self.context,
            use_mapped_columns=True,
        )
        review = [
            issue for issue in result["issues"]
            if issue["status"] == PICKLIST_STATUS_NEEDS_REVIEW
        ]
        self.assertEqual(len(review), 1)
        self.assertEqual(review[0]["suggested_replacement"], "AWAY FROM HOME")
        self.assertEqual(review[0]["required_api_name"], "AWAY FROM HOME")

    @patch("validators.picklist_validator.get_adapter")
    def test_inactive_value_is_rejected(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        rows = _rows(("L1 Channel", "L1_Channel__c"))
        result = validate_picklists(
            pd.DataFrame({"L1_Channel__c": ["OLD VALUE"]}),
            rows,
            self.context,
            use_mapped_columns=True,
        )
        self.assertTrue(result["has_blocking_issues"])

    @patch("validators.picklist_validator.get_adapter")
    def test_required_blank_picklist_is_flagged(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        rows = _rows(("Status", "Status__c"))
        result = validate_picklists(
            pd.DataFrame({"Status__c": [""]}),
            rows,
            self.context,
            use_mapped_columns=True,
        )
        self.assertTrue(result["has_blocking_issues"])
        self.assertEqual(result["issues"][0]["status"], PICKLIST_STATUS_BLANK_REQUIRED)

    @patch("validators.picklist_validator.get_adapter")
    def test_optional_blank_picklist_is_allowed(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        rows = _rows(("L1 Channel", "L1_Channel__c"))
        result = validate_picklists(
            pd.DataFrame({"L1_Channel__c": [""]}),
            rows,
            self.context,
            use_mapped_columns=True,
        )
        self.assertFalse(result["has_blocking_issues"])
        self.assertEqual(result["issues"][0]["status"], PICKLIST_STATUS_VALID)

    @patch("validators.picklist_validator.get_adapter")
    def test_record_type_restrictions_are_applied(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        rows = _rows(("L1 Channel", "L1_Channel__c"))
        result = validate_picklists(
            pd.DataFrame({"L1_Channel__c": ["DISTRIBUTOR"]}),
            rows,
            self.context,
            use_mapped_columns=True,
        )
        self.assertTrue(result["has_blocking_issues"])

    @patch("validators.picklist_validator.get_adapter")
    def test_object_level_fallback_is_labelled(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        context = _template_context(template_name="Key Account", record_type_name=None)
        rows = _rows(("L1 Channel", "L1_Channel__c"))
        result = validate_picklists(
            pd.DataFrame({"L1_Channel__c": ["DISTRIBUTOR"]}),
            rows,
            context,
            use_mapped_columns=True,
        )
        self.assertEqual(
            result["field_summaries"][0]["validation_source"],
            PICKLIST_STATUS_RECORD_TYPE_FALLBACK,
        )

    @patch("validators.picklist_validator.get_adapter")
    def test_multipicklist_values_split_on_semicolons(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        rows = _rows(("Tags", "Tags__c"))
        result = validate_picklists(
            pd.DataFrame({"Tags__c": ["AWAY FROM HOME;DISTRIBUTOR"]}),
            rows,
            self.context,
            use_mapped_columns=True,
        )
        self.assertFalse(result["has_blocking_issues"])
        self.assertEqual(result["valid_count"], 2)

    @patch("validators.picklist_validator.get_adapter")
    def test_one_invalid_multipicklist_entry_is_flagged(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        rows = _rows(("Tags", "Tags__c"))
        result = validate_picklists(
            pd.DataFrame({"Tags__c": ["AWAY FROM HOME;INVALID VALUE"]}),
            rows,
            self.context,
            use_mapped_columns=True,
        )
        self.assertTrue(result["has_blocking_issues"])
        invalid = [issue for issue in result["issues"] if issue["status"] == PICKLIST_STATUS_MULTI_INVALID]
        self.assertEqual(len(invalid), 1)

    @patch("validators.picklist_validator.get_adapter")
    def test_excluded_columns_are_not_validated(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        rows = [
            *_rows(("L1 Channel", "L1_Channel__c")),
            {
                "uploaded_column": "Notes",
                "dit_column": "Notes",
                "status": "Do Not Include",
                "action": "exclude",
                "resolved": True,
            },
        ]
        original = pd.DataFrame({"L1_Channel__c": ["AWAY FROM HOME"], "Notes": ["secret"]})
        active = _active_columns(original, rows)
        self.assertEqual(active, ["L1_Channel__c"])

    @patch("validators.picklist_validator.get_adapter")
    def test_approved_replacements_update_corrected_df(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        mapped_df = pd.DataFrame({"L1_Channel__c": ["  AWAY FROM HOME  "]})
        validation = validate_picklists(
            mapped_df,
            _rows(("L1 Channel", "L1_Channel__c")),
            self.context,
            use_mapped_columns=True,
        )
        correction = [
            issue for issue in validation["issues"]
            if issue["status"] == PICKLIST_STATUS_NEEDS_REVIEW
        ][0]
        corrected_df, change_log, original_copy = apply_picklist_corrections(
            mapped_df,
            validation,
            [{
                **correction,
                "correction_id": correction["issue_id"],
                "column_name": "L1_Channel__c",
                "proposed_value": "AWAY FROM HOME",
                "field_type": "picklist",
            }],
        )
        self.assertEqual(corrected_df.iloc[0]["L1_Channel__c"], "AWAY FROM HOME")
        self.assertEqual(len(change_log), 1)
        pd.testing.assert_series_equal(original_copy.iloc[:, 0], mapped_df.iloc[:, 0])

    @patch("validators.picklist_validator.get_adapter")
    def test_revalidation_runs_after_replacement(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        mapped_df = pd.DataFrame({"L1_Channel__c": ["  AWAY FROM HOME  "]})
        validation = validate_picklists(
            mapped_df,
            _rows(("L1 Channel", "L1_Channel__c")),
            self.context,
            use_mapped_columns=True,
        )
        correction = [
            issue for issue in validation["issues"]
            if issue["status"] == PICKLIST_STATUS_NEEDS_REVIEW
        ][0]
        corrected_df, _, _ = apply_picklist_corrections(
            mapped_df,
            validation,
            [{
                **correction,
                "correction_id": correction["issue_id"],
                "column_name": "L1_Channel__c",
                "proposed_value": "AWAY FROM HOME",
                "field_type": "picklist",
            }],
        )
        revalidation = revalidate_picklists_after_corrections(
            corrected_df,
            _rows(("L1 Channel", "L1_Channel__c")),
            self.context,
        )
        self.assertFalse(revalidation["has_blocking_issues"])

    @patch("validators.picklist_validator.get_adapter")
    def test_original_uploaded_dataframe_remains_unchanged(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        original = pd.DataFrame({"L1 Channel": ["FAKE CHANNEL"]})
        snapshot = original.copy()
        rows = _rows(("L1 Channel", "L1_Channel__c"))
        validate_picklists(
            pd.DataFrame({"L1_Channel__c": ["FAKE CHANNEL"]}),
            rows,
            self.context,
            use_mapped_columns=True,
        )
        pd.testing.assert_frame_equal(original, snapshot)

    @patch("services.picklist_field_catalog.get_adapter")
    def test_solution_works_for_objects_other_than_account(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        fields = get_picklist_fields("Contact", None, self.adapter)
        self.assertEqual([field["field_api_name"] for field in fields], ["LeadSource"])

    @patch("validators.picklist_validator.get_adapter")
    def test_channel_labeled_text_field_is_skipped(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        rows = _rows(("L1 Channel", "Name"))
        result = validate_picklists(
            pd.DataFrame({"Name": ["AWAY FROM HOME"]}),
            rows,
            self.context,
            use_mapped_columns=True,
        )
        self.assertEqual(result["field_summaries"], [])
        self.assertEqual(result["issues"], [])

    @patch("validators.picklist_validator.get_adapter")
    def test_type_labeled_non_picklist_field_is_skipped(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        rows = _rows(("Account Type Label", "Name"))
        result = validate_picklists(
            pd.DataFrame({"Name": ["Customer"]}),
            rows,
            self.context,
            use_mapped_columns=True,
        )
        self.assertEqual(result["field_summaries"], [])

    @patch("validators.picklist_validator.get_adapter")
    def test_status_labeled_non_picklist_field_is_skipped(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        rows = _rows(("Status Label", "Name"))
        result = validate_picklists(
            pd.DataFrame({"Name": ["Active"]}),
            rows,
            self.context,
            use_mapped_columns=True,
        )
        self.assertEqual(result["field_summaries"], [])

    @patch("validators.picklist_validator.get_adapter")
    def test_metadata_source_is_local(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        rows = _rows(("L1 Channel", "L1_Channel__c"))
        result = validate_picklists(
            pd.DataFrame({"L1_Channel__c": ["AWAY FROM HOME"]}),
            rows,
            self.context,
            use_mapped_columns=True,
        )
        self.assertEqual(
            result["field_summaries"][0]["metadata_source"],
            PICKLIST_METADATA_SOURCE_LOCAL,
        )
        self.assertEqual(
            result["issues"][0]["metadata_source"],
            PICKLIST_METADATA_SOURCE_LOCAL,
        )

    @patch("validators.picklist_validator.get_adapter")
    def test_api_field_name_is_not_treated_as_valid_picklist_value(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        rows = _rows(("L1 Channel", "L1_Channel__c"))
        result = validate_picklists(
            pd.DataFrame({"L1_Channel__c": ["L1_Channel__c"]}),
            rows,
            self.context,
            use_mapped_columns=True,
        )
        self.assertTrue(result["has_blocking_issues"])
        invalid = [
            issue for issue in result["issues"]
            if issue["status"] == PICKLIST_STATUS_NEEDS_USER_ACTION
        ]
        self.assertEqual(len(invalid), 1)

    @patch("validators.picklist_validator.get_adapter")
    def test_picklist_identified_only_from_mapped_api_field_metadata(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        rows = _rows(("L1 Channel", "L1_Channel__c"))
        result = validate_picklists(
            pd.DataFrame({"L1_Channel__c": ["AWAY FROM HOME"]}),
            rows,
            self.context,
            use_mapped_columns=True,
        )
        summary = result["field_summaries"][0]
        self.assertEqual(summary["salesforce_field"], "L1_Channel__c")
        self.assertEqual(summary["field_type"], "picklist")
        self.assertEqual(summary["check_type"], "field_identification")
        self.assertEqual(summary["metadata_source"], PICKLIST_METADATA_SOURCE_LOCAL)

    @patch("validators.picklist_validator.get_adapter")
    def test_exact_api_name_passes(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        rows = _rows(("Trade Type", "Trade_Type__c"))
        result = validate_picklists(
            pd.DataFrame({"Trade_Type__c": ["TT"]}),
            rows,
            self.context,
            use_mapped_columns=True,
        )
        valid = [issue for issue in result["issues"] if issue["status"] == PICKLIST_STATUS_VALID]
        self.assertEqual(len(valid), 1)
        self.assertEqual(valid[0]["required_api_name"], "TT")
        self.assertFalse(result["has_blocking_issues"])

    @patch("validators.picklist_validator.get_adapter")
    def test_display_label_equal_to_api_name_passes(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        rows = _rows(("Type", "Type"))
        result = validate_picklists(
            pd.DataFrame({"Type": ["Customer"]}),
            rows,
            self.context,
            use_mapped_columns=True,
        )
        valid = [issue for issue in result["issues"] if issue["status"] == PICKLIST_STATUS_VALID]
        self.assertEqual(len(valid), 1)
        self.assertFalse(result["has_blocking_issues"])

    @patch("validators.picklist_validator.get_adapter")
    def test_display_label_different_from_api_name_needs_user_action(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        rows = _rows(("Trade Type", "Trade_Type__c"))
        result = validate_picklists(
            pd.DataFrame({"Trade_Type__c": ["Traditional Trade"]}),
            rows,
            self.context,
            use_mapped_columns=True,
        )
        action_needed = [
            issue for issue in result["issues"]
            if issue["status"] == PICKLIST_STATUS_NEEDS_USER_ACTION
        ]
        self.assertEqual(len(action_needed), 1)
        self.assertIsNone(action_needed[0]["suggested_replacement"])
        self.assertTrue(result["has_blocking_issues"])

    @patch("validators.picklist_validator.get_adapter")
    def test_case_mismatch_needs_user_action(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        rows = _rows(("L1 Channel", "L1_Channel__c"))
        result = validate_picklists(
            pd.DataFrame({"L1_Channel__c": ["away from home"]}),
            rows,
            self.context,
            use_mapped_columns=True,
        )
        action_needed = [
            issue for issue in result["issues"]
            if issue["status"] == PICKLIST_STATUS_NEEDS_USER_ACTION
        ]
        self.assertEqual(len(action_needed), 1)
        self.assertIsNone(action_needed[0]["suggested_replacement"])
        self.assertTrue(result["has_blocking_issues"])

    @patch("validators.picklist_validator.get_adapter")
    def test_punctuation_mismatch_needs_user_action(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        rows = _rows(("L1 Channel", "L1_Channel__c"))
        result = validate_picklists(
            pd.DataFrame({"L1_Channel__c": ["AWAY-FROM-HOME"]}),
            rows,
            self.context,
            use_mapped_columns=True,
        )
        action_needed = [
            issue for issue in result["issues"]
            if issue["status"] == PICKLIST_STATUS_NEEDS_USER_ACTION
        ]
        self.assertEqual(len(action_needed), 1)
        self.assertIsNone(action_needed[0]["suggested_replacement"])
        self.assertTrue(result["has_blocking_issues"])

    @patch("validators.picklist_validator.get_adapter")
    def test_whitespace_mismatch_requires_review(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        rows = _rows(("L1 Channel", "L1_Channel__c"))
        result = validate_picklists(
            pd.DataFrame({"L1_Channel__c": [" AWAY FROM HOME "]}),
            rows,
            self.context,
            use_mapped_columns=True,
        )
        review = [issue for issue in result["issues"] if issue["status"] == PICKLIST_STATUS_NEEDS_REVIEW]
        self.assertEqual(len(review), 1)
        self.assertEqual(review[0]["suggested_replacement"], "AWAY FROM HOME")
        self.assertTrue(result["has_blocking_issues"])

    @patch("validators.picklist_validator.get_adapter")
    def test_invalid_value_fails(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        rows = _rows(("Trade Type", "Trade_Type__c"))
        result = validate_picklists(
            pd.DataFrame({"Trade_Type__c": ["Not A Real Value"]}),
            rows,
            self.context,
            use_mapped_columns=True,
        )
        self.assertTrue(result["has_blocking_issues"])
        invalid = [issue for issue in result["issues"] if issue["status"] == PICKLIST_STATUS_NEEDS_USER_ACTION]
        self.assertEqual(len(invalid), 1)

    @patch("validators.picklist_validator.get_adapter")
    def test_inactive_value_fails(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        rows = _rows(("L1 Channel", "L1_Channel__c"))
        result = validate_picklists(
            pd.DataFrame({"L1_Channel__c": ["OLD VALUE"]}),
            rows,
            self.context,
            use_mapped_columns=True,
        )
        self.assertTrue(result["has_blocking_issues"])
        invalid = [issue for issue in result["issues"] if issue["status"] == PICKLIST_STATUS_NEEDS_USER_ACTION]
        self.assertEqual(len(invalid), 1)
        self.assertIn("Inactive", invalid[0]["reason"])

    @patch("validators.picklist_validator.get_adapter")
    def test_corrected_csv_uses_api_name(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        mapped_df = pd.DataFrame({"Trade_Type__c": ["Traditional Trade"]})
        validation = validate_picklists(
            mapped_df,
            _rows(("Trade Type", "Trade_Type__c")),
            self.context,
            use_mapped_columns=True,
        )
        correction = [
            issue for issue in validation["issues"]
            if issue["status"] == PICKLIST_STATUS_NEEDS_USER_ACTION
        ][0]
        corrected_df, _, _ = apply_picklist_corrections(
            mapped_df,
            validation,
            [{
                **correction,
                "correction_id": correction["issue_id"],
                "column_name": "Trade_Type__c",
                "proposed_value": "TT",
                "field_type": "picklist",
            }],
        )
        self.assertEqual(corrected_df.iloc[0]["Trade_Type__c"], "TT")
        revalidation = revalidate_picklists_after_corrections(
            corrected_df,
            _rows(("Trade Type", "Trade_Type__c")),
            self.context,
        )
        self.assertFalse(revalidation["has_blocking_issues"])
        valid = [
            issue for issue in revalidation["issues"]
            if issue["status"] == PICKLIST_STATUS_VALID
        ]
        self.assertEqual(len(valid), 1)

    @patch("validators.picklist_validator.get_adapter")
    def test_multipicklist_validated_using_api_names(self, adapter_mock):
        adapter = _mock_adapter()
        multipicklist_details = {
            ("Account", "Tags__c"): [
                PicklistValue("AFH", "Away From Home"),
                PicklistValue("DIST", "Distributor"),
            ],
        }
        original_side_effect = adapter.get_picklist_value_details.side_effect

        def picklist_details_side_effect(obj, field):
            if (obj, field) in multipicklist_details:
                return multipicklist_details[(obj, field)]
            return original_side_effect(obj, field)

        adapter.get_picklist_value_details.side_effect = picklist_details_side_effect
        adapter_mock.return_value = adapter
        rows = _rows(("Tags", "Tags__c"))
        result = validate_picklists(
            pd.DataFrame({"Tags__c": ["AFH;Away From Home;DIST"]}),
            rows,
            self.context,
            use_mapped_columns=True,
        )
        valid = [issue for issue in result["issues"] if issue["status"] == PICKLIST_STATUS_VALID]
        action_needed = [
            issue for issue in result["issues"]
            if issue["status"] in {PICKLIST_STATUS_NEEDS_USER_ACTION, PICKLIST_STATUS_MULTI_INVALID}
        ]
        self.assertEqual(len(valid), 2)
        self.assertEqual(len(action_needed), 1)
        self.assertIsNone(action_needed[0]["suggested_replacement"])
        self.assertTrue(result["has_blocking_issues"])

    @patch("validators.picklist_validator.get_adapter")
    def test_invalid_row_is_not_deleted(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        mapped_df = pd.DataFrame({"Trade_Type__c": ["Traditional Trade", "TT"]})
        validation = validate_picklists(
            mapped_df,
            _rows(("Trade Type", "Trade_Type__c")),
            self.context,
            use_mapped_columns=True,
        )
        self.assertEqual(len(mapped_df), 2)
        self.assertTrue(validation["has_blocking_issues"])

    @patch("validators.picklist_validator.get_adapter")
    def test_no_fuzzy_replacement_applied(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        from services.picklist_correction_service import build_picklist_correction_plan

        mapped_df = pd.DataFrame({"L1_Channel__c": ["AWAY-FROM-HOME"]})
        validation = validate_picklists(
            mapped_df,
            _rows(("L1 Channel", "L1_Channel__c")),
            self.context,
            use_mapped_columns=True,
        )
        plan = build_picklist_correction_plan(validation, mapped_df)
        self.assertEqual(plan["corrections"][0]["proposed_value"], None)
        self.assertTrue(plan["corrections"][0]["requires_user_selection"])

    @patch("validators.picklist_validator.get_adapter")
    def test_unresolved_invalid_values_block_readiness(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        from services.preparation_flow_service import evaluate_preparation_readiness
        from core.config import READINESS_STATUS

        validation = validate_picklists(
            pd.DataFrame({"Trade_Type__c": ["Traditional Trade"]}),
            _rows(("Trade Type", "Trade_Type__c")),
            self.context,
            use_mapped_columns=True,
        )
        readiness = evaluate_preparation_readiness(
            header_review_complete=True,
            preparation_result={"corrected_df": object(), "manual_review": [], "warnings": []},
            row_correction_plan={"corrections_applied": True},
            workbench_plan=None,
            validation_result={"picklist_validation": validation},
        )
        self.assertEqual(readiness["status"], READINESS_STATUS["NOT_READY"])

    @patch("validators.picklist_validator.get_adapter")
    def test_workbench_output_uses_api_field_headers(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        mapped_df = pd.DataFrame({"L1_Channel__c": ["AWAY FROM HOME"]})
        self.assertIn("L1_Channel__c", mapped_df.columns)
        self.assertNotIn("L1 Channel", mapped_df.columns)

    @patch("validators.picklist_validator.get_adapter")
    def test_dit_keeps_friendly_headers(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        df = pd.DataFrame({"L1 Channel": ["AWAY FROM HOME"]})
        rows = _rows(("L1 Channel", "L1_Channel__c"))
        result = validate_picklists(
            df,
            rows,
            self.context,
            use_mapped_columns=False,
        )
        self.assertEqual(result["field_summaries"][0]["uploaded_column"], "L1 Channel")


class PicklistFieldGroupTests(unittest.TestCase):
    def test_build_picklist_field_groups_groups_by_field(self):
        from services.constants import PICKLIST_STATUS_NEEDS_REVIEW, PICKLIST_STATUS_NEEDS_USER_ACTION
        from services.dit_ux_service import build_picklist_field_groups
        from services.picklist_correction_service import build_picklist_correction_plan

        validation = {
            "field_summaries": [
                {
                    "uploaded_column": "L1 Channel",
                    "salesforce_field": "L1_Channel__c",
                    "allowed_value_count": 2,
                    "valid_row_count": 23,
                    "invalid_row_count": 0,
                },
                {
                    "uploaded_column": "*Market",
                    "salesforce_field": "Market__c",
                    "allowed_value_count": 3,
                    "valid_row_count": 10,
                    "invalid_row_count": 1,
                },
            ],
            "issues": [
                {
                    "issue_id": "l1:2",
                    "row": 2,
                    "uploaded_column": "L1 Channel",
                    "salesforce_api_field": "L1_Channel__c",
                    "uploaded_value": " AWAY FROM HOME ",
                    "allowed_values": ["AWAY FROM HOME", "DISTRIBUTOR"],
                    "status": PICKLIST_STATUS_NEEDS_REVIEW,
                    "suggested_replacement": "AWAY FROM HOME",
                    "reason": "Valid after trimming whitespace; use stored value `AWAY FROM HOME`.",
                },
                {
                    "issue_id": "m:3",
                    "row": 3,
                    "uploaded_column": "*Market",
                    "salesforce_api_field": "Market__c",
                    "uploaded_value": "INVALID",
                    "allowed_values": ["DE", "FR", "UK"],
                    "status": PICKLIST_STATUS_NEEDS_USER_ACTION,
                },
            ],
        }
        mapped_df = pd.DataFrame({
            "L1_Channel__c": [" AWAY FROM HOME "],
            "Market__c": ["INVALID"],
        })
        correctable = build_picklist_correction_plan(validation, mapped_df)["corrections"]

        groups = build_picklist_field_groups(validation, correctable)
        self.assertEqual(len(groups), 2)

        l1_group = next(item for item in groups if item["salesforce_field"] == "L1_Channel__c")
        self.assertEqual(l1_group["friendly_column"], "L1 Channel")
        self.assertEqual(l1_group["status_icon"], "🟡")
        self.assertEqual(l1_group["affected_rows"], 1)
        self.assertTrue(l1_group["whitespace_only"])
        self.assertEqual(l1_group["suggested_example"], '" AWAY FROM HOME " → "AWAY FROM HOME"')

        market_group = next(item for item in groups if item["salesforce_field"] == "Market__c")
        self.assertEqual(market_group["friendly_column"], "*Market")
        self.assertEqual(market_group["status_icon"], "🔴")
        self.assertEqual(market_group["affected_rows"], 1)
        self.assertFalse(market_group["whitespace_only"])
        self.assertIsNone(market_group["suggested_example"])

    def test_build_picklist_column_summary_lines(self):
        from services.dit_ux_service import build_picklist_column_summary_lines
        from services.constants import PICKLIST_STATUS_NEEDS_USER_ACTION, PICKLIST_STATUS_VALID

        validation = {
            "field_summaries": [
                {"uploaded_column": "L1 Channel", "salesforce_field": "L1_Channel__c", "valid_row_count": 24},
                {"uploaded_column": "Promotion Type", "salesforce_field": "Promotion_Type__c", "valid_row_count": 10},
                {"uploaded_column": "Market", "salesforce_field": "Market__c", "valid_row_count": 9},
            ],
            "issues": [
                {"salesforce_api_field": "L1_Channel__c", "status": PICKLIST_STATUS_VALID, "row": 2},
                {"salesforce_api_field": "L1_Channel__c", "status": PICKLIST_STATUS_NEEDS_USER_ACTION, "row": 3},
                {"salesforce_api_field": "L1_Channel__c", "status": PICKLIST_STATUS_NEEDS_USER_ACTION, "row": 4},
                {"salesforce_api_field": "Promotion_Type__c", "status": PICKLIST_STATUS_VALID, "row": 2},
                {"salesforce_api_field": "Market__c", "status": PICKLIST_STATUS_NEEDS_USER_ACTION, "row": 5},
            ],
        }
        lines = build_picklist_column_summary_lines(validation)
        self.assertIn("L1 Channel - 24 valid, 2 need correction", lines)
        self.assertIn("Promotion Type - All values valid", lines)
        self.assertIn("Market - 1 value needs correction", lines)


class PicklistReviewInteractionTests(unittest.TestCase):
    def test_review_button_label_singular(self):
        from services.dit_ux_service import build_picklist_review_button_label

        self.assertEqual(build_picklist_review_button_label(1), "Review 1 Value")

    def test_review_button_label_plural(self):
        from services.dit_ux_service import build_picklist_review_button_label

        self.assertEqual(build_picklist_review_button_label(3), "Review 3 Values")

    def test_count_reviewable_picklist_corrections_excludes_whitespace(self):
        from services.dit_ux_service import count_reviewable_picklist_corrections

        corrections = [
            {"is_whitespace_trim": True, "row": 2},
            {"is_whitespace_trim": False, "row": 3},
            {"is_whitespace_trim": False, "row": 4},
        ]
        self.assertEqual(count_reviewable_picklist_corrections(corrections), 2)

    def test_accordion_uses_single_expanded_field_session_key(self):
        from services.dit_ux_service import (
            SESSION_PICKLIST_REVIEW_EXPANDED_FIELD,
            set_picklist_review_expanded_field,
        )

        session_state: dict = {}
        set_picklist_review_expanded_field(session_state, "Market__c")
        self.assertEqual(session_state[SESSION_PICKLIST_REVIEW_EXPANDED_FIELD], "Market__c")

        set_picklist_review_expanded_field(session_state, "Promotion_Type__c")
        self.assertEqual(session_state[SESSION_PICKLIST_REVIEW_EXPANDED_FIELD], "Promotion_Type__c")
        self.assertEqual(
            len([key for key in session_state if key.startswith("picklist_review_current_row_index_")]),
            1,
        )

    def test_advance_after_save_keeps_field_open_for_next_row(self):
        from services.dit_ux_service import (
            SESSION_PICKLIST_REVIEW_EXPANDED_FIELD,
            advance_picklist_review_after_save,
            picklist_review_row_index_key,
        )

        session_state = {
            SESSION_PICKLIST_REVIEW_EXPANDED_FIELD: "Market__c",
            picklist_review_row_index_key("Market__c"): 1,
        }
        advance_picklist_review_after_save(
            session_state,
            "Market__c",
            remaining_invalid_count=2,
        )
        self.assertEqual(session_state[SESSION_PICKLIST_REVIEW_EXPANDED_FIELD], "Market__c")
        self.assertEqual(session_state[picklist_review_row_index_key("Market__c")], 0)

    def test_advance_after_save_collapses_when_all_fixed(self):
        from services.dit_ux_service import (
            SESSION_PICKLIST_REVIEW_EXPANDED_FIELD,
            advance_picklist_review_after_save,
            picklist_review_row_index_key,
        )

        session_state = {
            SESSION_PICKLIST_REVIEW_EXPANDED_FIELD: "Market__c",
            picklist_review_row_index_key("Market__c"): 0,
        }
        advance_picklist_review_after_save(
            session_state,
            "Market__c",
            remaining_invalid_count=0,
        )
        self.assertNotIn(SESSION_PICKLIST_REVIEW_EXPANDED_FIELD, session_state)
        self.assertNotIn(picklist_review_row_index_key("Market__c"), session_state)

    def test_resolve_picklist_review_row_index_clamps_out_of_range(self):
        from services.dit_ux_service import resolve_picklist_review_row_index

        corrections = [{"correction_id": "a", "row": 2}, {"correction_id": "b", "row": 4}]
        correction, index = resolve_picklist_review_row_index(corrections, 5)
        self.assertEqual(index, 0)
        self.assertEqual(correction["correction_id"], "a")

    @patch("validators.picklist_validator.get_adapter")
    def test_inline_save_updates_corrected_df_and_row_count(self, adapter_mock):
        adapter_mock.return_value = _mock_adapter()

        mapped_df = pd.DataFrame({"Trade_Type__c": ["Traditional Trade", "Not A Real Value"]})
        validation = validate_picklists(
            mapped_df,
            _rows(("Trade Type", "Trade_Type__c")),
            _template_context(),
            use_mapped_columns=True,
        )
        self.assertEqual(validation["invalid_count"], 2)

        correction = [
            issue for issue in validation["issues"]
            if issue["status"] == PICKLIST_STATUS_NEEDS_USER_ACTION and issue["row"] == 2
        ][0]
        corrected_df, _, _ = apply_picklist_corrections(
            mapped_df,
            validation,
            [{
                **correction,
                "correction_id": correction["issue_id"],
                "column_name": "Trade_Type__c",
                "proposed_value": "TT",
                "field_type": "picklist",
            }],
        )
        revalidation = revalidate_picklists_after_corrections(
            corrected_df,
            _rows(("Trade Type", "Trade_Type__c")),
            _template_context(),
        )
        self.assertEqual(corrected_df.iloc[0]["Trade_Type__c"], "TT")
        self.assertEqual(revalidation["invalid_count"], 1)

    def test_all_values_valid_message_constant(self):
        from ui.picklist_validation import PICKLIST_ALL_VALID_MESSAGE

        self.assertEqual(PICKLIST_ALL_VALID_MESSAGE, "✓ All values are valid.")

    def test_inline_editor_renders_within_field_card_not_page_bottom(self):
        import inspect

        from ui.picklist_validation import (
            _render_inline_picklist_editor,
            _render_picklist_field_card,
            render_picklist_validation,
        )

        render_source = inspect.getsource(render_picklist_validation)
        card_source = inspect.getsource(_render_picklist_field_card)
        self.assertIn("for field_group in field_groups:", render_source)
        self.assertIn("_render_picklist_field_card", render_source)
        self.assertNotIn("_render_picklist_expandable_rows", render_source)
        self.assertNotIn("Review Individually", render_source)
        self.assertIn("_render_inline_picklist_editor", card_source)
        self.assertIn("build_picklist_review_button_label", card_source)
        self.assertIn("render_picklist_issue_editor", inspect.getsource(_render_inline_picklist_editor))
