"""Structure tests for corrected-preview dual download behavior."""

from __future__ import annotations

import ast
import inspect
import unittest

import pandas as pd

from services.export_service import (
    ISSUE_DETAIL_COLUMN,
    ISSUE_STATUS_COLUMN,
    build_review_dataframe,
    build_review_filename,
    build_review_issue_examples,
    build_tool_ready_filename,
)
from ui.components import render_preparation_results
from ui.preparation_action_cards import TECHNICAL_DETAILS_TITLE, render_technical_details_expander


def _function_source() -> str:
    return inspect.getsource(render_preparation_results)


def _main_view_source() -> str:
    return _function_source().split("def _render_technical_preparation_details")[0]


def _technical_details_source() -> str:
    return _function_source().split("def _render_technical_preparation_details", 1)[1]


def _expander_source() -> str:
    return inspect.getsource(render_technical_details_expander)


class ExportServiceTests(unittest.TestCase):
    def test_tool_ready_filename_uses_tool_ready_suffix(self) -> None:
        filename = build_tool_ready_filename("Retail_Promotion", "Data Import Tool")
        self.assertEqual(filename, "Retail_Promotion_tool_ready.csv")
        self.assertNotIn("_review", filename)
        self.assertNotIn("REVIEW_NOT_READY", filename)

    def test_review_filename_uses_review_suffix(self) -> None:
        filename = build_review_filename("Retail_Promotion")
        self.assertEqual(filename, "Retail_Promotion_review.csv")
        self.assertNotIn("REVIEW_NOT_READY", filename)

    def test_review_dataframe_uses_corrected_df_without_issue_notes(self) -> None:
        corrected = pd.DataFrame({"Name": ["A"], "Status": ["Open"]})
        review = build_review_dataframe(corrected)
        self.assertEqual(list(review.columns), ["Name", "Status"])
        pd.testing.assert_frame_equal(review, corrected)

    def test_review_dataframe_reflects_approved_corrections(self) -> None:
        corrected = pd.DataFrame({"Start Date": ["06/07/2026"], "Status": ["Active"]})
        review = build_review_dataframe(corrected)
        pd.testing.assert_frame_equal(review, corrected)
        self.assertEqual(review.iloc[0]["Start Date"], "06/07/2026")

    def test_review_dataframe_adds_issue_columns_when_requested(self) -> None:
        corrected = pd.DataFrame({"Name": ["A", "B"]})
        review = build_review_dataframe(
            corrected,
            include_issue_notes=True,
            preparation_result={
                "date_unresolved": [{"row": 2, "field": "StartDate"}],
            },
        )
        self.assertIn(ISSUE_STATUS_COLUMN, review.columns)
        self.assertIn(ISSUE_DETAIL_COLUMN, review.columns)
        self.assertEqual(review.iloc[0][ISSUE_STATUS_COLUMN], "Issue")
        self.assertEqual(review.iloc[1][ISSUE_STATUS_COLUMN], "")

    def test_build_review_issue_examples(self) -> None:
        examples = build_review_issue_examples(
            {"date_unresolved": [{}, {}], "manual_review": []},
            {
                "picklist_validation": {
                    "issues": [
                        {"status": "Invalid Picklist Value"},
                        {"status": "Blank Required Value"},
                    ],
                },
            },
        )
        self.assertIn("- 2 unresolved date values", examples)
        self.assertIn("- 1 invalid picklist value", examples)
        self.assertIn("- 1 required field missing", examples)


