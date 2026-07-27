"""Tests for Workbench mapping flow, mapped dataframe, and session behavior."""

from __future__ import annotations

import io
import unittest
from unittest.mock import patch

import pandas as pd

from adapters.sfdx_metadata.models import FieldDefinition
from core.csv_loader import filter_blank_header_columns, load_uploaded_csv
from services.constants import (
    MAPPING_ACTION_MAP,
    MAPPING_STATUS_CONFIRMED,
    MAPPING_STATUS_EXACT_API,
    MAPPING_STATUS_EXCLUDED,
)
from services.row_correction_plan_service import _active_columns
from services.template_service import TemplateContext
from services.workbench_mapped_dataframe import build_mapped_df
from services.workbench_mapping_service import (
    apply_mapping_action,
    apply_session_to_rows,
    build_workbench_mapping_rows,
    exclude_mapping,
    filter_valid_mapping_rows,
    get_excluded_columns,
    get_mapping_summary,
    is_valid_mapping_row,
    keep_existing_header,
    mappings_ready_for_preparation,
    rows_to_session,
)


def _template_context() -> TemplateContext:
    return TemplateContext(
        template_name="Customers",
        metadata_available=True,
        template_definition=None,
        salesforce_object="Account",
        fallback_config=None,
        metadata_message=None,
        record_type_name="Customer",
        required_type_value="Customer",
        account_type_valid=True,
        account_type_error=None,
        is_account_template=True,
    )


def _object_fields() -> dict[str, FieldDefinition]:
    return {
        "Name": FieldDefinition("Name", "Account Name", "string", True),
        "BillingCity": FieldDefinition("BillingCity", "Billing City", "string", False),
        "Phone": FieldDefinition("Phone", "Phone", "phone", False),
        "Notes__c": FieldDefinition("Notes__c", "Notes", "textarea", False),
    }


