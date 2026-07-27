"""Tests for row-level validation and correction."""

from __future__ import annotations

import csv
import io
import unittest

import pandas as pd

from services.row_correction_plan_service import apply_row_corrections, build_row_correction_plan
from validators.address_validator import validate_addresses
from validators.boolean_validator import validate_boolean_fields
from validators.csv_structure_validator import validate_csv_structure
from validators.date_validator import analyze_date_value, format_date, validate_dates
from validators.duplicate_key_validator import validate_duplicate_keys
from validators.identifier_validator import validate_identifiers
from validators.phone_validator import validate_phones


class RowValidationTests(unittest.TestCase):
    def test_dit_valid_date(self):
        analysis = analyze_date_value("13/01/2026", "Data Import Tool")
        self.assertEqual(analysis["status"], "valid_target")

    def test_workbench_valid_date(self):
        analysis = analyze_date_value("2026-01-13", "Workbench")
        self.assertEqual(analysis["status"], "valid_target")

    def test_convert_iso_to_dit(self):
        analysis = analyze_date_value("2026-01-13", "Data Import Tool")
        self.assertEqual(analysis["status"], "convertible")
        self.assertEqual(analysis["converted"], "13/01/2026")

    def test_convert_dit_to_workbench(self):
        analysis = analyze_date_value("13/01/2026", "Workbench")
        self.assertEqual(analysis["status"], "convertible")
        self.assertEqual(analysis["converted"], "2026-01-13")

    def test_reject_invalid_month_day(self):
        analysis = analyze_date_value("31/02/2026", "Data Import Tool")
        self.assertEqual(analysis["status"], "invalid")

    def test_flag_ambiguous_dates(self):
        from validators.date_validator import SOURCE_FORMAT_DIT, SOURCE_FORMAT_US

        dit_analysis = analyze_date_value("01/02/2026", "Workbench", source_format=SOURCE_FORMAT_DIT)
        self.assertEqual(dit_analysis["status"], "convertible")
        self.assertEqual(dit_analysis["converted"], "2026-02-01")

        us_analysis = analyze_date_value("01/02/2026", "Workbench", source_format=SOURCE_FORMAT_US)
        self.assertEqual(us_analysis["status"], "convertible")
        self.assertEqual(us_analysis["converted"], "2026-01-02")

    def test_detect_excel_serial_dates(self):
        analysis = analyze_date_value("45658", "Workbench")
        self.assertEqual(analysis["status"], "excel_serial")

    def test_postal_code_is_not_padded_by_identifier_validator(self):
        df = pd.DataFrame({"Postal Code": ["7120", "02108", "0"]})
        issues = validate_identifiers(df, ["Postal Code"])
        self.assertFalse(issues)

    def test_billing_postal_code_is_not_resolved_as_identifier(self):
        from validators.identifier_validator import resolve_identifier_fields

        columns = ["BillingPostalCode", "Postal Code", "CUST_ID__c"]
        resolved = resolve_identifier_fields(columns, {"BillingPostalCode": "BillingPostalCode"})
        self.assertNotIn("BillingPostalCode", resolved)
        self.assertNotIn("Postal Code", resolved)
        self.assertIn("CUST_ID__c", resolved)

    def test_detect_scientific_notation_in_identifiers(self):
        df = pd.DataFrame({"CUST_ID__c": ["1.0010E+12"]})
        issues = validate_identifiers(df, ["CUST_ID__c"])
        self.assertTrue(any("scientific notation" in issue["reason"].lower() for issue in issues))

    def test_phone_values_do_not_use_numeric_decimal_rules(self):
        df = pd.DataFrame({"Phone": ["+44 0123 456789"]})
        issues = validate_phones(df, ["Phone"])
        self.assertFalse(any("numeric field" in issue["reason"].lower() for issue in issues))

    def test_detect_malformed_address_row_with_extra_comma(self):
        content = "Name,Street\nAcme,\"123 Main Street, Building A\",Extra\n"
        issues = validate_csv_structure(content, 2)
        self.assertTrue(any(issue["category"] == "csv_structure" for issue in issues))

    def test_parse_quoted_address_with_comma(self):
        content = "Name,Street\nAcme,\"123 Main Street, Building A\"\n"
        reader = csv.reader(io.StringIO(content))
        headers = next(reader)
        row = next(reader)
        self.assertEqual(len(headers), len(row))
        self.assertEqual(row[1], "123 Main Street, Building A")

    def test_preserve_postal_codes_as_text(self):
        df = pd.DataFrame({"Postal Code": ["00123.0"]})
        issues = validate_addresses(df, ["Postal Code"])
        self.assertTrue(any(issue["proposed_value"] == "00123" for issue in issues))

    def test_trim_phone_and_address_whitespace(self):
        df = pd.DataFrame({"Phone": ["  12345  "], "Street": ["  Main St  "]})
        phone_issues = validate_phones(df, ["Phone"])
        address_issues = validate_addresses(df, ["Street"])
        self.assertTrue(any(issue["proposed_value"] == "12345" for issue in phone_issues))
        self.assertTrue(any(issue["proposed_value"] == "Main St" for issue in address_issues))

    def test_convert_yes_no_to_true_false_after_approval(self):
        df = pd.DataFrame({"Active__c": ["Yes", "No"]})
        issues = validate_boolean_fields(df, ["Active__c"])
        self.assertTrue(all(issue["requires_confirmation"] for issue in issues))
        plan = {"issues": issues}
        corrected, log = apply_row_corrections(df, plan, {issue["issue_id"] for issue in issues})
        self.assertEqual(corrected.loc[0, "Active__c"], "TRUE")
        self.assertEqual(corrected.loc[1, "Active__c"], "FALSE")
        self.assertEqual(len(log), 2)

    def test_detect_duplicate_external_ids(self):
        df = pd.DataFrame({"*External Id": ["1001", "1001", "1002"]})
        issues = validate_duplicate_keys(df, ["*External Id"])
        self.assertTrue(any("Duplicate value `1001`" in issue["reason"] for issue in issues))

    def test_revalidate_corrected_df_after_approval(self):
        original = pd.DataFrame({"Date Field": ["2026-01-13"]})
        plan = {
            "issues": [{
                "issue_id": "date:Date Field:2",
                "category": "dates",
                "field": "Date Field",
                "row": 2,
                "original_value": "2026-01-13",
                "proposed_value": "13/01/2026",
                "reason": "Convert date",
                "safe": True,
                "blocking": False,
            }]
        }
        corrected, _log = apply_row_corrections(original, plan, {"date:Date Field:2"})
        self.assertEqual(corrected.loc[0, "Date Field"], "13/01/2026")
        self.assertEqual(original.loc[0, "Date Field"], "2026-01-13")

    def test_original_dataframe_remains_unchanged(self):
        original = pd.DataFrame({"Phone": [" 123 "]})
        plan = {
            "issues": [{
                "issue_id": "phone:trim:Phone:2",
                "category": "phones",
                "field": "Phone",
                "row": 2,
                "original_value": " 123 ",
                "proposed_value": "123",
                "reason": "Trim whitespace",
                "safe": True,
                "blocking": False,
            }]
        }
        apply_row_corrections(original, plan, {"phone:trim:Phone:2"})
        self.assertEqual(original.loc[0, "Phone"], " 123 ")


if __name__ == "__main__":
    unittest.main()