class PreparationResultsUiStructureTests(unittest.TestCase):
    def test_tool_ready_download_outside_technical_details_expander(self) -> None:
        source = _main_view_source()
        self.assertIn("Download Tool-Ready CSV", source)
        self.assertIn('key="download_tool_ready_csv"', source)

    def test_review_download_outside_technical_details_expander(self) -> None:
        source = _main_view_source()
        self.assertIn("Download Review CSV", source)
        self.assertIn('key="download_review_csv"', source)

    def test_corrected_preview_remains_visible(self) -> None:
        source = _main_view_source()
        self.assertIn("Corrected Preview", source)
        self.assertIn("st.dataframe(preview_df.head(10)", source)

    def test_technical_details_collapsed_by_default(self) -> None:
        source = _expander_source()
        self.assertIn("expanded: bool = False", source)

    def test_review_download_uses_corrected_df(self) -> None:
        source = _main_view_source()
        corrected_index = source.index('corrected_df = result.get("corrected_df")')
        review_index = source.index("build_review_dataframe(")
        self.assertLess(corrected_index, review_index)
        self.assertIn("build_review_dataframe(\n        corrected_df", source)

    def test_tool_ready_download_blocked_when_not_ready(self) -> None:
        source = _main_view_source()
        self.assertIn("if can_download:", source)
        self.assertIn('key="download_tool_ready_csv"', source)
        not_ready_block = source.split("if can_download:", 1)[0]
        self.assertNotIn('key="download_tool_ready_csv"', not_ready_block)

    def test_review_download_available_when_not_ready(self) -> None:
        source = _main_view_source()
        can_download_index = source.index("if can_download:")
        review_index = source.index('key="download_review_csv"')
        self.assertLess(review_index, can_download_index)
        ready_block = source.split("if can_download:", 1)[1]
        self.assertNotIn('key="download_review_csv"', ready_block)

    def test_review_download_not_gated_by_acknowledgement(self) -> None:
        source = _main_view_source()
        self.assertNotIn("review_download_ack", source)
        self.assertNotIn("disabled=not review_ack", source)

    def test_review_download_available_with_unresolved_picklist(self) -> None:
        source = _main_view_source()
        self.assertIn("build_review_issue_examples", source)
        review_index = source.index('key="download_review_csv"')
        picklist_index = source.index("build_review_issue_examples")
        self.assertGreater(review_index, picklist_index)

    def test_review_download_available_with_unresolved_dates(self) -> None:
        source = _main_view_source()
        self.assertIn("date_unresolved", source)
        self.assertIn('key="download_review_csv"', source)

    def test_review_still_available_when_ready(self) -> None:
        source = _main_view_source()
        ready_block = source.split("if can_download:", 1)[1]
        self.assertIn('key="download_review_csv"', _main_view_source())
        self.assertIn('key="download_tool_ready_csv"', ready_block)

    def test_both_downloads_when_ready(self) -> None:
        source = _main_view_source()
        ready_block = source.split("if can_download:", 1)[1]
        self.assertIn('key="download_tool_ready_csv"', ready_block)
        self.assertIn('key="download_review_csv"', source)

    def test_review_filename_uses_review_suffix(self) -> None:
        source = _main_view_source()
        self.assertIn("build_review_filename(base_name)", source)
        self.assertEqual(build_review_filename("Sample"), "Sample_review.csv")

    def test_tool_ready_filename_uses_tool_ready_suffix(self) -> None:
        source = _main_view_source()
        self.assertIn("build_tool_ready_filename(base_name, upload_method)", source)
        self.assertEqual(
            build_tool_ready_filename("Sample", "Workbench"),
            "Sample_tool_ready.csv",
        )

    def test_no_duplicate_download_buttons(self) -> None:
        technical_source = _technical_details_source()
        for label in ("Download Tool-Ready CSV", "Download Review CSV"):
            self.assertNotIn(label, technical_source)
        self.assertEqual(_function_source().count('key="download_tool_ready_csv"'), 1)
        self.assertEqual(_function_source().count('key="download_review_csv"'), 1)

    def test_primary_download_not_gated_by_expander(self) -> None:
        tree = ast.parse(_function_source())
        function_def = next(
            node for node in tree.body if isinstance(node, ast.FunctionDef)
        )
        nested_def = next(
            node
            for node in function_def.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_render_technical_preparation_details"
        )
        nested_names = {
            node.id
            for node in ast.walk(nested_def)
            if isinstance(node, ast.Name)
        }
        self.assertNotIn("can_download", nested_names)

    def test_expander_renders_after_main_download_section(self) -> None:
        source = _function_source()
        download_index = source.index('key="download_review_csv"')
        expander_index = source.index(
            "render_technical_details_expander(render_fn=_render_technical_preparation_details)"
        )
        self.assertLess(download_index, expander_index)

    def test_technical_details_title_constant(self) -> None:
        self.assertEqual(TECHNICAL_DETAILS_TITLE, "View Technical Details")

    def test_not_ready_shows_readiness_in_main_view(self) -> None:
        source = _main_view_source()
        not_ready_block = source.split("if can_download:", 1)[0]
        self.assertIn("render_readiness(readiness)", not_ready_block)

    def test_review_section_displays_required_caption(self) -> None:
        source = _main_view_source()
        self.assertIn("This file includes your approved changes", source)
        self.assertIn("unresolved issues may still", source)

    def test_tool_ready_section_displays_required_caption(self) -> None:
        source = _main_view_source()
        self.assertIn("All blocking issues have been resolved.", source)


if __name__ == "__main__":
    unittest.main()