class WorkbenchMappingFlowTests(unittest.TestCase):
    @patch("services.workbench_mapping_service.get_workbench_field_catalog")
    @patch("services.workbench_mapping_service.resolve_template")
    def test_blank_csv_headers_are_not_rendered(self, resolve_mock, catalog_mock):
        resolve_mock.return_value = _template_context()
        catalog_mock.return_value = ([], _object_fields(), "Account")
        rows, _ = build_workbench_mapping_rows(["", "Name", "   "], "Customers", "Insert")
        self.assertEqual([row["uploaded_column"] for row in rows], ["Name"])

    @patch("services.workbench_mapping_service.get_workbench_field_catalog")
    @patch("services.workbench_mapping_service.resolve_template")
    def test_unnamed_pandas_columns_are_ignored(self, resolve_mock, catalog_mock):
        resolve_mock.return_value = _template_context()
        catalog_mock.return_value = ([], _object_fields(), "Account")
        rows, _ = build_workbench_mapping_rows(["Unnamed: 0", "Name"], "Customers", "Insert")
        self.assertEqual([row["uploaded_column"] for row in rows], ["Name"])

    @patch("services.workbench_mapping_service.get_workbench_field_catalog")
    @patch("services.workbench_mapping_service.resolve_template")
    def test_real_headers_each_create_exactly_one_mapping_row(self, resolve_mock, catalog_mock):
        resolve_mock.return_value = _template_context()
        catalog_mock.return_value = ([], _object_fields(), "Account")
        headers = ["Name", "Billing City", "Notes"]
        rows, _ = build_workbench_mapping_rows(headers, "Customers", "Insert")
        self.assertEqual(len(rows), 3)
        self.assertEqual(len({row["uploaded_column"] for row in rows}), 3)

    @patch("services.workbench_mapping_service.get_adapter")
    @patch("services.workbench_mapping_service.get_workbench_field_catalog")
    @patch("services.workbench_mapping_service.resolve_template")
    def test_excluded_columns_do_not_require_api_mappings(self, resolve_mock, catalog_mock, adapter_mock):
        resolve_mock.return_value = _template_context()
        catalog_mock.return_value = ([], _object_fields(), "Account")
        adapter_mock.return_value.get_object_fields.return_value = _object_fields()
        rows, _ = build_workbench_mapping_rows(["Name", "Notes"], "Customers", "Insert")
        keep_existing_header(rows, "Name")
        exclude_mapping(rows, "Notes")
        ready, message = mappings_ready_for_preparation(rows, True, True, _template_context())
        self.assertTrue(ready, message)

    @patch("services.workbench_mapping_service.get_adapter")
    @patch("services.workbench_mapping_service.get_workbench_field_catalog")
    @patch("services.workbench_mapping_service.resolve_template")
    def test_user_can_continue_when_all_columns_resolved(self, resolve_mock, catalog_mock, adapter_mock):
        resolve_mock.return_value = _template_context()
        catalog_mock.return_value = ([], _object_fields(), "Account")
        adapter_mock.return_value.get_object_fields.return_value = _object_fields()
        rows, _ = build_workbench_mapping_rows(["Name", "Billing City", "Notes"], "Customers", "Insert")
        keep_existing_header(rows, "Name")
        apply_mapping_action(rows, "Billing City", MAPPING_ACTION_MAP, "BillingCity")
        exclude_mapping(rows, "Notes")
        ready, message = mappings_ready_for_preparation(rows, True, True, _template_context())
        self.assertTrue(ready, message)

    @patch("services.workbench_mapping_service.get_adapter")
    @patch("services.workbench_mapping_service.get_workbench_field_catalog")
    @patch("services.workbench_mapping_service.resolve_template")
    def test_user_cannot_continue_with_unresolved_columns(self, resolve_mock, catalog_mock, adapter_mock):
        resolve_mock.return_value = _template_context()
        catalog_mock.return_value = ([], _object_fields(), "Account")
        adapter_mock.return_value.get_object_fields.return_value = _object_fields()
        rows, _ = build_workbench_mapping_rows(["Name", "Billing City"], "Customers", "Insert")
        ready, _ = mappings_ready_for_preparation(rows, True, True, _template_context())
        self.assertFalse(ready)

    @patch("services.workbench_mapping_service.get_adapter")
    @patch("services.workbench_mapping_service.get_workbench_field_catalog")
    @patch("services.workbench_mapping_service.resolve_template")
    def test_mapped_df_excludes_do_not_include_columns(self, resolve_mock, catalog_mock, adapter_mock):
        resolve_mock.return_value = _template_context()
        catalog_mock.return_value = ([], _object_fields(), "Account")
        adapter_mock.return_value.get_object_fields.return_value = _object_fields()
        original = pd.DataFrame({"Name": ["Acme"], "Notes": ["x"]})
        rows, _ = build_workbench_mapping_rows(["Name", "Notes"], "Customers", "Insert")
        keep_existing_header(rows, "Name")
        exclude_mapping(rows, "Notes")
        mapped = build_mapped_df(original, rows)
        self.assertEqual(list(mapped.columns), ["Name"])
        self.assertNotIn("Notes", mapped.columns)

    @patch("services.workbench_mapping_service.get_adapter")
    @patch("services.workbench_mapping_service.get_workbench_field_catalog")
    @patch("services.workbench_mapping_service.resolve_template")
    def test_mapped_df_renames_confirmed_mappings(self, resolve_mock, catalog_mock, adapter_mock):
        resolve_mock.return_value = _template_context()
        catalog_mock.return_value = ([], _object_fields(), "Account")
        adapter_mock.return_value.get_object_fields.return_value = _object_fields()
        original = pd.DataFrame({"Billing City": ["Paris"]})
        rows, _ = build_workbench_mapping_rows(["Billing City"], "Customers", "Insert")
        apply_mapping_action(rows, "Billing City", MAPPING_ACTION_MAP, "BillingCity")
        mapped = build_mapped_df(original, rows)
        self.assertEqual(list(mapped.columns), ["BillingCity"])

    @patch("services.workbench_mapping_service.get_adapter")
    @patch("services.workbench_mapping_service.get_workbench_field_catalog")
    @patch("services.workbench_mapping_service.resolve_template")
    def test_exact_api_headers_are_preserved(self, resolve_mock, catalog_mock, adapter_mock):
        resolve_mock.return_value = _template_context()
        catalog_mock.return_value = ([], _object_fields(), "Account")
        adapter_mock.return_value.get_object_fields.return_value = _object_fields()
        original = pd.DataFrame({"Name": ["Acme"]})
        rows, _ = build_workbench_mapping_rows(["Name"], "Customers", "Insert")
        keep_existing_header(rows, "Name")
        mapped = build_mapped_df(original, rows)
        self.assertEqual(list(mapped.columns), ["Name"])

    @patch("services.workbench_mapping_service.get_adapter")
    @patch("services.workbench_mapping_service.get_workbench_field_catalog")
    @patch("services.workbench_mapping_service.resolve_template")
    def test_duplicate_target_mappings_are_blocked(self, resolve_mock, catalog_mock, adapter_mock):
        resolve_mock.return_value = _template_context()
        catalog_mock.return_value = ([], _object_fields(), "Account")
        adapter_mock.return_value.get_object_fields.return_value = _object_fields()
        original = pd.DataFrame({"Billing City": ["Paris"], "City": ["Lyon"]})
        rows, _ = build_workbench_mapping_rows(["Billing City", "City"], "Customers", "Insert")
        apply_mapping_action(rows, "Billing City", MAPPING_ACTION_MAP, "BillingCity")
        apply_mapping_action(rows, "City", MAPPING_ACTION_MAP, "BillingCity")
        with self.assertRaises(ValueError):
            build_mapped_df(original, rows)

    @patch("services.workbench_mapping_service.get_adapter")
    @patch("services.workbench_mapping_service.get_workbench_field_catalog")
    @patch("services.workbench_mapping_service.resolve_template")
    def test_original_df_remains_unchanged(self, resolve_mock, catalog_mock, adapter_mock):
        resolve_mock.return_value = _template_context()
        catalog_mock.return_value = ([], _object_fields(), "Account")
        adapter_mock.return_value.get_object_fields.return_value = _object_fields()
        original = pd.DataFrame({"Billing City": ["Paris"], "Notes": ["x"]})
        snapshot = original.copy()
        rows, _ = build_workbench_mapping_rows(["Billing City", "Notes"], "Customers", "Insert")
        apply_mapping_action(rows, "Billing City", MAPPING_ACTION_MAP, "BillingCity")
        exclude_mapping(rows, "Notes")
        build_mapped_df(original, rows)
        pd.testing.assert_frame_equal(original, snapshot)

    @patch("services.workbench_mapping_service.get_adapter")
    @patch("services.workbench_mapping_service.get_workbench_field_catalog")
    @patch("services.workbench_mapping_service.resolve_template")
    def test_excluded_columns_are_not_row_validated(self, resolve_mock, catalog_mock, adapter_mock):
        resolve_mock.return_value = _template_context()
        catalog_mock.return_value = ([], _object_fields(), "Account")
        adapter_mock.return_value.get_object_fields.return_value = _object_fields()
        original = pd.DataFrame({"Name": ["Acme"], "Notes": ["secret"]})
        rows, _ = build_workbench_mapping_rows(["Name", "Notes"], "Customers", "Insert")
        keep_existing_header(rows, "Name")
        exclude_mapping(rows, "Notes")
        active = _active_columns(original, rows)
        self.assertEqual(active, ["Name"])

    def test_corrected_df_is_downloadable(self):
        corrected = pd.DataFrame({"Name": ["Acme"], "BillingCity": ["Paris"]})
        buffer = io.StringIO()
        corrected.to_csv(buffer, index=False)
        self.assertIn("BillingCity", buffer.getvalue())

    @patch("services.workbench_mapping_service.get_adapter")
    @patch("services.workbench_mapping_service.get_workbench_field_catalog")
    @patch("services.workbench_mapping_service.resolve_template")
    def test_downloaded_csv_contains_only_retained_columns(self, resolve_mock, catalog_mock, adapter_mock):
        resolve_mock.return_value = _template_context()
        catalog_mock.return_value = ([], _object_fields(), "Account")
        adapter_mock.return_value.get_object_fields.return_value = _object_fields()
        original = pd.DataFrame({
            "Name": ["Acme"],
            "Billing City": ["Paris"],
            "Notes": ["ignore"],
        })
        rows, _ = build_workbench_mapping_rows(list(original.columns), "Customers", "Insert")
        keep_existing_header(rows, "Name")
        apply_mapping_action(rows, "Billing City", MAPPING_ACTION_MAP, "BillingCity")
        exclude_mapping(rows, "Notes")
        mapped = build_mapped_df(original, rows)
        csv_text = mapped.to_csv(index=False)
        self.assertIn("Name", csv_text)
        self.assertIn("BillingCity", csv_text)
        self.assertNotIn("Notes", csv_text)

    @patch("services.workbench_mapping_service.get_adapter")
    @patch("services.workbench_mapping_service.get_workbench_field_catalog")
    @patch("services.workbench_mapping_service.resolve_template")
    def test_streamlit_reruns_preserve_mapping_choices(self, resolve_mock, catalog_mock, adapter_mock):
        resolve_mock.return_value = _template_context()
        catalog_mock.return_value = ([], _object_fields(), "Account")
        adapter_mock.return_value.get_object_fields.return_value = _object_fields()
        rows, _ = build_workbench_mapping_rows(["Name", "Notes"], "Customers", "Insert")
        keep_existing_header(rows, "Name")
        exclude_mapping(rows, "Notes")
        session = rows_to_session(rows)
        fresh_rows, _ = build_workbench_mapping_rows(["Name", "Notes"], "Customers", "Insert")
        apply_session_to_rows(fresh_rows, session)
        self.assertTrue(all(row.get("resolved") for row in fresh_rows))
        self.assertEqual(get_excluded_columns(fresh_rows), {"Notes"})

    def test_invalid_rows_are_filtered_before_render(self):
        rows = [
            {"uploaded_column": "", "dit_column": "", "status": MAPPING_STATUS_EXCLUDED},
            {"uploaded_column": "Name", "dit_column": "Name", "status": MAPPING_STATUS_CONFIRMED},
        ]
        valid = filter_valid_mapping_rows(rows)
        self.assertEqual(len(valid), 1)
        self.assertFalse(is_valid_mapping_row(rows[0]))

    def test_filter_blank_header_columns_returns_skipped_headers(self):
        df = pd.DataFrame([["", "Acme"], ["", "Beta"]])
        filtered_df, filtered_headers, skipped = filter_blank_header_columns(df, ["", "Name"])
        self.assertEqual(filtered_headers, ["Name"])
        self.assertEqual(skipped, [""])

    def test_load_uploaded_csv_skips_blank_headers(self):
        content = ",Name\n,Acme\n,Beta\n".encode("utf-8-sig")

        class UploadedStub:
            def getvalue(self):
                return content

        df, headers = load_uploaded_csv(UploadedStub())
        self.assertEqual(headers, ["Name"])
        self.assertEqual(list(df.columns), ["Name"])
        self.assertEqual(df.attrs.get("skipped_headers"), [""])

    def test_mapping_summary_counts(self):
        rows = [
            {"uploaded_column": "Name", "dit_column": "Name", "resolved": True, "status": MAPPING_STATUS_EXACT_API},
            {"uploaded_column": "Notes", "dit_column": "Notes", "resolved": True, "status": MAPPING_STATUS_EXCLUDED},
            {"uploaded_column": "City", "dit_column": "City", "resolved": False, "status": "Unresolved"},
        ]
        summary = get_mapping_summary(rows)
        self.assertEqual(summary["resolved"], 2)
        self.assertEqual(summary["excluded"], 1)
        self.assertEqual(summary["unresolved"], 1)
