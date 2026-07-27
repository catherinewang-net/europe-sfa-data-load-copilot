"""Tests for unified preparation features: whitespace, blank rows, numeric, download."""

from __future__ import annotations

import io
import unittest
from unittest.mock import patch

import pandas as pd

from services.row_correction_plan_service import apply_row_corrections, build_row_correction_plan
from validators.blank_row_validator import validate_blank_rows
from validators.numeric_validator import validate_numeric_fields
from validators.whitespace_validator import validate_whitespace


class PreparationFeatureTests(unittest.TestCase):
    def test_whitespace_trim(self):
        df = pd.DataFrame({"Name": [" Tesco "]})
        issues = validate_whitespace(df, ["Name"])
        self.assertTrue(any(issue["proposed_value"] == "Tesco" for issue in issues))

    def test_whitespace_repeated_spaces(self):
        df = pd.DataFrame({"City": ["London     Store"]})
        issues = validate_whitespace(df, ["City"])
        self.assertTrue(any(issue["proposed_value"] == "London Store" for issue in issues))

    def test_whitespace_tabs_and_nbsp(self):
        df = pd.DataFrame({"Name": ["AWAY\u00a0FROM\tHOME "]})
        issues = validate_whitespace(df, ["Name"])
        self.assertTrue(any(issue["proposed_value"] == "AWAY FROM HOME" for issue in issues))

    def test_whitespace_line_breaks(self):
        df = pd.DataFrame({"Contact": ["John\nSmith"]})
        issues = validate_whitespace(df, ["Contact"])
        self.assertTrue(any(issue["proposed_value"] == "John Smith" for issue in issues))

    def test_blank_rows_detected(self):
        df = pd.DataFrame({
            "Name": ["Acme", "", "   "],
            "City": ["London", None, "\t"],
        })
        issues = validate_blank_rows(df)
        self.assertEqual(len(issues), 2)

    def test_blank_rows_removed_from_corrected_df(self):
        df = pd.DataFrame({
            "Name": ["Acme", "", "Beta"],
            "City": ["London", "   ", "Paris"],
        })
        issues = validate_blank_rows(df)
        plan = {"issues": issues}
        corrected, log = apply_row_corrections(df, plan, {issue["issue_id"] for issue in issues})
        self.assertEqual(len(corrected), 2)
        self.assertEqual(list(corrected["Name"]), ["Acme", "Beta"])
        self.assertTrue(any(entry["category"] == "blank_rows" for entry in log))

    def test_numeric_comma_decimal_conversion(self):
        df = pd.DataFrame({"Amount__c": ["12,5"]})
        issues = validate_numeric_fields(df, ["Amount__c"])
        self.assertTrue(any(issue["proposed_value"] == "12.5" for issue in issues))
        self.assertTrue(all(issue.get("requires_confirmation") for issue in issues if issue.get("proposed_value") == "12.5"))
        self.assertFalse(any(issue.get("safe") for issue in issues if issue.get("proposed_value") == "12.5"))

    def test_numeric_thousands_conversion(self):
        df = pd.DataFrame({"Amount__c": ["1,000.50"]})
        issues = validate_numeric_fields(df, ["Amount__c"])
        self.assertTrue(any(issue["proposed_value"] == "1000.50" for issue in issues))

    def test_numeric_skips_external_id_column(self):
        df = pd.DataFrame({"External Id": ["1,000.50"]})
        fields = __import__(
            "validators.numeric_validator",
            fromlist=["resolve_numeric_fields"],
        ).resolve_numeric_fields(["External Id"], {})
        self.assertEqual(fields, [])

    def test_apply_whitespace_updates_corrected_df(self):
        original = pd.DataFrame({"Name": [" Tesco ", "London     Store"]})
        issues = validate_whitespace(original, ["Name"])
        plan = {"issues": issues}
        corrected, _log = apply_row_corrections(original, plan, {issue["issue_id"] for issue in issues})
        self.assertEqual(corrected.loc[0, "Name"], "Tesco")
        self.assertEqual(corrected.loc[1, "Name"], "London Store")
        self.assertEqual(original.loc[0, "Name"], " Tesco ")

    def test_download_output_has_no_blank_rows(self):
        df = pd.DataFrame({
            "Name": ["Acme", "", "Beta"],
            "City": ["London", "   ", "Paris"],
        })
        issues = validate_blank_rows(df)
        plan = {"issues": issues}
        corrected, _log = apply_row_corrections(df, plan, {issue["issue_id"] for issue in issues})
        csv_buffer = io.StringIO()
        corrected.to_csv(csv_buffer, index=False)
        output = csv_buffer.getvalue()
        self.assertIn("Acme", output)
        self.assertIn("Beta", output)
        self.assertEqual(len(corrected), 2)

    def test_row_plan_summary_includes_blank_rows(self):
        df = pd.DataFrame({"Name": ["Acme", ""], "City": ["London", ""]})
        with patch("services.row_correction_plan_service.get_metadata_adapter") as adapter_mock:
            adapter_mock.return_value.get_object_fields.return_value = {}
            plan = build_row_correction_plan(df, "Data Import Tool", "Customers")
        self.assertGreaterEqual(plan["summary"]["blank_rows"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
