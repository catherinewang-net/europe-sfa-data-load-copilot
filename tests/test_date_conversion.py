"""Comprehensive tests for strict date detection and conversion."""

from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd

from services.date_conversion_service import (
    SOURCE_FORMAT_DIT,
    SOURCE_FORMAT_US,
    SOURCE_FORMAT_WORKBENCH,
    STATUS_VALID,
    TARGET_TOOL_DIT,
    TARGET_TOOL_WORKBENCH,
    analyze_cell,
    apply_date_conversions,
    attach_date_validation_state,
    build_date_conversion_plan,
    build_date_status_preview,
    collect_unresolved_date_rows,
    convert_date_column,
    default_source_format,
    display_status,
    revalidate_dataframe_dates,
    resolve_date_field_columns,
)
from services.preparation_flow_service import evaluate_preparation_readiness
from validators.date_validator import analyze_date_value, validate_dates
from validators.workbench_readiness_validator import evaluate_workbench_readiness
from core.config import READINESS_STATUS


class DateConversionServiceTests(unittest.TestCase):
    def test_default_source_format_dit(self):
        self.assertEqual(default_source_format("Data Import Tool"), SOURCE_FORMAT_DIT)

    def test_default_source_format_workbench(self):
        self.assertEqual(default_source_format("Workbench"), SOURCE_FORMAT_WORKBENCH)

    def test_workbench_target_iso_unchanged(self):
        analysis = analyze_cell("2026-07-20", SOURCE_FORMAT_WORKBENCH, TARGET_TOOL_WORKBENCH)
        self.assertEqual(analysis["status"], "already_correct")

    def test_dit_target_slash_unchanged(self):
        analysis = analyze_cell("20/07/2026", SOURCE_FORMAT_DIT, TARGET_TOOL_DIT)
        self.assertEqual(analysis["status"], "already_correct")

    def test_convert_dmy_to_workbench(self):
        analysis = analyze_cell("6/7/2026", SOURCE_FORMAT_DIT, TARGET_TOOL_WORKBENCH)
        self.assertEqual(analysis["status"], "convertible")
        self.assertEqual(analysis["converted"], "2026-07-06")

    def test_convert_dmy_second_example(self):
        analysis = analyze_cell("9/8/2026", SOURCE_FORMAT_DIT, TARGET_TOOL_WORKBENCH)
        self.assertEqual(analysis["status"], "convertible")
        self.assertEqual(analysis["converted"], "2026-08-09")

    def test_iso_to_workbench_unchanged(self):
        analysis = analyze_cell("2026-07-20", SOURCE_FORMAT_DIT, TARGET_TOOL_WORKBENCH)
        self.assertEqual(analysis["status"], "already_correct")

    def test_ambiguous_without_source_format_defaults_day_first(self):
        analysis = analyze_cell("01/02/2026", None, TARGET_TOOL_WORKBENCH)
        self.assertEqual(analysis["status"], "convertible")
        self.assertEqual(analysis["converted"], "2026-02-01")

    def test_workbench_default_source_converts_single_digit_slash(self):
        analysis = analyze_cell("6/7/2026", SOURCE_FORMAT_WORKBENCH, TARGET_TOOL_WORKBENCH)
        self.assertEqual(analysis["status"], "convertible")
        self.assertEqual(analysis["converted"], "2026-07-06")

    def test_convert_dmy_to_dit_zero_padded(self):
        analysis = analyze_cell("6/7/2026", SOURCE_FORMAT_DIT, TARGET_TOOL_DIT)
        self.assertEqual(analysis["status"], "convertible")
        self.assertEqual(analysis["converted"], "06/07/2026")

    def test_single_digit_day_accepted(self):
        analysis = analyze_cell("6/07/2026", SOURCE_FORMAT_DIT, TARGET_TOOL_WORKBENCH)
        self.assertEqual(analysis["status"], "convertible")
        self.assertEqual(analysis["converted"], "2026-07-06")

    def test_single_digit_month_accepted(self):
        analysis = analyze_cell("06/7/2026", SOURCE_FORMAT_DIT, TARGET_TOOL_WORKBENCH)
        self.assertEqual(analysis["status"], "convertible")
        self.assertEqual(analysis["converted"], "2026-07-06")

    def test_both_single_digit_accepted(self):
        analysis = analyze_cell("6/7/2026", SOURCE_FORMAT_DIT, TARGET_TOOL_WORKBENCH)
        self.assertEqual(analysis["status"], "convertible")
        self.assertEqual(analysis["converted"], "2026-07-06")

    def test_dd_mm_yyyy_still_works(self):
        analysis = analyze_cell("20/07/2026", SOURCE_FORMAT_DIT, TARGET_TOOL_WORKBENCH)
        self.assertEqual(analysis["status"], "convertible")
        self.assertEqual(analysis["converted"], "2026-07-20")

    def test_corrected_preview_uses_corrected_df(self):
        df = pd.DataFrame({"StartDate": ["6/7/2026", "2026-07-20"]})
        field_types = {"StartDate": "date"}
        plan = build_date_conversion_plan(df, field_types, TARGET_TOOL_WORKBENCH, SOURCE_FORMAT_DIT)
        corrected, _ = apply_date_conversions(df, plan)
        self.assertEqual(corrected.loc[0, "StartDate"], "2026-07-06")
        self.assertEqual(corrected.loc[1, "StartDate"], "2026-07-20")
        self.assertNotEqual(corrected.loc[0, "StartDate"], df.loc[0, "StartDate"])

    def test_download_uses_corrected_df(self):
        df = pd.DataFrame({"StartDate": ["9/8/2026"]})
        field_types = {"StartDate": "date"}
        plan = build_date_conversion_plan(df, field_types, TARGET_TOOL_WORKBENCH, SOURCE_FORMAT_DIT)
        corrected, log = apply_date_conversions(df, plan)
        preparation_result = {"corrected_df": corrected, "change_log": log}
        buffer = corrected.to_csv(index=False)
        self.assertIn("2026-08-09", buffer)
        self.assertNotIn("9/8/2026", buffer)
        self.assertEqual(preparation_result["corrected_df"].iloc[0]["StartDate"], "2026-08-09")

    def test_ambiguous_resolved_with_dit_source(self):
        analysis = analyze_cell("01/02/2026", SOURCE_FORMAT_DIT, TARGET_TOOL_WORKBENCH)
        self.assertEqual(analysis["status"], "convertible")
        self.assertEqual(analysis["converted"], "2026-02-01")

    def test_ambiguous_resolved_with_us_source(self):
        analysis = analyze_cell("01/02/2026", SOURCE_FORMAT_US, TARGET_TOOL_WORKBENCH)
        self.assertEqual(analysis["status"], "convertible")
        self.assertEqual(analysis["converted"], "2026-01-02")

    def test_unambiguous_dmy_day_gt_12(self):
        analysis = analyze_cell("13/01/2026", None, TARGET_TOOL_WORKBENCH)
        self.assertEqual(analysis["status"], "convertible")
        self.assertEqual(analysis["converted"], "2026-01-13")

    def test_invalid_date_feb_31(self):
        analysis = analyze_cell("31/02/2026", SOURCE_FORMAT_DIT, TARGET_TOOL_DIT)
        self.assertEqual(analysis["status"], "invalid_calendar")
        self.assertEqual(display_status(analysis["status"]), "Invalid Calendar Date")

    def test_invalid_month_13(self):
        analysis = analyze_cell("2026-13-01", SOURCE_FORMAT_WORKBENCH, TARGET_TOOL_WORKBENCH)
        self.assertEqual(analysis["status"], "invalid_calendar")

    def test_invalid_text_date(self):
        analysis = analyze_cell("Jan 5 2026", SOURCE_FORMAT_DIT, TARGET_TOOL_WORKBENCH)
        self.assertEqual(analysis["status"], "unsupported_text")
        self.assertEqual(analysis["converted"], "2026-01-05")

    def test_excel_serial_detection(self):
        analysis = analyze_cell("45658", SOURCE_FORMAT_DIT, TARGET_TOOL_WORKBENCH)
        self.assertEqual(analysis["status"], "excel_serial")

    def test_iso_datetime_conversion(self):
        analysis = analyze_cell(
            "2026-07-20T00:00:00",
            SOURCE_FORMAT_WORKBENCH,
            TARGET_TOOL_WORKBENCH,
            field_type="datetime",
        )
        self.assertEqual(analysis["status"], "already_correct")
        self.assertEqual(analysis["converted"], "2026-07-20T00:00:00")

    def test_iso_datetime_to_dit(self):
        analysis = analyze_cell(
            "2026-07-20T00:00:00",
            SOURCE_FORMAT_WORKBENCH,
            TARGET_TOOL_DIT,
            field_type="datetime",
        )
        self.assertEqual(analysis["status"], "convertible")
        self.assertEqual(analysis["converted"], "20/07/2026 00:00:00")

    def test_iso_datetime_space_separator(self):
        analysis = analyze_cell("2026-07-20 00:00:00", SOURCE_FORMAT_WORKBENCH, TARGET_TOOL_WORKBENCH)
        self.assertEqual(analysis["status"], "convertible")

    def test_yyyy_slash_mm_dd(self):
        analysis = analyze_cell("2026/07/20", SOURCE_FORMAT_WORKBENCH, TARGET_TOOL_WORKBENCH)
        self.assertEqual(analysis["status"], "convertible")
        self.assertEqual(analysis["converted"], "2026-07-20")

    def test_dash_dmy_format(self):
        analysis = analyze_cell("06-07-2026", SOURCE_FORMAT_DIT, TARGET_TOOL_WORKBENCH)
        self.assertEqual(analysis["status"], "convertible")
        self.assertEqual(analysis["converted"], "2026-07-06")

    def test_pandas_timestamp_conversion(self):
        ts = pd.Timestamp("2026-07-06")
        analysis = analyze_cell(ts, SOURCE_FORMAT_DIT, TARGET_TOOL_WORKBENCH)
        self.assertEqual(analysis["status"], "convertible")
        self.assertEqual(analysis["converted"], "2026-07-06")

    def test_convert_column_mixed_formats(self):
        series = pd.Series(["6/7/2026", "9/8/2026", "2026-07-20", ""])
        result = convert_date_column(series, SOURCE_FORMAT_DIT, TARGET_TOOL_WORKBENCH)
        corrected = result["corrected_series"]
        self.assertEqual(corrected.iloc[0], "2026-07-06")
        self.assertEqual(corrected.iloc[1], "2026-08-09")
        self.assertEqual(corrected.iloc[2], "2026-07-20")
        self.assertEqual(result["summary"]["can_convert"], 2)
        self.assertEqual(result["summary"]["already_correct"], 1)

    def test_apply_conversions_updates_dataframe(self):
        df = pd.DataFrame({
            "StartDate": ["6/7/2026", "2026-07-20"],
            "EndDate": ["9/8/2026", "15/01/2026"],
        })
        field_types = {"StartDate": "date", "EndDate": "date"}
        plan = build_date_conversion_plan(df, field_types, TARGET_TOOL_WORKBENCH, SOURCE_FORMAT_DIT)
        corrected, log = apply_date_conversions(df, plan)
        self.assertEqual(corrected.loc[0, "StartDate"], "2026-07-06")
        self.assertEqual(corrected.loc[0, "EndDate"], "2026-08-09")
        self.assertEqual(corrected.loc[1, "StartDate"], "2026-07-20")
        self.assertEqual(corrected.loc[1, "EndDate"], "2026-01-15")
        self.assertEqual(len(log), 3)

    def test_post_conversion_validation_workbench(self):
        df = pd.DataFrame({"StartDate": ["2026-07-06", "6/7/2026"]})
        issues = validate_dates(
            df,
            {"StartDate": "date"},
            TARGET_TOOL_WORKBENCH,
            post_conversion=True,
        )
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["original_value"], "6/7/2026")

    def test_post_conversion_validation_dit(self):
        df = pd.DataFrame({"Date Field": ["20/07/2026", "2026-07-20"]})
        issues = validate_dates(
            df,
            {"Date Field": "date"},
            TARGET_TOOL_DIT,
            post_conversion=True,
        )
        self.assertEqual(len(issues), 1)

    def test_dit_to_workbench_via_validator(self):
        analysis = analyze_date_value("13/01/2026", TARGET_TOOL_WORKBENCH, SOURCE_FORMAT_DIT)
        self.assertEqual(analysis["status"], "convertible")
        self.assertEqual(analysis["converted"], "2026-01-13")

    def test_convert_to_dit_format(self):
        analysis = analyze_cell("2026-01-13", SOURCE_FORMAT_WORKBENCH, TARGET_TOOL_DIT)
        self.assertEqual(analysis["status"], "convertible")
        self.assertEqual(analysis["converted"], "13/01/2026")


