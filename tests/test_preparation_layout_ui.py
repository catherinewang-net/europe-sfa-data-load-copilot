"""Layout structure tests for Data Cleanup and Fix Issues workflow."""

from __future__ import annotations

import inspect
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from ui.components import render_preparation_results
from ui.data_preparation_issues import render_data_preparation_issues
from ui.data_preparation_warnings import render_data_preparation_warnings
from ui.issue_editor import (
    ALL_RESOLVED_MESSAGE,
    FIX_ISSUES_TITLE,
    build_issue_expander_label,
    build_issue_session_key,
    build_issue_status_summary,
    render_fix_issues_in_copilot,
)
from ui.picklist_validation import (
    PICKLIST_ALL_VALID_MESSAGE,
    _render_inline_picklist_editor,
    _render_picklist_field_card,
    render_picklist_validation,
)


def _app_source() -> str:
    with open("app.py", encoding="utf-8") as handle:
        return handle.read()


class SectionTitleTests(unittest.TestCase):
    def test_section_titles_have_no_numbers(self):
        sources = [
            inspect.getsource(render_data_preparation_issues),
            inspect.getsource(render_preparation_results),
            inspect.getsource(render_data_preparation_warnings),
            inspect.getsource(render_picklist_validation),
        ]
        for source in sources:
            self.assertNotRegex(source, r'subheader\("\d+\.')
            self.assertNotRegex(source, r"subheader\('\d+\.")

    def test_fix_issues_title_has_no_number(self):
        self.assertEqual(FIX_ISSUES_TITLE, "Fix Issues in Copilot")
        self.assertNotIn(".", FIX_ISSUES_TITLE.split()[0])


class AppLayoutOrderTests(unittest.TestCase):
    def test_fix_issues_appears_before_picklist_in_app(self):
        source = _app_source()
        dit_block = source.split('upload_method == "Data Import Tool"')[1].split('elif upload_method == "Workbench"')[0]
        fix_index = dit_block.index("render_fix_issues_in_copilot")
        picklist_index = dit_block.index("render_picklist_validation", fix_index)
        self.assertLess(fix_index, picklist_index)

    def test_corrected_preview_before_validation_results_in_app(self):
        source = _app_source()
        dit_block = source.split('upload_method == "Data Import Tool"')[1].split('elif upload_method == "Workbench"')[0]
        preview_index = dit_block.index("render_preparation_results")
        validation_index = dit_block.index("render_validation_results", preview_index)
        self.assertLess(preview_index, validation_index)

    def test_validation_results_does_not_interrupt_main_flow(self):
        source = inspect.getsource(render_preparation_results)
        self.assertIn("render_technical_details_expander", source)
        self.assertNotIn("render_validation_results", source)


class ExpandableIssueTests(unittest.TestCase):
    def test_issues_use_expander_labels(self):
        issue = {
            "row": 5,
            "field": "Start Date",
            "problem": "Invalid date",
            "issue_type": "date",
        }
        label = build_issue_expander_label(issue)
        self.assertEqual(label, "Row 5 — Start Date — Invalid date")

    def test_issue_status_summary_groups_by_type(self):
        issues = [
            {"issue_type": "date", "row": 5, "field": "Start Date"},
            {"issue_type": "date", "row": 6, "field": "Start Date"},
            {"issue_type": "duplicate", "row": 13, "field": "*External Id"},
        ]
        header, lines = build_issue_status_summary(issues)
        self.assertEqual(header, "3 issues need attention")
        self.assertIn("- 2 date issues", lines)
        self.assertIn("- 1 duplicate identifier issue", lines)

    def test_fix_issues_uses_expanders_collapsed_by_default(self):
        source = inspect.getsource(render_fix_issues_in_copilot)
        self.assertIn("st.expander", source)
        self.assertIn("expanded=expanded", source)

    def test_stable_session_keys(self):
        issue = {"issue_type": "date", "field": "Start Date", "row": 5}
        self.assertEqual(build_issue_session_key(issue), "date_issue_StartDate_row_5")

    def test_picklist_inline_editor_is_within_field_card(self):
        source = inspect.getsource(render_picklist_validation)
        self.assertIn("_render_picklist_field_card", source)
        self.assertNotIn("_render_picklist_expandable_rows", source)
        card_source = inspect.getsource(_render_picklist_field_card)
        self.assertIn("_render_inline_picklist_editor", card_source)
        self.assertIn("build_picklist_review_button_label", card_source)
        inline_source = inspect.getsource(_render_inline_picklist_editor)
        self.assertIn("render_picklist_issue_editor", inline_source)
        self.assertNotIn("Review Invalid Rows", source)


class FixIssuesBehaviorTests(unittest.TestCase):
    def test_all_resolved_message_when_no_issues(self):
        preparation_result = {
            "corrected_df": pd.DataFrame({"Start Date": ["06/07/2026"]}),
            "date_unresolved": [],
            "manual_review": [],
        }
        mock_st = MagicMock()
        mock_st.session_state = {}
        mock_st.subheader = MagicMock()
        mock_st.success = MagicMock()
        mock_st.markdown = MagicMock()

        with patch("ui.issue_editor.st", mock_st), patch(
            "ui.issue_editor.collect_editable_issues",
            return_value=[],
        ):
            result = render_fix_issues_in_copilot(
                preparation_result=preparation_result,
                original_df=preparation_result["corrected_df"],
                row_correction_plan={"issues": []},
                picklist_validation={"issues": []},
                mapped_df=preparation_result["corrected_df"],
                upload_method="Data Import Tool",
                template="Customers",
                mapping_rows=[],
                validation_bundle={},
                date_field_types={},
                source_date_format=None,
                template_context=None,
            )
        self.assertIsNone(result)
        mock_st.success.assert_called_once_with(ALL_RESOLVED_MESSAGE)

    def test_invalid_replacement_rejected_on_save(self):
        from services.issue_edit_service import validate_date_replacement

        result = validate_date_replacement("31/02/2026", "Data Import Tool")
        self.assertFalse(result["valid"])

    def test_valid_correction_updates_corrected_df(self):
        from services.issue_edit_service import apply_cell_correction

        df = pd.DataFrame({"Start Date": ["31/02/2026"]})
        corrected = apply_cell_correction(df, 2, "Start Date", "06/07/2026")
        self.assertEqual(corrected.loc[0, "Start Date"], "06/07/2026")


if __name__ == "__main__":
    unittest.main()
