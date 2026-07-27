"""Tests for leading-zero correction rules (EAN, Federation ID, Postal Code)."""

from __future__ import annotations

import csv
import io
import unittest
from unittest.mock import patch

import pandas as pd

from services.row_correction_plan_service import apply_row_corrections, build_row_correction_plan
from validators.common import export_csv_with_quoting
from validators.ean_validator import validate_eans
from validators.federation_id_validator import validate_federation_ids
from validators.identifier_validator import resolve_identifier_fields, validate_identifiers


class LeadingZeroRuleTests(unittest.TestCase):
    def test_postal_code_7120_remains_7120(self):
        df = pd.DataFrame({"Postal Code": ["7120"]})
        issues = validate_identifiers(df, ["Postal Code"])
        self.assertFalse(issues)

    def test_postal_code_02108_remains_02108(self):
        df = pd.DataFrame({"Postal Code": ["02108"]})
        issues = validate_identifiers(df, ["Postal Code"])
        self.assertFalse(any(issue.get("proposed_value") != "02108" for issue in issues))

    def test_postal_code_zero_is_not_padded(self):
        df = pd.DataFrame({"Postal Code": ["0"]})
        issues = validate_identifiers(df, ["Postal Code"])
        self.assertFalse(any(issue.get("proposed_value") == "00000" for issue in issues))

    def test_billing_postal_code_is_never_auto_padded(self):
        df = pd.DataFrame({"BillingPostalCode": ["6210"]})
        resolved = resolve_identifier_fields(
            ["BillingPostalCode"],
            {"BillingPostalCode": "BillingPostalCode"},
        )
        self.assertNotIn("BillingPostalCode", resolved)
        issues = validate_identifiers(df, ["BillingPostalCode"])
        self.assertFalse(any(issue.get("proposed_value") == "06210" for issue in issues))

    def test_ean_padded_only_when_expected_length_configured(self):
        df = pd.DataFrame({"EAN Code": ["123456789012"]})
        issues = validate_eans(df, ["EAN Code"])
        leading_zero = [
            issue for issue in issues
            if issue.get("issue_id", "").startswith("eans:leading-zero")
        ]
        self.assertEqual(len(leading_zero), 1)
        self.assertEqual(leading_zero[0]["proposed_value"], "0123456789012")

    def test_ean_not_padded_without_matching_configured_length(self):
        df = pd.DataFrame({"EAN Code": ["7120"]})
        issues = validate_eans(df, ["EAN Code"])
        self.assertFalse(any(
            issue.get("issue_id", "").startswith("eans:leading-zero")
            for issue in issues
        ))

    def test_federation_id_starting_with_9_suggested_only_when_configured(self):
        df = pd.DataFrame({"Federation ID": ["91234567"]})
        issues = validate_federation_ids(df, ["Federation ID"])
        leading_zero = [
            issue for issue in issues
            if issue.get("issue_id", "").startswith("federation_id:leading-zero")
        ]
        self.assertEqual(len(leading_zero), 1)
        self.assertEqual(leading_zero[0]["proposed_value"], "091234567")
        self.assertTrue(leading_zero[0].get("requires_confirmation"))

    def test_other_ids_not_padded(self):
        df = pd.DataFrame({"CUST_ID__c": ["1234", "91234567"]})
        issues = validate_identifiers(df, ["CUST_ID__c"])
        self.assertFalse(any(
            issue.get("proposed_value") in {"01234", "091234567", "00001234"}
            for issue in issues
        ))

    def test_postal_code_padding_proposals_cleared_after_revalidation(self):
        original = pd.DataFrame({"Postal Code": ["7120"], "EAN Code": ["5449000000996"]})
        with patch("services.row_correction_plan_service.resolve_template") as template_mock:
            template_mock.return_value = None
            with patch("validators.ean_validator.run_ean_live_lookup") as lookup_mock:
                lookup_mock.return_value = {"available": False, "status_by_field": {}, "attempted": False}
                plan = build_row_correction_plan(
                    original,
                    upload_method="Data Import Tool",
                    template="",
                    mapping_rows=[{"source_column": column, "status": "Mapped"} for column in original.columns],
                )
        postal_padding = [
            issue for issue in plan["issues"]
            if issue.get("field") == "Postal Code"
            and issue.get("proposed_value") in {"07120", "00000", "06210"}
        ]
        self.assertFalse(postal_padding)

    def test_corrected_df_preserves_postal_codes(self):
        original = pd.DataFrame({"Postal Code": ["7120", "02108", "0"]})
        plan = {"issues": []}
        corrected, _log = apply_row_corrections(original, plan, set())
        self.assertEqual(corrected.loc[0, "Postal Code"], "7120")
        self.assertEqual(corrected.loc[1, "Postal Code"], "02108")
        self.assertEqual(corrected.loc[2, "Postal Code"], "0")

    def test_final_csv_preserves_postal_codes_exactly(self):
        df = pd.DataFrame({"Postal Code": ["7120", "02108", "0"]})
        csv_text = export_csv_with_quoting(df)
        reader = csv.reader(io.StringIO(csv_text))
        rows = list(reader)
        self.assertEqual(rows[1][0], "7120")
        self.assertEqual(rows[2][0], "02108")
        self.assertEqual(rows[3][0], "0")


if __name__ == "__main__":
    unittest.main()
