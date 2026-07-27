"""Tests for live Salesforce record existence and unified preparation checks."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from adapters.sfdx_metadata.models import FieldDefinition
from clients.salesforce_client import UnavailableSalesforceClient
from services.constants import (
    RECORD_CHECK_DUPLICATE_MATCH,
    RECORD_CHECK_FOUND,
    RECORD_CHECK_NEW_IDENTIFIER,
    RECORD_CHECK_NOT_EVALUATED,
    RECORD_CHECK_NOT_FOUND,
    RECORD_CHECK_POSSIBLE_EXISTING,
    RECORD_CHECK_UNAVAILABLE,
)
from services.external_id_discovery_service import discover_external_id_fields, discover_identifier_fields
from services.salesforce_record_lookup_service import lookup_records_by_field
from services.template_service import TemplateContext
from validators.load_action_validator import validate_load_action, not_evaluated_load_action_result
from validators.picklist_validator import validate_picklists
from validators.record_existence_validator import validate_record_existence


def _field(
    api_name: str,
    field_type: str = "Text",
    *,
    external_id: bool = False,
    unique: bool = False,
) -> FieldDefinition:
    return FieldDefinition(
        api_name,
        api_name,
        field_type,
        False,
        external_id=external_id,
        unique=unique,
    )


def _template_context(object_name: str = "Account") -> TemplateContext:
    return TemplateContext(
        template_name="Customers",
        metadata_available=True,
        template_definition=None,
        salesforce_object=object_name,
        fallback_config=None,
        metadata_message=None,
        record_type_name="Customer",
        required_type_value="Customer",
        account_type_valid=True,
        account_type_error=None,
        is_account_template=True,
    )


def _mapping_rows(api_field: str, uploaded_column: str) -> list[dict]:
    return [{
        "uploaded_column": uploaded_column,
        "confirmed_api_field": api_field,
        "status": "Confirmed",
        "action": "map",
    }]


class MockSalesforceClient:
    def __init__(self, matches: dict[str, list[dict[str, str]]] | None = None, available: bool = True):
        self._matches = matches or {}
        self._available = available

    def is_configured(self) -> bool:
        return self._available

    def test_connection(self) -> dict:
        if not self._available:
            return {"available": False, "status": "unavailable", "message": RECORD_CHECK_UNAVAILABLE}
        return {"available": True, "status": "connected", "message": "connected"}

    def query(self, soql: str) -> dict:
        records = []
        for value, matches in self._matches.items():
            for match in matches:
                records.append({**match, "External_Id__c": value})
        return {"records": records, "totalSize": len(records)}


class RecordExistenceValidationTests(unittest.TestCase):
    def setUp(self):
        self.adapter_patcher = patch("services.external_id_discovery_service.get_adapter")
        self.mock_get_adapter = self.adapter_patcher.start()
        self.mock_get_adapter.return_value.get_object_fields.return_value = {
            "External_Id__c": _field("External_Id__c", external_id=True),
            "Name": _field("Name", "Text"),
            "Id": _field("Id", "Id"),
        }

    def tearDown(self):
        self.adapter_patcher.stop()

    def test_prepare_and_validate_not_evaluated(self):
        result = validate_record_existence(
            pd.DataFrame({"External_Id__c": ["A"]}),
            _mapping_rows("External_Id__c", "External Id"),
            None,
            _template_context(),
            client=MockSalesforceClient(),
        )
        self.assertEqual(result["status"], RECORD_CHECK_NOT_EVALUATED)
        load_action = not_evaluated_load_action_result()
        self.assertFalse(load_action["evaluated"])

    def test_insert_no_id_required(self):
        load_action = validate_load_action(
            pd.DataFrame({"External_Id__c": ["A"]}),
            _mapping_rows("External_Id__c", "External Id"),
            "Insert",
            _template_context(),
        )
        self.assertFalse(load_action["requires_id"])

    def test_update_requires_identifier(self):
        load_action = validate_load_action(
            pd.DataFrame({"Name": ["Acme"]}),
            _mapping_rows("Name", "Name"),
            "Update",
            _template_context(),
        )
        self.assertTrue(load_action["requires_id"])

    def test_external_id_from_metadata(self):
        fields = discover_external_id_fields("Account")
        api_names = {field["field_api_name"] for field in fields}
        self.assertIn("External_Id__c", api_names)

    def test_insert_warns_existing_identifier(self):
        client = MockSalesforceClient({
            "existing-1": [{"Id": "001xx", "External_Id__c": "existing-1"}],
        })
        result = validate_record_existence(
            pd.DataFrame({"External_Id__c": ["existing-1", "new-1"]}),
            _mapping_rows("External_Id__c", "External_Id__c"),
            "Insert",
            _template_context(),
            identifier_field="External_Id__c",
            use_mapped_columns=True,
            client=client,
        )
        statuses = {row["status"] for row in result["row_results"]}
        self.assertIn(RECORD_CHECK_POSSIBLE_EXISTING, statuses)
        self.assertIn(RECORD_CHECK_NEW_IDENTIFIER, statuses)

    def test_insert_allows_new_identifier(self):
        client = MockSalesforceClient({})
        result = validate_record_existence(
            pd.DataFrame({"External_Id__c": ["brand-new"]}),
            _mapping_rows("External_Id__c", "External_Id__c"),
            "Insert",
            _template_context(),
            identifier_field="External_Id__c",
            use_mapped_columns=True,
            client=client,
        )
        self.assertEqual(result["row_results"][0]["status"], RECORD_CHECK_NEW_IDENTIFIER)

    def test_update_passes_one_match(self):
        client = MockSalesforceClient({
            "acct-1": [{"Id": "001MATCH", "External_Id__c": "acct-1"}],
        })
        result = validate_record_existence(
            pd.DataFrame({"External_Id__c": ["acct-1"]}),
            _mapping_rows("External_Id__c", "External_Id__c"),
            "Update",
            _template_context(),
            identifier_field="External_Id__c",
            use_mapped_columns=True,
            client=client,
        )
        self.assertEqual(result["row_results"][0]["status"], RECORD_CHECK_FOUND)
        self.assertEqual(result["row_results"][0]["salesforce_ids"], ["001MATCH"])

    def test_update_flags_missing(self):
        client = MockSalesforceClient({})
        result = validate_record_existence(
            pd.DataFrame({"External_Id__c": ["missing"]}),
            _mapping_rows("External_Id__c", "External_Id__c"),
            "Update",
            _template_context(),
            identifier_field="External_Id__c",
            use_mapped_columns=True,
            client=client,
        )
        self.assertEqual(result["row_results"][0]["status"], RECORD_CHECK_NOT_FOUND)
        self.assertTrue(result["blocks_download"])

    def test_update_flags_duplicates(self):
        client = MockSalesforceClient({
            "dup": [
                {"Id": "001A", "External_Id__c": "dup"},
                {"Id": "001B", "External_Id__c": "dup"},
            ],
        })
        result = validate_record_existence(
            pd.DataFrame({"External_Id__c": ["dup"]}),
            _mapping_rows("External_Id__c", "External_Id__c"),
            "Update",
            _template_context(),
            identifier_field="External_Id__c",
            use_mapped_columns=True,
            client=client,
        )
        self.assertEqual(result["row_results"][0]["status"], RECORD_CHECK_DUPLICATE_MATCH)

    def test_connection_failure_no_false_not_found(self):
        result = validate_record_existence(
            pd.DataFrame({"External_Id__c": ["any"]}),
            _mapping_rows("External_Id__c", "External_Id__c"),
            "Update",
            _template_context(),
            identifier_field="External_Id__c",
            use_mapped_columns=True,
            client=UnavailableSalesforceClient(),
        )
        self.assertEqual(result["status"], RECORD_CHECK_UNAVAILABLE)
        self.assertEqual(result["row_results"], [])
        self.assertFalse(result["blocks_download"])

    def test_batched_queries(self):
        client = MagicMock()
        client.is_configured.return_value = True
        client.test_connection.return_value = {"available": True, "status": "connected"}
        client.query.return_value = {"records": [], "totalSize": 0}

        values = [f"VAL-{index}" for index in range(450)]
        lookup_records_by_field(client, "Account", "External_Id__c", values)
        self.assertEqual(client.query.call_count, 3)

    def test_local_repo_not_treated_as_live_db(self):
        client = MockSalesforceClient({})
        with patch(
            "validators.record_existence_validator.lookup_records_by_field",
            wraps=lookup_records_by_field,
        ) as lookup_mock:
            validate_record_existence(
                pd.DataFrame({"External_Id__c": ["x"]}),
                _mapping_rows("External_Id__c", "External_Id__c"),
                "Insert",
                _template_context(),
                identifier_field="External_Id__c",
                use_mapped_columns=True,
                client=client,
            )
            lookup_mock.assert_called_once()


class PicklistMetadataValidationTests(unittest.TestCase):
    def setUp(self):
        self.adapter = MagicMock()
        self.adapter.get_object_fields.side_effect = lambda obj: {
            "Account": {
                "Type": FieldDefinition("Type", "Type", "Picklist", False),
                "Name": FieldDefinition("Name", "Name", "Text", False),
                "L1_Channel__c": FieldDefinition("L1_Channel__c", "Channel", "Picklist", False),
            },
        }.get(obj, {})
        self.adapter.get_picklist_value_details.side_effect = lambda obj, field: {
            ("Account", "Type"): [
                type("PV", (), {"api_name": "Customer", "label": "Customer Label", "is_active": True})(),
            ],
            ("Account", "L1_Channel__c"): [
                type("PV", (), {"api_name": "AWAY FROM HOME", "label": "Away From Home", "is_active": True})(),
            ],
        }.get((obj, field), [])
        self.adapter.has_record_type_picklist_restriction.return_value = False
        self.adapter.get_allowed_values_for_record_type.side_effect = (
            lambda obj, rt, field: ["Customer"] if field == "Type" else ["AWAY FROM HOME"]
        )

    @patch("validators.picklist_validator.get_adapter", create=True)
    def test_picklist_detection_via_api_field_metadata(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        df = pd.DataFrame({"Type": ["Customer"]})
        result = validate_picklists(
            df,
            _mapping_rows("Type", "Type"),
            _template_context(),
            use_mapped_columns=True,
        )
        self.assertTrue(result["field_summaries"])
        self.assertEqual(result["field_summaries"][0]["check_type"], "field_identification")

    @patch("validators.picklist_validator.get_adapter", create=True)
    def test_non_picklist_skipped(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        df = pd.DataFrame({"Name": ["Acme"]})
        result = validate_picklists(
            df,
            _mapping_rows("Name", "Name"),
            _template_context(),
            use_mapped_columns=True,
        )
        self.assertEqual(result["field_summaries"], [])

    @patch("validators.picklist_validator.get_adapter", create=True)
    def test_api_name_not_confused_with_value(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        df = pd.DataFrame({"Type": ["Type"]})
        result = validate_picklists(
            df,
            _mapping_rows("Type", "Type"),
            _template_context(),
            use_mapped_columns=True,
        )
        invalid = [issue for issue in result["issues"] if issue["status"] == "Needs User Action"]
        self.assertTrue(invalid)

    @patch("validators.picklist_validator.get_adapter", create=True)
    def test_valid_stored_value_passes(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        result = validate_picklists(
            pd.DataFrame({"Type": ["Customer"]}),
            _mapping_rows("Type", "Type"),
            _template_context(),
            use_mapped_columns=True,
        )
        self.assertGreater(result["valid_count"], 0)

    @patch("validators.picklist_validator.get_adapter", create=True)
    def test_invalid_value_flagged(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        result = validate_picklists(
            pd.DataFrame({"Type": ["NotARealValue"]}),
            _mapping_rows("Type", "Type"),
            _template_context(),
            use_mapped_columns=True,
        )
        self.assertGreater(result["invalid_count"], 0)

    @patch("validators.picklist_validator.get_adapter", create=True)
    def test_suggested_changes_need_approval(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        result = validate_picklists(
            pd.DataFrame({"L1_Channel__c": [" AWAY FROM HOME "]},
            ),
            _mapping_rows("L1_Channel__c", "L1_Channel__c"),
            _template_context(),
            use_mapped_columns=True,
        )
        cleanup = [
            issue for issue in result["issues"]
            if issue.get("requires_approval")
        ]
        self.assertTrue(cleanup)

    @patch("validators.picklist_validator.get_adapter", create=True)
    def test_record_type_restrictions(self, adapter_mock):
        adapter_mock.return_value = self.adapter
        adapter_mock.return_value.has_record_type_picklist_restriction.return_value = True
        adapter_mock.return_value.get_allowed_values_for_record_type.return_value = ["Customer"]
        result = validate_picklists(
            pd.DataFrame({"Type": ["Prospect"]}),
            _mapping_rows("Type", "Type"),
            _template_context(),
            use_mapped_columns=True,
        )
        self.assertGreater(result["invalid_count"], 0)


class UnifiedPreparationPipelineTests(unittest.TestCase):
    def test_all_tasks_use_row_validation(self):
        from services.row_correction_plan_service import build_row_correction_plan

        df = pd.DataFrame({"External Id": ["1"]})
        with patch("services.row_correction_plan_service.resolve_template") as resolve_mock:
            resolve_mock.return_value = _template_context()
            for _load_operation in (None, "Insert", "Update"):
                plan = build_row_correction_plan(
                    df,
                    "Workbench",
                    "Customers",
                    mapping_rows=_mapping_rows("External_Id__c", "External Id"),
                )
                self.assertIn("summary", plan)

    def test_header_mapping_required_for_all_tasks(self):
        rows = _mapping_rows("External_Id__c", "External Id")
        self.assertEqual(rows[0]["confirmed_api_field"], "External_Id__c")

    def test_discover_identifier_fields_includes_unique_and_external(self):
        adapter = MagicMock()
        adapter.get_object_fields.return_value = {
            "External_Id__c": _field("External_Id__c", external_id=True),
            "SKU__c": _field("SKU__c", unique=True),
            "Name": _field("Name"),
        }
        discovered = discover_identifier_fields("Product2", adapter)
        kinds = {
            field["field_api_name"]: field["identifier_kinds"]
            for field in discovered
        }
        self.assertIn("External ID", kinds["External_Id__c"])
        self.assertIn("Unique", kinds["SKU__c"])


if __name__ == "__main__":
    unittest.main()
