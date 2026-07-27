"""Live metadata integration tests for Account Relationship Workbench catalog."""

from __future__ import annotations

import unittest

from services.metadata_provider_factory import clear_metadata_adapter_cache
from core.config import EUSFA_SFDX_REPO_PATH
from services.template_service import resolve_template
from services.workbench_field_catalog_service import (
    ACCOUNT_RELATIONSHIP_VERIFICATION_CHECKLIST,
    build_field_metadata_debug_report,
    format_field_type,
    get_workbench_field_catalog,
)


@unittest.skipUnless(
    (EUSFA_SFDX_REPO_PATH / "force-app" / "main" / "default").is_dir(),
    "EUSFA SFDX metadata repo not available",
)
class AccountRelationshipFieldCatalogIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        clear_metadata_adapter_cache()

    def test_template_resolves_account_relationship_object(self):
        context = resolve_template("Account Relationship")
        self.assertIsNotNone(context)
        assert context is not None
        self.assertTrue(context.metadata_available)
        self.assertEqual(context.salesforce_object, "Account_Relationship__c")
        assert context.template_definition is not None
        self.assertEqual(
            context.template_definition.object_api_name,
            "Account_Relationship__c",
        )
        self.assertEqual(context.template_definition.developer_name, "Account_Relationship")

    def test_catalog_contains_all_metadata_fields_and_checklist_coverage(self):
        options, object_fields, object_name = get_workbench_field_catalog(
            "Account Relationship",
            "Insert",
        )
        self.assertEqual(object_name, "Account_Relationship__c")
        self.assertEqual(len(options), len(object_fields))
        self.assertGreaterEqual(len(object_fields), 11)

        report = build_field_metadata_debug_report("Account Relationship", "Insert")
        missing = set(report["missing_checklist_fields"])
        self.assertNotIn("Related_Account_ExternaIId__c", missing)
        self.assertIn("Is_Primary__c", missing)

        for field_name in (
            "Active__c",
            "Customer_Account__c",
            "Customer_ERP_ID__c",
            "Customer_ERP_Name__c",
            "Customer_External_Id__c",
            "Market__c",
            "OwnerId",
            "RecordTypeId",
            "CurrencyIsoCode",
            "Related_Account_ExternaIId__c",
            "Related_Account__c",
            "Relationship_Type__c",
            "Wholesaler_Relationship__c",
        ):
            self.assertIn(field_name, object_fields, f"{field_name} missing from catalog")

        active = object_fields["Active__c"]
        self.assertEqual(active.field_type.lower(), "checkbox")
        self.assertEqual(format_field_type(active), "Boolean")

        customer_account = object_fields["Customer_Account__c"]
        self.assertEqual(customer_account.reference_to, "Account")
        self.assertEqual(format_field_type(customer_account), "Lookup(Account)")

        related_external = object_fields["Related_Account_ExternaIId__c"]
        self.assertEqual(related_external.field_type.lower(), "text")

        market = next(
            item for item in report["picklist_fields_discovered"]
            if item["api_name"] == "Market__c"
        )
        self.assertEqual(market["value_set_name"], "Country_Markets")
        self.assertGreater(market["allowed_value_count"], 0)

        relationship_type = next(
            item for item in report["picklist_fields_discovered"]
            if item["api_name"] == "Relationship_Type__c"
        )
        self.assertIn("Wholesaler", relationship_type["allowed_values_sample"])

        dropdown_labels = {option.display_label for option in options}
        for field_name in (
            "Customer_Store_Id__c",
            "Related_Account__c",
            "Wholesaler_Relationship__c",
        ):
            self.assertTrue(
                any(label.startswith(f"{field_name} —") for label in dropdown_labels),
                f"{field_name} missing from dropdown labels",
            )

        self.assertEqual(
            set(ACCOUNT_RELATIONSHIP_VERIFICATION_CHECKLIST) - set(object_fields),
            {"Is_Primary__c"},
        )


if __name__ == "__main__":
    unittest.main()
