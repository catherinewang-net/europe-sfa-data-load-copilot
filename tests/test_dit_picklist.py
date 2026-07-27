"""Tests for DIT picklist validation via synthetic mapping rows."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from adapters.sfdx_metadata.models import FieldDefinition, PicklistValue, TemplateDefinition
from services.constants import MAPPING_ACTION_MAP
from services.template_service import TemplateContext
from validators.picklist_validator import validate_picklists
from workflow.copilot import build_dit_mapping_rows


def _field(api_name: str, field_type: str, *, required: bool = False) -> FieldDefinition:
    return FieldDefinition(api_name, api_name, field_type, required)


def _template_context() -> TemplateContext:
    return TemplateContext(
        template_name="Customers",
        salesforce_object="Account",
        template_definition=TemplateDefinition(
            name="Customers",
            developer_name="Customers_Account",
            object_api_name="Account",
            is_active=True,
            csv_label_to_api={"*L1 Channel": "L1_Channel__c", "L1_Channel__c": "L1_Channel__c"},
            api_to_csv_label={"L1_Channel__c": "*L1 Channel"},
            required_csv_labels=(),
        ),
        metadata_available=True,
        metadata_message=None,
        fallback_config=None,
        record_type_name=None,
        required_type_value="Customer",
        account_type_valid=True,
        account_type_error=None,
        is_account_template=True,
    )


class DitPicklistTests(unittest.TestCase):
    def test_build_dit_mapping_rows(self):
        rows = build_dit_mapping_rows(["*L1 Channel", "L1_Channel__c"], "Customers")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["confirmed_api_field"], "L1_Channel__c")
        self.assertEqual(rows[0]["action"], MAPPING_ACTION_MAP)
        self.assertEqual(rows[1]["confirmed_api_field"], "L1_Channel__c")

    @patch("validators.picklist_validator.get_adapter")
    def test_dit_picklist_validation_with_friendly_headers(self, adapter_getter):
        adapter = MagicMock()
        adapter_getter.return_value = adapter
        adapter.get_object_fields.return_value = {
            "L1_Channel__c": _field("L1_Channel__c", "picklist"),
        }
        adapter.get_picklist_value_details.return_value = [
            PicklistValue("AWAY FROM HOME", "AWAY FROM HOME"),
        ]
        adapter.has_record_type_picklist_restriction.return_value = False

        df = pd.DataFrame({"*L1 Channel": [" AWAY FROM HOME ", "INVALID"]})
        mapping_rows = build_dit_mapping_rows(list(df.columns), "Customers")
        result = validate_picklists(
            df,
            mapping_rows,
            _template_context(),
            use_mapped_columns=False,
        )
        self.assertEqual(result["invalid_count"], 1)
        self.assertTrue(any(issue["status"] == "Needs User Action" for issue in result["issues"]))


if __name__ == "__main__":
    unittest.main()
