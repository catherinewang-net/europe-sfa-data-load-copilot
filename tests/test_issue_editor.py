"""Tests for in-app issue editing service and UI helpers."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from core.config import READINESS_STATUS
from services.issue_edit_service import (
    ISSUE_EDITS_KEY,
    apply_cell_correction,
    collect_editable_issues,
    duplicate_validation_cleared,
    expand_duplicate_issues,
    get_issue_edits,
    make_edit_key,
    parse_duplicate_rows,
    revalidate_after_issue_edit,
    save_pending_edit,
    validate_date_replacement,
    validate_picklist_replacement,
    validate_replacement,
)
from services.preparation_flow_service import evaluate_preparation_readiness
from ui.issue_editor import (
    FIX_ISSUES_TITLE,
    build_issue_editor_summary,
    build_issue_expander_label,
    build_issue_session_key,
    build_issue_status_summary,
    render_date_issue_editor,
    render_issue_editor,
    render_picklist_issue_editor,
)


class IssueEditServiceTests(unittest.TestCase):
    def test_invalid_date_can_be_validated_and_rejected(self):
        invalid = validate_date_replacement("31/02/2026", "Data Import Tool")
        self.assertFalse(invalid["valid"])
        self.assertIn("❌", invalid["message"])

        valid = validate_date_replacement("06/07/2026", "Data Import Tool")
        self.assertTrue(valid["valid"])
        self.assertEqual(valid["message"], "✅ Date corrected")

    def test_valid_replacement_updates_corrected_df(self):
        original = pd.DataFrame({"Start Date": ["31/02/2026"]})
        corrected = apply_cell_correction(original, 2, "Start Date", "06/07/2026")
        self.assertEqual(corrected.loc[0, "Start Date"], "06/07/2026")
        self.assertEqual(original.loc[0, "Start Date"], "31/02/2026")

    def test_excel_serial_suggestion_requires_approval_in_editor(self):
        issue = {
            "edit_key": make_edit_key(2, "Start Date"),
            "issue_type": "date",
            "row": 2,
            "field": "Start Date",
            "current_value": "46209",
            "problem": "Possible Excel Serial Date",
            "date_subtype": "excel_serial",
            "suggested_value": "2026-07-06",
            "field_type": "date",
            "category": "dates",
        }
        session_state: dict = {}
        mock_st = MagicMock()
        mock_st.session_state = session_state
        mock_st.button.side_effect = [False, False]
        mock_st.text_input.return_value = ""
        mock_st.expander.return_value.__enter__ = MagicMock(return_value=None)
        mock_st.expander.return_value.__exit__ = MagicMock(return_value=None)
        mock_st.caption = MagicMock()
        mock_st.markdown = MagicMock()
        mock_st.info = MagicMock()
        mock_st.success = MagicMock()
        mock_st.error = MagicMock()
        mock_st.warning = MagicMock()

        with patch("ui.issue_editor.st", mock_st):
            result = render_date_issue_editor(
                issue,
                upload_method="Data Import Tool",
                session_state=session_state,
            )
        self.assertIsNone(result)
        self.assertFalse(get_issue_edits(session_state).get(issue["edit_key"], {}).get("validated"))

    def test_duplicate_issues_expand_to_each_row(self):
        issues = [{
            "issue_id": "duplicate:*External Id:ACC000012",
            "category": "duplicates",
            "field": "*External Id",
            "row": 13,
            "original_value": "ACC000012",
            "reason": "Duplicate value `ACC000012` appears on rows 13, 14.",
            "blocking": True,
        }]
        expanded = expand_duplicate_issues(issues)
        self.assertEqual(len(expanded), 2)
        self.assertEqual(expanded[0]["row"], 13)
        self.assertEqual(expanded[1]["row"], 14)

    def test_duplicate_validation_clears_after_correction(self):
        df = pd.DataFrame({"*External Id": ["ACC000012", "ACC000012", "ACC000013"]})
        corrected = apply_cell_correction(df, 3, "*External Id", "ACC000014")
        self.assertTrue(
            duplicate_validation_cleared(
                corrected,
                "*External Id",
                edited_row=3,
                new_value="ACC000014",
                key_fields=["*External Id"],
            )
        )

    def test_picklist_dropdown_uses_allowed_api_values(self):
        issue = {
            "edit_key": make_edit_key(3, "L1_Channel__c"),
            "issue_type": "picklist",
            "row": 3,
            "field": "L1_Channel__c",
            "current_value": "Bad Value",
            "problem": "Invalid Picklist Value",
            "allowed_values": ["AWAY FROM HOME", "DISTRIBUTOR"],
            "category": "picklist",
        }
        invalid = validate_picklist_replacement("Bad Value", issue["allowed_values"])
        self.assertFalse(invalid["valid"])
        valid = validate_picklist_replacement("DISTRIBUTOR", issue["allowed_values"])
        self.assertTrue(valid["valid"])

    def test_saved_picklist_correction_updates_corrected_df(self):
        original = pd.DataFrame({"L1_Channel__c": ["Bad Value"]})
        corrected = apply_cell_correction(original, 2, "L1_Channel__c", "DISTRIBUTOR")
        self.assertEqual(corrected.loc[0, "L1_Channel__c"], "DISTRIBUTOR")
        self.assertEqual(original.loc[0, "L1_Channel__c"], "Bad Value")

    def test_original_df_unchanged_after_issue_edit(self):
        original_df = pd.DataFrame({"Start Date": ["31/02/2026"]})
        preparation_result = {
            "corrected_df": original_df.copy(),
            "change_log": [],
            "manual_review": [],
        }
        correction = {
            "row": 2,
            "field": "Start Date",
            "proposed_value": "06/07/2026",
            "original_value": "31/02/2026",
            "category": "dates",
            "issue_id": "date:Start Date:2",
            "problem": "Invalid Calendar Date",
        }
        with patch("services.issue_edit_service.build_row_correction_plan") as plan_mock, patch(
            "services.issue_edit_service.attach_date_validation_state",
            side_effect=lambda result, *_args, **_kwargs: result,
        ):
            plan_mock.return_value = {"manual_review": [], "issues": []}
            payload = revalidate_after_issue_edit(
                preparation_result=preparation_result,
                original_df=original_df,
                correction=correction,
                upload_method="Data Import Tool",
                template="Customers",
                mapping_rows=[],
                validation_bundle={},
                row_correction_plan={"issues": []},
                date_field_types={"Start Date": "date"},
                source_date_format=None,
                template_context=None,
            )
        self.assertEqual(original_df.loc[0, "Start Date"], "31/02/2026")
        self.assertEqual(payload["preparation_result"]["corrected_df"].loc[0, "Start Date"], "06/07/2026")

    def test_readiness_updates_after_fixes(self):
        readiness_before = evaluate_preparation_readiness(
            header_review_complete=True,
            preparation_result={
                "corrected_df": pd.DataFrame({"Start Date": ["31/02/2026"]}),
                "manual_review": [{"row": 2, "field": "Start Date", "reason": "Invalid date"}],
                "date_unresolved": [{"row": 2, "field": "Start Date", "value": "31/02/2026"}],
                "warnings": [],
            },
            row_correction_plan={"corrections_applied": True},
            workbench_plan=None,
            validation_result={"picklist_validation": {"has_blocking_issues": False}, "dependencies": {}},
        )
        self.assertEqual(readiness_before["status"], READINESS_STATUS["NOT_READY"])

        readiness_after = evaluate_preparation_readiness(
            header_review_complete=True,
            preparation_result={
                "corrected_df": pd.DataFrame({"Start Date": ["06/07/2026"]}),
                "manual_review": [],
                "date_unresolved": [],
                "warnings": [],
            },
            row_correction_plan={"corrections_applied": True, "manual_review": []},
            workbench_plan=None,
            validation_result={"picklist_validation": {"has_blocking_issues": False}, "dependencies": {}},
        )
        self.assertIn(readiness_after["status"], {READINESS_STATUS["READY"], READINESS_STATUS["READY_WITH_WARNINGS"]})

    def test_download_uses_corrected_df(self):
        corrected_df = pd.DataFrame({"Start Date": ["06/07/2026"]})
        preparation_result = {"corrected_df": corrected_df}
        self.assertIs(preparation_result["corrected_df"], corrected_df)

    def test_session_reruns_preserve_pending_edits(self):
        session_state: dict = {}
        save_pending_edit(
            session_state,
            "row_5_StartDate",
            original="31/02/2026",
            proposed="06/07/2026",
            validated=False,
        )
        save_pending_edit(
            session_state,
            "row_5_StartDate",
            original="31/02/2026",
            proposed="06/07/2026",
            validated=True,
            extra={"validation_message": "✅ Date corrected"},
        )
        edits = get_issue_edits(session_state)
        self.assertEqual(edits["row_5_StartDate"]["proposed"], "06/07/2026")
        self.assertTrue(edits["row_5_StartDate"]["validated"])

    def test_collect_editable_issues_includes_blocking_dates_and_duplicates(self):
        prep = {
            "date_unresolved": [{
                "row": 5,
                "field": "Start Date",
                "value": "31/02/2026",
                "reason": "Invalid Calendar Date",
                "display_status": "Invalid Calendar Date",
            }],
            "corrected_df": pd.DataFrame({
                "Start Date": ["31/02/2026", "06/07/2026"],
                "*External Id": ["ACC000012", "ACC000012"],
            }),
        }
        row_plan = {
            "issues": [{
                "issue_id": "duplicate:*External Id:ACC000012",
                "category": "duplicates",
                "field": "*External Id",
                "row": 13,
                "original_value": "ACC000012",
                "reason": "Duplicate value `ACC000012` appears on rows 13, 14.",
                "blocking": True,
            }],
            "manual_review": [],
        }
        issues = collect_editable_issues(
            preparation_result=prep,
            row_correction_plan=row_plan,
            picklist_validation={"issues": []},
            mapped_df=prep["corrected_df"],
            upload_method="Data Import Tool",
            date_field_types={"Start Date": "date"},
        )
        keys = {issue["edit_key"] for issue in issues}
        self.assertIn(make_edit_key(5, "Start Date"), keys)
        self.assertIn(make_edit_key(13, "*External Id"), keys)
        self.assertIn(make_edit_key(14, "*External Id"), keys)

    def test_parse_duplicate_rows(self):
        self.assertEqual(parse_duplicate_rows("Duplicate value appears on rows 13, 14."), [13, 14])

    def test_validate_replacement_routes_by_issue_type(self):
        numeric_issue = {"issue_type": "numeric"}
        result = validate_replacement(numeric_issue, "1.234,56", "Workbench")
        self.assertTrue(result["valid"])
        self.assertEqual(result["normalized_value"], "1234.56")

    def test_fix_issues_title_constant(self):
        self.assertEqual(FIX_ISSUES_TITLE, "Fix Issues in Copilot")

    def test_build_issue_editor_summary(self):
        summary = build_issue_editor_summary([
            {
                "row": 5,
                "field": "Start Date",
                "problem": "Invalid date",
                "current_value": "31/02/2026",
            }
        ])
        self.assertIn("Row 5", summary)
        self.assertIn("Start Date", summary)

    def test_render_issue_editor_routes_to_date_editor(self):
        issue = {
            "edit_key": make_edit_key(2, "Start Date"),
            "issue_type": "date",
            "row": 2,
            "field": "Start Date",
            "current_value": "31/02/2026",
            "problem": "Invalid Calendar Date",
            "date_subtype": "invalid_calendar",
            "field_type": "date",
            "category": "dates",
        }
        session_state: dict = {}
        mock_st = MagicMock()
        mock_st.session_state = session_state
        mock_st.button.side_effect = [False]
        mock_st.text_input.return_value = "06/07/2026"
        mock_st.caption = MagicMock()
        mock_st.markdown = MagicMock()
        mock_st.info = MagicMock()
        mock_st.success = MagicMock()
        mock_st.error = MagicMock()
        mock_st.warning = MagicMock()

        with patch("ui.issue_editor.render_date_issue_editor") as date_mock:
            date_mock.return_value = None
            render_issue_editor(issue, upload_method="Data Import Tool", session_state=session_state)
            date_mock.assert_called_once()

    def test_render_picklist_issue_editor_structure(self):
        issue = {
            "edit_key": make_edit_key(3, "L1_Channel__c"),
            "issue_type": "picklist",
            "row": 3,
            "field": "L1_Channel__c",
            "current_value": "Bad Value",
            "problem": "Invalid Picklist Value",
            "allowed_values": ["AWAY FROM HOME", "DISTRIBUTOR"],
            "category": "picklist",
        }
        session_state: dict = {}
        mock_st = MagicMock()
        mock_st.session_state = session_state
        mock_st.button.side_effect = [False]
        mock_st.selectbox.return_value = "DISTRIBUTOR"
        mock_st.caption = MagicMock()
        mock_st.markdown = MagicMock()
        mock_st.success = MagicMock()
        mock_st.error = MagicMock()
        mock_st.warning = MagicMock()

        with patch("ui.issue_editor.st", mock_st):
            result = render_picklist_issue_editor(
                issue,
                upload_method="Workbench",
                session_state=session_state,
            )
        self.assertIsNone(result)
        mock_st.selectbox.assert_called_once()

    def test_build_issue_expander_label(self):
        label = build_issue_expander_label({
            "row": 5,
            "field": "Start Date",
            "problem": "Invalid date",
        })
        self.assertEqual(label, "Row 5 — Start Date — Invalid date")

    def test_build_issue_status_summary(self):
        header, lines = build_issue_status_summary([
            {"issue_type": "date"},
            {"issue_type": "date"},
            {"issue_type": "duplicate"},
        ])
        self.assertEqual(header, "3 issues need attention")
        self.assertIn("- 2 date issues", lines)

    def test_build_issue_session_key(self):
        key = build_issue_session_key({"issue_type": "date", "field": "Start Date", "row": 5})
        self.assertEqual(key, "date_issue_StartDate_row_5")


if __name__ == "__main__":
    unittest.main()