class DateFieldResolutionTests(unittest.TestCase):
    def test_metadata_date_fields_without_date_in_name(self):
        metadata = MagicMock()
        metadata.field_type = "date"
        object_fields = {"StartDate": metadata, "Name": MagicMock(field_type="string")}

        context = MagicMock()
        context.fallback_config = {"date_fields": []}
        context.template_definition = None

        result = resolve_date_field_columns(
            ["StartDate", "EndDate", "Name"],
            {"StartDate": "StartDate", "EndDate": "EndDate", "Name": "Name"},
            context,
            object_fields,
        )
        self.assertEqual(result["StartDate"], "date")
        self.assertNotIn("Name", result)

    def test_template_date_fields_from_fallback_config(self):
        context = MagicMock()
        context.fallback_config = {
            "date_fields": ["Customer Valid from Date(dd/mm/yyyy)"],
        }
        context.template_definition = None

        result = resolve_date_field_columns(
            ["Customer Valid from Date(dd/mm/yyyy)", "Name"],
            {},
            context,
            {},
        )
        self.assertIn("Customer Valid from Date(dd/mm/yyyy)", result)

    def test_datetime_field_type_preserved(self):
        metadata = MagicMock()
        metadata.field_type = "datetime"
        object_fields = {"CreatedDate": metadata}

        context = MagicMock()
        context.fallback_config = None
        context.template_definition = None

        result = resolve_date_field_columns(["CreatedDate"], {}, context, object_fields)
        self.assertEqual(result["CreatedDate"], "datetime")


