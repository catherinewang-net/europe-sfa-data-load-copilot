"""Tests for DIT-aligned validation rules (CSV, punctuation, EAN, Federation ID, address)."""

from __future__ import annotations

import csv
import io
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from services.constants import RECORD_CHECK_UNAVAILABLE
from services.row_correction_plan_service import build_row_correction_plan
from validators.address_validator import validate_addresses
from validators.common import NBSP, export_csv_with_quoting
from validators.csv_structure_validator import validate_csv_structure
from validators.ean_validator import run_ean_live_lookup, validate_eans
from validators.federation_id_validator import validate_federation_ids
from validators.text_sanitization_validator import validate_text_sanitization


class DitValidationRuleTests(unittest.TestCase):
    def test_01_quoted_comma_in_street_remains_one_field(self):
        raw_csv = 'Street,City\n"123 Main Street, Building A",Chicago\n'
        issues = validate_csv_structure(raw_csv, header_count=2)
        self.assertFalse(issues)

    def test_02_unquoted_comma_causes_column_shift_warning(self):
        raw_csv = "Street,City\n123 Main Street, Building A,Chicago\n"
        issues = validate_csv_structure(raw_csv, header_count=2)
        self.assertTrue(issues)
        self.assertIn("too many fields", issues[0]["reason"].lower())

    def test_03_unclosed_quote_is_detected(self):
        raw_csv = 'Street,City\n"123 Main Street,Chicago\n'
        issues = validate_csv_structure(raw_csv, header_count=2)
        self.assertTrue(any("unclosed" in issue["reason"].lower() for issue in issues))

    def test_04_non_breaking_spaces_are_detected(self):
        df = pd.DataFrame({"Store Name": [f"Store{NBSP}Name"]})
        issues = validate_text_sanitization(df, ["Store Name"])
        self.assertTrue(issues)
        self.assertEqual(issues[0]["category"], "punctuation")

    def test_05_smart_punctuation_is_identified(self):
        df = pd.DataFrame({"Store Name": ["\u201cStore Name\u201d"]})
        issues = validate_text_sanitization(df, ["Store Name"])
        self.assertTrue(issues)
        self.assertIn("smart quote", issues[0]["reason"].lower())

    def test_06_ean_remains_text(self):
        df = pd.DataFrame({"EAN Code": ["5449000000996"]})
        issues = validate_eans(df, ["EAN Code"])
        blocking = [issue for issue in issues if issue.get("blocking")]
        self.assertFalse(blocking)

    def test_07_ean_scientific_notation_is_flagged(self):
        df = pd.DataFrame({"EAN Code": ["1.23E+12"]})
        issues = validate_eans(df, ["EAN Code"])
        self.assertTrue(any("scientific notation" in issue["reason"].lower() for issue in issues))

    def test_08_duplicate_ean_is_flagged(self):
        df = pd.DataFrame({"EAN Code": ["5449000000996", "5449000000996"]})
        issues = validate_eans(df, ["EAN Code"])
        self.assertTrue(any("duplicate ean" in issue["reason"].lower() for issue in issues))

    def test_09_ean_existence_check_is_batched(self):
        df = pd.DataFrame({"EAN Code": ["5449000000996", "5449000000997"]})
        mock_client = MagicMock()
        mock_client.is_configured.return_value = True

        with patch("clients.salesforce_client.get_salesforce_client", return_value=mock_client):
            with patch("services.salesforce_record_lookup_service.lookup_records_by_field") as lookup_mock:
                lookup_mock.return_value = {
                    "matches_by_value": {"5449000000996": [{"Id": "001", "EAN__c": "5449000000996"}]},
                    "query_errors": [],
                }
                result = run_ean_live_lookup(df, ["EAN Code"], {"EAN Code": "EAN__c"})
                self.assertTrue(result["available"])
                lookup_mock.assert_called_once()
                call_values = lookup_mock.call_args[0][3]
                self.assertEqual(len(call_values), 2)

    def test_10_salesforce_connection_failure_produces_check_unavailable(self):
        df = pd.DataFrame({"EAN Code": ["5449000000996"]})
        live_lookup = {
            "available": False,
            "status_by_field": {},
            "query_errors": ["connection failed"],
            "message": RECORD_CHECK_UNAVAILABLE,
            "attempted": True,
        }
        issues = validate_eans(df, ["EAN Code"], live_lookup_result=live_lookup)
        self.assertTrue(any(
            "existence in salesforce was not verified" in issue["reason"].lower()
            for issue in issues
        ))

    def test_11_federation_id_beginning_with_9_and_too_short_is_flagged(self):
        df = pd.DataFrame({"Federation ID": ["91234567"]})
        issues = validate_federation_ids(df, ["Federation ID"])
        self.assertTrue(any("leading zero" in issue["reason"].lower() for issue in issues))

    def test_12_federation_id_is_not_automatically_padded(self):
        df = pd.DataFrame({"Federation ID": ["91234567"]})
        issues = validate_federation_ids(df, ["Federation ID"])
        leading_zero_issues = [
            issue for issue in issues
            if issue.get("issue_id", "").startswith("federation_id:leading-zero")
        ]
        self.assertEqual(len(leading_zero_issues), 1)
        issue = leading_zero_issues[0]
        self.assertFalse(issue.get("safe"))
        self.assertTrue(issue.get("requires_confirmation"))
        self.assertEqual(issue["proposed_value"], "091234567")
        self.assertEqual(issue["original_value"], "91234567")

    def test_13_street_containing_city_state_postal_code_is_flagged(self):
        df = pd.DataFrame({
            "Street": ["123 Main Street, Chicago, IL 60601"],
            "City": [""],
            "State": [""],
            "Postal Code": [""],
        })
        issues = validate_addresses(df, ["Street", "City", "State", "Postal Code"])
        self.assertTrue(any(
            "street appears to contain city" in issue["reason"].lower()
            for issue in issues
        ))

    def test_14_postal_code_leading_zero_is_preserved(self):
        df = pd.DataFrame({"Postal Code": ["02108"]})
        issues = validate_addresses(df, ["Postal Code"])
        safe_fixes = [issue for issue in issues if issue.get("safe")]
        self.assertFalse(any(issue.get("proposed_value") != "02108" for issue in safe_fixes))

    def test_15_valid_structured_address_passes(self):
        df = pd.DataFrame({
            "Street": ["123 Main Street, Building A"],
            "City": ["Chicago"],
            "State": ["IL"],
            "Postal Code": ["60601"],
            "Country": ["United States"],
        })
        issues = validate_addresses(df, list(df.columns))
        blocking = [issue for issue in issues if issue.get("blocking")]
        self.assertFalse(blocking)

    def test_16_corrected_csv_quotes_address_commas_properly(self):
        df = pd.DataFrame({
            "Street": ["123 Main Street, Building A"],
            "City": ["Chicago"],
            "State": ["IL"],
            "Postal Code": ["60601"],
            "Country": ["United States"],
        })
        csv_text = export_csv_with_quoting(df)
        reader = csv.reader(io.StringIO(csv_text))
        headers = next(reader)
        row = next(reader)
        self.assertEqual(len(headers), len(row))
        self.assertEqual(row[0], "123 Main Street, Building A")
        self.assertIn('"123 Main Street, Building A"', csv_text)

    def test_row_plan_integrates_chicago_address_example(self):
        raw_csv = (
            "Street,City,State,Postal Code,Country\n"
            '"123 Main Street, Building A",Chicago,IL,60601,United States\n'
            "123 Main Street, Chicago, IL 60601,,,\n"
        )
        df = pd.DataFrame({
            "Street": ["123 Main Street, Building A", "123 Main Street, Chicago, IL 60601"],
            "City": ["Chicago", ""],
            "State": ["IL", ""],
            "Postal Code": ["60601", ""],
            "Country": ["United States", ""],
        })
        plan = build_row_correction_plan(
            df,
            "Data Import Tool",
            "Prospects",
            raw_csv_content=raw_csv,
        )
        categories = {issue["category"] for issue in plan["issues"]}
        self.assertIn("addresses", categories)


if __name__ == "__main__":
    unittest.main()
