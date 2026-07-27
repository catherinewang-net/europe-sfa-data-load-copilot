"""Unit tests for preparation action card helpers."""

from __future__ import annotations

import unittest

from services.correction_plan_service import get_reorder_change_ids
from ui.preparation_action_cards import (
    TECHNICAL_DETAILS_TITLE,
    build_action_card_body,
    build_cleanup_action_buttons,
    build_cleanup_category_summaries,
    build_data_cleanup_description,
    count_fixable_issues,
    format_cleanup_summary_intro,
    format_header_order_details,
    format_issue_details,
    format_structure_change_details,
    get_issue_ids_for_categories,
    render_technical_details_expander,
)


class PreparationActionCardTests(unittest.TestCase):
    def test_technical_details_title_constant(self):
        self.assertEqual(TECHNICAL_DETAILS_TITLE, "View Technical Details")

    def test_render_technical_details_expander_skips_empty_content(self):
        self.assertIsNone(render_technical_details_expander(None))
        self.assertIsNone(render_technical_details_expander(render_fn=None))

    def test_build_action_card_body_shows_success_when_applied(self):
        body = build_action_card_body(
            applied=True,
            description="Fix something.",
            success_message="✅ Done.",
        )
        self.assertEqual(body, "✅ Done.")

    def test_build_action_card_body_shows_description_when_not_applied(self):
        body = build_action_card_body(
            applied=False,
            description="Fix something.",
            success_message="✅ Done.",
        )
        self.assertEqual(body, "Fix something.")

    def test_format_header_order_details(self):
        details = format_header_order_details([
            {"header": "Name", "expected_position": 2, "actual_position": 11},
        ])
        self.assertIn("Name", details)
        self.assertIn("expected position 2", details)
        self.assertIn("found 11", details)

    def test_format_structure_change_details(self):
        details = format_structure_change_details(["Rename headers: **2**"])
        self.assertIn("Rename headers", details)

    def test_format_issue_details_truncates(self):
        issues = [
            {
                "row": index,
                "field": "Field",
                "reason": "Issue",
                "original_value": "a",
                "proposed_value": "b",
            }
            for index in range(1, 30)
        ]
        details = format_issue_details(issues, limit=5)
        self.assertIn("Row 1", details)
        self.assertIn("more issue(s) not shown", details)

    def test_get_issue_ids_for_categories(self):
        plan = {
            "issues": [
                {"issue_id": "ws:1", "category": "whitespace", "safe": True},
                {"issue_id": "id:1", "category": "identifiers", "safe": True},
                {"issue_id": "br:1", "category": "blank_rows", "requires_confirmation": True},
            ],
        }
        cleanup_ids = get_issue_ids_for_categories(plan, ("whitespace", "blank_rows"))
        self.assertEqual(cleanup_ids, {"ws:1", "br:1"})

        safe_only = get_issue_ids_for_categories(plan, ("blank_rows",), safe_only=True)
        self.assertEqual(safe_only, set())

    def test_count_fixable_issues(self):
        plan = {
            "issues": [
                {"issue_id": "ws:1", "category": "whitespace", "safe": True, "row": 2},
                {"issue_id": "ws:2", "category": "whitespace", "safe": True, "row": 3},
                {"issue_id": "id:1", "category": "identifiers", "safe": False},
            ],
        }
        count, rows = count_fixable_issues(plan, ("whitespace",))
        self.assertEqual(count, 2)
        self.assertEqual(rows, 2)

    def test_format_cleanup_summary_intro(self):
        self.assertEqual(format_cleanup_summary_intro(1), "1 cleanup item found.")
        self.assertEqual(format_cleanup_summary_intro(18), "18 cleanup items found.")

    def test_build_cleanup_category_summaries(self):
        plan = {
            "issues": [
                {"issue_id": "ws:1", "category": "whitespace", "safe": True, "row": 2},
                {"issue_id": "ws:2", "category": "whitespace", "safe": True, "row": 3},
                {"issue_id": "dt:1", "category": "dates", "safe": True, "row": 4},
                {"issue_id": "id:1", "category": "identifiers", "requires_confirmation": True, "row": 5},
                {"issue_id": "ph:1", "category": "phones", "safe": True, "row": 6},
                {"issue_id": "ad:1", "category": "addresses", "safe": True, "row": 7},
                {"issue_id": "ad:2", "category": "addresses", "safe": True, "row": 8},
                {"issue_id": "ad:3", "category": "addresses", "safe": True, "row": 9},
            ],
            "summary": {},
        }
        summaries = build_cleanup_category_summaries(plan)
        lines = [item["line"] for item in summaries]
        self.assertIn("Whitespace — ✓ 2 values will be trimmed", lines)
        self.assertIn("Dates — ✓ 1 date will be converted", lines)
        self.assertIn("Identifier Format — ⚠ 1 identifier value need review", lines)
        self.assertIn("Phone Formatting — ✓ 1 value can be corrected", lines)
        self.assertIn("Address Formatting — ✓ 3 values need cleanup", lines)

    def test_build_data_cleanup_description_whitespace_only(self):
        description = build_data_cleanup_description(
            trim_count=8,
            blank_count=0,
            other_count=0,
            cleanup_rows=8,
            cleanup_count=8,
        )
        self.assertEqual(description, "8 whitespace issues were found across 8 rows.")

    def test_build_data_cleanup_description_mixed(self):
        description = build_data_cleanup_description(
            trim_count=2,
            blank_count=1,
            other_count=0,
            cleanup_rows=3,
            cleanup_count=3,
        )
        self.assertIn("3 cleanup items across 3 rows", description)
        self.assertIn("2 whitespace issue(s)", description)
        self.assertIn("1 blank row(s)", description)

    def test_build_cleanup_action_buttons(self):
        buttons = build_cleanup_action_buttons(3, 1, 2, categories=("whitespace", "blank_rows", "punctuation"))
        labels = [label for label, _key, _cats in buttons]
        self.assertEqual(labels, ["Apply Whitespace Cleanup", "Remove Blank Rows", "Apply Other Cleanup"])

    def test_get_reorder_change_ids(self):
        plan = {
            "changes": [
                {"change_id": "reorder:columns", "category": "reorder_columns"},
                {"change_id": "rename:a", "category": "rename"},
            ],
        }
        self.assertEqual(get_reorder_change_ids(plan), {"reorder:columns"})


if __name__ == "__main__":
    unittest.main()