class DateConversionPlanTests(unittest.TestCase):
    def test_plan_all_date_columns(self):
        df = pd.DataFrame({
            "StartDate": ["6/7/2026"],
            "EndDate": ["9/8/2026"],
            "Influence_Date__c": ["2026-07-20"],
        })
        field_types = {
            "StartDate": "date",
            "EndDate": "date",
            "Influence_Date__c": "date",
        }
        plan = build_date_conversion_plan(df, field_types, TARGET_TOOL_WORKBENCH, SOURCE_FORMAT_DIT)
        self.assertEqual(set(plan["columns"].keys()), set(field_types.keys()))


class RequiredDateValidationTests(unittest.TestCase):
    """Ten required date-validation workflow tests."""

    MIXED_DF = pd.DataFrame({
        "StartDate": ["2026-07-06", "31/02/2026", "July 6, 2026", "46209"],
        "EndDate": ["2026-08-09", "2026-06-22", "", "2026-07-06"],
    })
    FIELD_TYPES = {"StartDate": "date", "EndDate": "date"}

    def test_1_valid_iso_passes(self):
        analysis = analyze_cell("2026-07-06", SOURCE_FORMAT_WORKBENCH, TARGET_TOOL_WORKBENCH)
        self.assertEqual(analysis["status"], "already_correct")
        self.assertEqual(display_status(analysis["status"]), "Valid")

    def test_2_invalid_calendar_fails(self):
        analysis = analyze_cell("31/02/2026", SOURCE_FORMAT_DIT, TARGET_TOOL_WORKBENCH)
        self.assertEqual(analysis["status"], "invalid_calendar")

    def test_3_text_date_classified_correctly(self):
        analysis = analyze_cell("July 6, 2026", SOURCE_FORMAT_DIT, TARGET_TOOL_WORKBENCH)
        self.assertEqual(analysis["status"], "unsupported_text")
        self.assertEqual(analysis["converted"], "2026-07-06")

    def test_4_excel_serial_detected(self):
        analysis = analyze_cell("46209", SOURCE_FORMAT_DIT, TARGET_TOOL_WORKBENCH)
        self.assertEqual(analysis["status"], "excel_serial")
        self.assertEqual(analysis["converted"], "2026-07-06")

    def test_5_regex_valid_impossible_date_fails(self):
        issues = validate_dates(
            pd.DataFrame({"StartDate": ["2026-02-31"]}),
            {"StartDate": "date"},
            TARGET_TOOL_WORKBENCH,
            post_conversion=True,
        )
        self.assertEqual(len(issues), 1)
        self.assertIn("Invalid Calendar Date", issues[0]["reason"])

    def test_6_corrected_preview_distinguishes_valid_unresolved(self):
        preview = build_date_status_preview(
            self.MIXED_DF,
            self.FIELD_TYPES,
            TARGET_TOOL_WORKBENCH,
            SOURCE_FORMAT_DIT,
        )
        self.assertEqual(preview.loc[0, "StartDate Status"], "Valid")
        self.assertEqual(preview.loc[1, "StartDate Status"], "Invalid Calendar Date")
        self.assertEqual(preview.loc[2, "StartDate Status"], "Unsupported Text Date")
        self.assertEqual(preview.loc[3, "StartDate Status"], "Possible Excel Serial Date")

    def test_7_ready_blocked_by_unresolved_required_dates(self):
        prep = attach_date_validation_state(
            {"corrected_df": self.MIXED_DF.copy(), "manual_review": [], "warnings": []},
            self.FIELD_TYPES,
            TARGET_TOOL_WORKBENCH,
            SOURCE_FORMAT_DIT,
        )
        readiness = evaluate_preparation_readiness(
            header_review_complete=True,
            preparation_result=prep,
            row_correction_plan={"corrections_applied": True},
            workbench_plan={"corrections_applied": True},
            validation_result={"picklist_validation": {"has_blocking_issues": False}},
            upload_method="Workbench",
        )
        self.assertEqual(readiness["status"], READINESS_STATUS["NOT_READY"])

    def test_8_download_blocked_by_invalid_dates(self):
        prep = attach_date_validation_state(
            {"corrected_df": self.MIXED_DF.copy(), "manual_review": [], "warnings": []},
            self.FIELD_TYPES,
            TARGET_TOOL_WORKBENCH,
            SOURCE_FORMAT_DIT,
        )
        template_context = MagicMock()
        template_context.metadata_available = True
        template_context.fallback_config = {}
        template_context.salesforce_object = "Account"
        template_context.is_account_template = False
        template_context.account_type_valid = True
        allowed, message, details = evaluate_workbench_readiness(
            template_context,
            [],
            True,
            "Insert",
            {"has_blocking_issues": False},
            {"issues": []},
            prep,
            row_correction_plan={"has_blocking_manual_review": False},
        )
        self.assertFalse(allowed)
        self.assertTrue(
            "unresolved date" in message.lower()
            or any("unresolved date" in reason.lower() for reason in details.get("reasons", []))
        )

    def test_9_revalidation_after_date_approvals(self):
        df = pd.DataFrame({"StartDate": ["6/7/2026", "July 6, 2026"]})
        plan = build_date_conversion_plan(df, {"StartDate": "date"}, TARGET_TOOL_WORKBENCH, SOURCE_FORMAT_DIT)
        corrected, _ = apply_date_conversions(df, plan)
        corrected.at[1, "StartDate"] = "2026-07-06"
        unresolved = revalidate_dataframe_dates(
            corrected,
            {"StartDate": "date"},
            TARGET_TOOL_WORKBENCH,
            SOURCE_FORMAT_DIT,
        )
        self.assertEqual(unresolved, [])

    def test_10_all_date_columns_checked(self):
        unresolved = collect_unresolved_date_rows(
            self.MIXED_DF,
            self.FIELD_TYPES,
            TARGET_TOOL_WORKBENCH,
            SOURCE_FORMAT_DIT,
        )
        fields = {item["field"] for item in unresolved}
        self.assertIn("StartDate", fields)
        self.assertEqual(len(fields), 1)

        for column in self.FIELD_TYPES:
            issues = validate_dates(
                self.MIXED_DF,
                self.FIELD_TYPES,
                TARGET_TOOL_WORKBENCH,
                SOURCE_FORMAT_DIT,
            )
            column_issues = [issue for issue in issues if issue["field"] == column]
            if column == "StartDate":
                self.assertGreaterEqual(len(column_issues), 3)
            else:
                self.assertEqual(len(column_issues), 0)


if __name__ == "__main__":
    unittest.main()
