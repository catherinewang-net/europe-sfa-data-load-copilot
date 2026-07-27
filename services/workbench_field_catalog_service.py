"""Workbench Salesforce field catalog — full object field list for mapping dropdowns."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from difflib import get_close_matches
from typing import Any

from adapters.sfdx_metadata.models import FieldDefinition
from adapters.sfdx_metadata.standard_field_supplements import (
    supplement_object_fields,
)
from services.external_id_discovery_service import discover_external_id_fields
from services.picklist_field_catalog import get_picklist_fields
from services.template_service import get_adapter, resolve_template
from services.workbench_field_matcher import normalize_header_for_matching, tokenize_header

FREQUENCY_FIELD_INVALID_XML_MESSAGE = (
    "Frequency__c exists in the verification catalog, but its local metadata file "
    "could not be parsed. Manual verification is required."
)

ASSORTMENT_VERIFICATION_CHECKLIST = (
    "AssortmentExtID__c", "AssortmentType__c", "CurrencyIsoCode", "Description",
    "External_Id__c", "Market__c", "Name", "OwnerId",
)

ASSORTMENT_ASSIGNMENT_VERIFICATION_CHECKLIST = (
    "AssortmentExtID__c", "Assortment_Name__c", "Assortment__c", "CurrencyIsoCode",
    "Cust_L1__c", "Cust_L2__c", "Cust_L3_bevs__c", "Cust_L3_snacks__c", "EndDate__c",
    "Key_Account_Banner__c", "L3_Customer_Class__c", "L4_Customer_Subtype__c",
    "Market__c", "OwnerId", "Shopper_Led_Cluster__c", "StartDate__c",
)

ASSORTMENT_PRODUCT_VERIFICATION_CHECKLIST = (
    "Active__c", "AssortmentExtID__c", "AssortmentId", "AssortmentName__c",
    "CurrencyIsoCode", "DefaultOrderQuantity", "End_Date__c", "External_Id__c",
    "IsFavorite", "ProductExtID__c", "ProductId", "ProducttName__c", "Start_Date__c",
    "StockKeepingUnit__c",
)

CONTACT_VERIFICATION_CHECKLIST = (
    "AccountId", "BuyerAttributes", "ContactSource", "CurrencyIsoCode", "Department",
    "DepartmentGroup", "Email", "EmailBouncedDate", "EmailBouncedReason", "Fax",
    "FirstName", "GDPR__c", "Jigsaw", "Job_Title__c", "LastName", "MailingCity",
    "MailingCountry", "MailingGeocodeAccuracy", "MailingLatitude", "MailingLongitude",
    "MailingPostalCode", "MailingState", "MailingStreet", "Market__c", "MiddleName",
    "MobilePhone", "OwnerId", "Phone", "Primary_or_Secondary__c", "ReportsToId",
    "Salutation", "Suffix", "Title", "TitleType",
)

CONTRACT_VERIFICATION_CHECKLIST = (
    "AccountId", "BillingCity", "BillingCountry", "BillingGeocodeAccuracy",
    "BillingLatitude", "BillingLongitude", "BillingPostalCode", "BillingState",
    "BillingStreet", "CompanySignedDate", "CompanySignedId", "ContractTerm",
    "Contract_Type__c", "Contract_Value__c", "CurrencyIsoCode", "CurrencyISOCode__c",
    "CustomerSignedDate", "CustomerSignedId", "CustomerSignedTitle", "Description",
    "Duration__c", "Generate_PDF__c", "HasEquipmentAmendments__c", "HasEquipmentLines__c",
    "HasInvestmentAmmendments__c", "HasInvestmentLines__c", "HasRebateAmmendments__c",
    "HasRebateLines__c", "Market__c", "Name", "Number_of_Invoices_Signed__c",
    "OwnerExpirationNotice", "OwnerId", "Period__c", "Pricebook2Id", "ShippingCity",
    "ShippingCountry", "ShippingGeocodeAccuracy", "ShippingLatitude", "ShippingLongitude",
    "ShippingPostalCode", "ShippingState", "ShippingStreet", "SpecialTerms", "StartDate",
    "Status", "Wholesaler__c",
)

CUSTOMER_TO_ROUTE_VERIFICATION_CHECKLIST = (
    "Close_Hour__c", "CurrencyIsoCode", "Delivery_End_Time__c", "Delivery_Start_Time__c",
    "Frequency__c", "Friday_Sequence__c", "IsPrimary__c", "Market__c", "Monday_Sequence__c",
    "Open_Hour__c", "OwnerId", "Route_ID__c", "Saturday_Sequence__c",
    "Seasonal_Closed_End_Date__c", "Seasonal_Closed_Start_Date__c", "Seasonal_Status__c",
    "Sunday_Sequence__c", "Thursday_Sequence__c", "Tuesday_Sequence__c", "Valid_from_Date__c",
    "Valid_to_Date__c", "Visit_Plan_ID__c", "Wednesday_Sequence__c", "Working_months__c",
)

ORDER_VERIFICATION_CHECKLIST = (
    "AccountId", "BillingCity", "BillingCountry", "BillingGeocodeAccuracy", "BillingLatitude",
    "BillingLongitude", "BillingPostalCode", "BillingState", "BillingStreet", "BillToContactId",
    "Car_Sales_Return_Reason__c", "CompanyAuthorizedById", "CompanyAuthorizedDate", "ContractId",
    "CurrencyIsoCode", "CustomerAuthorizedById", "CustomerAuthorizedDate", "Delivery_Date__c",
    "Description", "EffectiveDate", "EndDate", "External_Id__c", "First_Order__c",
    "IsReductionOrder", "Line_Discount__c", "Name", "OrderReferenceNumber", "OriginalOrderId",
    "OwnerId", "PoDate", "PoNumber", "Pricebook2Id", "Requested_Status__c", "ShippingCity",
    "ShippingCountry", "ShippingGeocodeAccuracy", "ShippingLatitude", "ShippingLongitude",
    "ShippingPostalCode", "ShippingState", "ShippingStreet", "ShipToContactId", "Status",
    "Total_Net_Value__c", "Total_Tax__c", "Type", "Visit__c",
)

ORDER_ITEM_VERIFICATION_CHECKLIST = (
    "CurrencyISOCode__c", "Description", "EndDate", "OrderId", "OriginalOrderItemId",
    "PricebookEntryId", "Product2Id", "Quantity", "ServiceDate", "Tax_Rate__c", "UnitPrice",
)

ROUTE_SALES_GEO_VERIFICATION_CHECKLIST = (
    "CurrencyIsoCode", "External_Id__c", "Hierarchy_Level_Code__c", "Hierarchy_Level__c",
    "Is_Active__c", "KPI_G_01_Target__c", "KPI_G_11_Target__c", "KPI_Last_Sync__c",
    "KPI_P_20_Target__c", "KPI_S_06_Target__c", "KPI_S_07_Target__c", "KPI_S_08_Target__c",
    "KPI_S_10_Target__c", "KPI_S_23_Target__c", "Market__c", "Name", "OwnerId",
    "Parent_Node__c", "RecordTypeId", "Route_End_Date__c", "Route_Start_Date__c",
    "Sales_Unit_Active_Flag_Value__c", "Sales_Unit_Description__c", "Sales_Unit_GTM_End_Date__c",
    "Sales_Unit_GTM_Start_Date__c", "Sales_Unit_Name__c", "S_09_Target__c",
)

UNITS_OF_MEASURE_VERIFICATION_CHECKLIST = (
    "CurrencyIsoCode", "Description", "Name", "OwnerId", "Type", "UnitCode",
)

ACCOUNT_RELATIONSHIP_VERIFICATION_CHECKLIST = (
    "Active__c", "CurrencyIsoCode", "Customer_Account__c", "Customer_ERP_ID__c",
    "Customer_ERP_Name__c", "Customer_External_Id__c", "Is_Primary__c", "Market__c",
    "OwnerId", "RecordTypeId", "Related_Account_ExternaIId__c", "Related_Account__c",
    "Relationship_Type__c", "Wholesaler_Relationship__c",
)

ACCOUNT_VERIFICATION_CHECKLIST = (
    "AccountNumber", "AccountSource", "Account_Unified_Id__c", "Active__c",
    "ALL_MSL_Missing_Date__c", "All_MSL_Missing__c", "AnnualRevenue",
    "Annual_Sales_Beverages__c", "Annual_Sales_Food__c", "Annual_Volume_Beverages__c",
    "Annual_Volume_Food__c", "B2B_Status__c", "BillingCity", "BillingCountry",
    "BillingGeocodeAccuracy", "BillingLatitude", "BillingLongitude", "BillingPostalCode",
    "BillingState", "BillingStreet", "Buying_Categories__c", "Category__c",
    "Centralization_Degree__c", "Comments__c", "Competitor_Contract_Expiration_Date__c",
    "Credit_Balance__c", "Credit_Limit__c", "CurrencyIsoCode", "CurrencyISOCode__c",
    "Cust_ID_System_of_Record__c", "CUST_ID__c", "Cust_L2__c", "Cust_Tax_Class__c",
    "Deactivate_Date__c", "Delivery_Day__c", "Delivery_Window_End_Time__c",
    "Delivery_Window_Start_Time__c", "Description", "Digital_Platform_Type__c",
    "Disqual_Reason__c", "DSD_Status__c", "ERP_Name__c", "EUSFA_Next_Visit__c",
    "EUSFA_Picos_Points__c", "EUSFA_Visits_Executed__c", "EUSFA_Weeks_Since_Last_Visit__c",
    "External_Segmentation_Bevs__c", "External_Segmentation_Snacks__c", "Fax",
    "GDPR_Date_Last_Checked__c", "GLN__c", "GTM_Model__c", "GTM_Status__c", "IBAN__c",
    "ImageURL__c", "Industry", "Jigsaw", "KeyAccountId__c", "Key_Account_Banner__c",
    "L1_Channel__c", "L2_Subchannel__c", "L3_Bevs_Pricegroup_Cluster__c",
    "L3_Bevs_Value_Segmentation__c", "L3_Classification__c",
    "L3_Snacks_Pricegroup_Cluster__c", "L3_Snacks_Value_Segmentation__c", "L4_Classification__c",
    "L4_Local_Definition__c", "Language__c", "Last_Order_Date__c", "Lead_Status__c",
    "Legacy_Name__c", "Legal_Entity_Name__c", "Level__c", "Local_Tax_ID__c",
    "maps__AssignmentRule__c", "Market__c", "Microsegment__c", "Missing_MSL_Visit_Count__c",
    "Name", "Notes__c", "NumberOfEmployees", "Open_Hours_End_Time__c",
    "Open_Hours_Start_Time__c", "OperatingHoursId", "OwnerId", "Ownership", "ParentId",
    "Payer_Email_Address__c", "Payer__c", "Payment_Terms__c", "Payment_Type__c", "Phone",
    "Picos_Opportunity__c", "Pricegroup_Cluster__c", "Primary_Contact__c",
    "Primary_Wholesaler__c", "PS_L4_Shopper_Led_Cluster__c", "Rating", "RecordTypeId",
    "SAP_ID__c", "Seasonal_Closed_End_Date__c", "Seasonal_Closed_Start_Date__c",
    "Seasonal_Status__c", "Secondary_Wholesaler__c", "Self_Certified__c", "ShippingCity",
    "ShippingCountry", "ShippingGeocodeAccuracy", "ShippingLatitude", "ShippingLongitude",
    "ShippingPostalCode", "ShippingState", "ShippingStreet", "Sic", "SicDesc", "Site",
    "Status__c", "Store_Email_Optin__c", "Store_Email__c", "Store_GTM_Status__c",
    "Store_SMS_OptIn__c", "Tax_ID__c", "TickerSymbol", "Total_Missing_MSL_count__c",
    "Total_MSL_count__c", "Type", "UoM_Beverages__c", "UoM_Foods__c", "Valid_from_Date__c",
    "Website",     "Wholesaler_Store_ID__c",
)

PRICELIST_VERIFICATION_CHECKLIST = (
    "CurrencyIsoCode", "OwnerId",
)

PRODUCTS_VERIFICATION_CHECKLIST = (
    "AvailabilityDate", "BasedOnId", "BUoM__c", "Category__c", "ConfigureDuringSale", "Container_Type__c",
    "CurrencyIsoCode", "CurrencyIsoCode__c", "Description", "DiscontinuedDate", "DisplayUrl", "EAN__c",
    "EndOfLifeDate", "ExternalDataSourceId", "ExternalId", "External_Id__c", "Family", "HelpText", "IsActive",
    "IsAssetizable", "IsSoldOnlyWithOtherProds", "Language_Code__c", "Legacy_Name__c", "List_Price__c",
    "Manufacturer__c", "Market__c", "Name", "Parent_SKU__c", "ProductCode", "Product_Hierarchy_Level__c",
    "Product_Icon__c", "Prod_Brand_Description__c", "Prod_Brand_Id__c", "Prod_Brand_PRT__c", "Prod_Brand__c",
    "Prod_Container_Type_PRT__c", "Prod_Count__c", "Prod_Flavor__c", "Prod_Format__c", "Prod_Group_Description__c",
    "Prod_Group_Id__c", "Prod_Group_PRT__c", "Prod_Group__c", "Prod_Line_Description__c", "Prod_Line_Id__c",
    "Prod_Line_PRT__c", "Prod_Line__c", "Prod_Size_PRT__c", "Prod_Subbrand_Description__c", "Prod_Subbrand_Id__c",
    "Prod_Subbrand_PRT__c", "Prod_Subbrand__c", "QuantityUnitOfMeasure", "Sales_UoM__c", "Short_Name__c", "Size__c",
    "SKU_ID_System_of_Record__c", "StockKeepingUnit", "Tax_Classification__c", "Tax_Rate__c", "Type", "UoM_Conversion__c",
    "UsedFor",
)

RETAIL_PROMOTION_VERIFICATION_CHECKLIST = (
    "CampaignId", "Category", "CurrencyIsoCode", "Description", "EndDate", "IsActive", "Level", "Methods",
    "Name", "Objective", "OwnerId", "StartDate",
)

TEMPLATE_VERIFICATION_CHECKLISTS: dict[str, tuple[str, ...]] = {
    "Account Object": ACCOUNT_VERIFICATION_CHECKLIST,
    "AccountObject": ACCOUNT_VERIFICATION_CHECKLIST,
    "Account Relationship": ACCOUNT_RELATIONSHIP_VERIFICATION_CHECKLIST,
    "Assortment": ASSORTMENT_VERIFICATION_CHECKLIST,
    "Assortment Assignment": ASSORTMENT_ASSIGNMENT_VERIFICATION_CHECKLIST,
    "Assortment Product": ASSORTMENT_PRODUCT_VERIFICATION_CHECKLIST,
    "Contact": CONTACT_VERIFICATION_CHECKLIST,
    "Contract": CONTRACT_VERIFICATION_CHECKLIST,
    "Customer to Route": CUSTOMER_TO_ROUTE_VERIFICATION_CHECKLIST,
    "Order": ORDER_VERIFICATION_CHECKLIST,
    "Order Item": ORDER_ITEM_VERIFICATION_CHECKLIST,
    "Retail Sales Geo": ROUTE_SALES_GEO_VERIFICATION_CHECKLIST,
    "Units of Measure": UNITS_OF_MEASURE_VERIFICATION_CHECKLIST,
    "Customers": ACCOUNT_VERIFICATION_CHECKLIST,
    "Payers": ACCOUNT_VERIFICATION_CHECKLIST,
    "Prospects": ACCOUNT_VERIFICATION_CHECKLIST,
    "Wholesalers": ACCOUNT_VERIFICATION_CHECKLIST,
    "Key Account": ACCOUNT_VERIFICATION_CHECKLIST,
    "Pricelist Master": PRICELIST_VERIFICATION_CHECKLIST,
    "Products": PRODUCTS_VERIFICATION_CHECKLIST,
    "Retail Promotion": RETAIL_PROMOTION_VERIFICATION_CHECKLIST,
}


def get_verification_checklist(template_name: str) -> tuple[str, ...]:
    """Return the verification checklist for a template, if one is defined."""
    return TEMPLATE_VERIFICATION_CHECKLISTS.get(template_name, ())


@dataclass(frozen=True)
class WorkbenchFieldOption:
    api_name: str
    label: str
    field_type: str
    display_label: str
    writeability: str
    reference_to: str | None
    search_text: str


def get_workbench_field_catalog(
    template_name: str,
    load_operation: str | None = None,
) -> tuple[list[WorkbenchFieldOption], dict[str, FieldDefinition], str | None]:
    """
    Return the full Workbench field catalog for a template's Salesforce object.

    Suggested mappings may use Template_Config, but the available field list always
    comes from adapter.get_object_fields() plus standard-field supplements.
    """
    context = resolve_template(template_name)
    if not context or not context.salesforce_object:
        return [], {}, None

    object_name = context.salesforce_object
    raw_fields = get_adapter().get_object_fields(object_name)
    object_fields = supplement_object_fields(object_name, raw_fields, load_operation)
    options = [
        _build_field_option(field_def)
        for api_name, field_def in sorted(object_fields.items(), key=lambda item: item[0].lower())
    ]
    return options, object_fields, object_name


def get_workbench_field_options(
    template_name: str,
    load_operation: str | None = None,
) -> list[WorkbenchFieldOption]:
    options, _, _ = get_workbench_field_catalog(template_name, load_operation)
    return options


def filter_field_options(
    options: list[WorkbenchFieldOption],
    query: str,
    uploaded_header: str | None = None,
) -> list[WorkbenchFieldOption]:
    """Search by API name, label, normalized text, and uploaded header tokens."""
    q = query.strip().lower()
    header_tokens = tokenize_header(uploaded_header or "")
    query_tokens = tokenize_header(query)
    if not q and not header_tokens:
        return options

    filtered: list[WorkbenchFieldOption] = []
    for option in options:
        haystack = option.search_text
        matches_query = not q or q in haystack or any(token in haystack for token in query_tokens)
        matches_header = not header_tokens or any(token in haystack for token in header_tokens)
        if matches_query and matches_header:
            filtered.append(option)
    return filtered


def format_dropdown_option(field_def: FieldDefinition | WorkbenchFieldOption) -> str:
    if isinstance(field_def, WorkbenchFieldOption):
        return field_def.display_label
    return _build_field_option(field_def).display_label


def parse_api_field_from_display(display_value: str) -> str:
    if display_value in {"— Select API field —", "Do Not Include"}:
        return display_value
    return display_value.split(" — ", 1)[0].strip()


def build_field_metadata_debug_report(
    template_name: str,
    load_operation: str | None = None,
    checklist: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Build a debug report comparing adapter output to the verification checklist."""
    if checklist is None:
        checklist = get_verification_checklist(template_name)

    context = resolve_template(template_name)
    options, object_fields, object_name = get_workbench_field_catalog(template_name, load_operation)
    adapter = get_adapter()
    raw_fields = adapter.get_object_fields(object_name or "") if object_name else {}
    adapter_raw_count = len(raw_fields)
    shown_api_names = [option.api_name for option in options]
    duplicates = sorted({
        name for name in shown_api_names if shown_api_names.count(name) > 1
    })
    missing_labels = [
        option.api_name for option in options if option.label == option.api_name
    ]
    unknown_types = [
        option.api_name for option in options if option.field_type.lower() == "unknown"
    ]
    checklist_found = [field_name for field_name in checklist if field_name in object_fields]
    missing_checklist = [field_name for field_name in checklist if field_name not in object_fields]
    filtered_from_ui = [
        field_name for field_name in checklist
        if field_name in raw_fields and field_name not in object_fields
    ]
    invalid_xml_fields = _discover_invalid_xml_fields(adapter, object_name, missing_checklist)
    spelling_mismatches = _find_spelling_mismatches(missing_checklist, set(object_fields))
    verification_mismatches = _build_verification_mismatches(
        checklist=checklist,
        object_fields=object_fields,
        raw_fields=raw_fields,
        invalid_xml_fields=invalid_xml_fields,
        spelling_mismatches=spelling_mismatches,
        object_resolution_failed=object_name is None,
    )
    picklist_fields = _discover_picklist_fields(object_name, object_fields, adapter)
    lookup_fields = _discover_lookup_fields(object_fields)
    date_fields = _discover_typed_fields(object_fields, {"date", "datetime"})
    boolean_fields = _discover_typed_fields(object_fields, {"boolean", "checkbox"})
    external_id_fields = [
        {
            "api_name": field["field_api_name"],
            "label": field["field_label"],
            "field_type": field["field_type"],
        }
        for field in discover_external_id_fields(object_name or "", adapter)
    ] if object_name else []
    special_validation_hints = _discover_special_validation_hints(object_fields)
    field_type_summary = dict(
        Counter(format_field_type(field_def) for field_def in object_fields.values())
    )
    metadata_not_in_checklist = sorted(set(object_fields) - set(checklist))
    metadata_not_in_checklist_count = len(metadata_not_in_checklist)
    return {
        "template_name": template_name,
        "object_name": object_name,
        "object_resolution_failed": object_name is None,
        "template_config_object": (
            context.template_definition.object_api_name
            if context and context.template_definition
            else None
        ),
        "metadata_available": context.metadata_available if context else False,
        "adapter_raw_field_count": adapter_raw_count,
        "catalog_field_count": len(options),
        "dropdown_field_count": len(options),
        "checklist_field_count": len(checklist),
        "checklist_fields_found": checklist_found,
        "checklist_fields_found_count": len(checklist_found),
        "checklist_fields_missing": missing_checklist,
        "metadata_fields_not_in_checklist": metadata_not_in_checklist,
        "metadata_fields_not_in_checklist_count": metadata_not_in_checklist_count,
        "removed_by_filtering": [
            {"api_name": field_name, "reason": "Present in adapter output but filtered from catalog"}
            for field_name in filtered_from_ui
        ],
        "filtering_rules_applied": [
            "No Template_Config limiting applied to available fields.",
            "No lookup/reference exclusion applied.",
            "No custom-field-only filtering applied.",
            "No createable/updateable metadata filtering applied; writeability is labeled only.",
            "Standard system fields and address components are supplemented when absent from field-meta.xml.",
        ],
        "template_config_limits_dropdown": False,
        "lookup_fields_excluded": False,
        "missing_checklist_fields": missing_checklist,
        "invalid_xml_fields": invalid_xml_fields,
        "possible_spelling_mismatches": spelling_mismatches,
        "verification_mismatches": verification_mismatches,
        "picklist_fields_discovered": picklist_fields,
        "lookup_fields_discovered": lookup_fields,
        "date_fields_discovered": date_fields,
        "boolean_fields_discovered": boolean_fields,
        "external_id_fields_discovered": external_id_fields,
        "special_validation_hints": special_validation_hints,
        "field_type_summary": field_type_summary,
        "duplicate_api_names": duplicates,
        "fields_with_missing_labels": missing_labels[:25],
        "fields_with_unknown_types": unknown_types[:25],
        "sample_fields": [option.display_label for option in options[:12]],
    }


def _discover_invalid_xml_fields(
    adapter,
    object_name: str | None,
    missing_checklist: list[str],
) -> list[dict[str, str]]:
    if not object_name:
        return []
    invalid: list[dict[str, str]] = []
    for field_name in missing_checklist:
        marker = f"/objects/{object_name}/fields/{field_name}.field-meta.xml"
        for skipped in adapter.skipped_files:
            normalized = skipped.replace("\\", "/")
            if marker in normalized:
                message = FREQUENCY_FIELD_INVALID_XML_MESSAGE if field_name == "Frequency__c" else (
                    f"{field_name} exists in the verification catalog, but its local metadata "
                    "file could not be parsed. Manual verification is required."
                )
                invalid.append({
                    "api_name": field_name,
                    "skipped_file": skipped,
                    "message": message,
                })
                break
    return invalid


def _find_spelling_mismatches(
    missing_fields: list[str],
    available_fields: set[str],
) -> dict[str, list[str]]:
    matches: dict[str, list[str]] = {}
    available = sorted(available_fields)
    for field_name in missing_fields:
        close = get_close_matches(field_name, available, n=3, cutoff=0.75)
        if close:
            matches[field_name] = close
    return matches


def _build_verification_mismatches(
    *,
    checklist: tuple[str, ...],
    object_fields: dict[str, FieldDefinition],
    raw_fields: dict[str, FieldDefinition],
    invalid_xml_fields: list[dict[str, str]],
    spelling_mismatches: dict[str, list[str]],
    object_resolution_failed: bool,
) -> list[dict[str, Any]]:
    invalid_by_name = {item["api_name"]: item for item in invalid_xml_fields}
    mismatches: list[dict[str, Any]] = []

    if object_resolution_failed:
        for field_name in checklist:
            mismatches.append({
                "field": field_name,
                "classification": "Object resolution failed",
                "detail": "Template could not be resolved to a Salesforce object.",
            })
        return mismatches

    for field_name in checklist:
        if field_name in object_fields:
            mismatches.append({
                "field": field_name,
                "classification": "Found in metadata",
                "detail": format_field_type(object_fields[field_name]),
            })
            continue
        if field_name in invalid_by_name:
            mismatches.append({
                "field": field_name,
                "classification": "Invalid XML",
                "detail": invalid_by_name[field_name]["message"],
            })
            continue
        if field_name in raw_fields and field_name not in object_fields:
            mismatches.append({
                "field": field_name,
                "classification": "Present but filtered from UI",
                "detail": "Field exists in adapter output but is absent from the Workbench catalog.",
            })
            continue
        if field_name in spelling_mismatches:
            suggestions = ", ".join(spelling_mismatches[field_name])
            mismatches.append({
                "field": field_name,
                "classification": "Possible spelling mismatch",
                "detail": f"Not found. Similar metadata fields: {suggestions}",
            })
            continue
        mismatches.append({
            "field": field_name,
            "classification": "Missing from metadata",
            "detail": "Field not found in adapter.get_object_fields() for the resolved object.",
        })
    return mismatches


def _discover_picklist_fields(
    object_name: str | None,
    object_fields: dict[str, FieldDefinition],
    adapter,
) -> list[dict[str, Any]]:
    if not object_name:
        return []

    picklist_catalog = {
        field["field_api_name"]: field
        for field in get_picklist_fields(object_name, adapter=adapter)
    }
    discovered: list[dict[str, Any]] = []
    for api_name, field_def in sorted(object_fields.items(), key=lambda item: item[0].lower()):
        if not field_def.is_picklist:
            continue
        catalog_entry = picklist_catalog.get(api_name, {})
        discovered.append({
            "api_name": api_name,
            "label": field_def.label,
            "field_type": format_field_type(field_def),
            "value_set_source": catalog_entry.get("value_set_source"),
            "value_set_name": catalog_entry.get("value_set_name"),
            "allowed_value_count": len(catalog_entry.get("allowed_values", [])),
            "allowed_values_sample": list(catalog_entry.get("allowed_values", []))[:8],
            "metadata_available": catalog_entry.get("metadata_available", False),
        })
    return discovered


def _discover_lookup_fields(
    object_fields: dict[str, FieldDefinition],
) -> list[dict[str, str]]:
    lookup_types = {"lookup", "reference", "masterdetail", "hierarchy"}
    discovered: list[dict[str, str]] = []
    for api_name, field_def in sorted(object_fields.items(), key=lambda item: item[0].lower()):
        if field_def.field_type.lower() not in lookup_types:
            continue
        discovered.append({
            "api_name": api_name,
            "label": field_def.label,
            "field_type": format_field_type(field_def),
            "reference_to": field_def.reference_to or "Unknown",
        })
    return discovered


def _discover_typed_fields(
    object_fields: dict[str, FieldDefinition],
    field_types: set[str],
) -> list[dict[str, str]]:
    discovered: list[dict[str, str]] = []
    for api_name, field_def in sorted(object_fields.items(), key=lambda item: item[0].lower()):
        if field_def.field_type.lower() not in field_types:
            continue
        discovered.append({
            "api_name": api_name,
            "label": field_def.label,
            "field_type": format_field_type(field_def),
        })
    return discovered


def _discover_special_validation_hints(
    object_fields: dict[str, FieldDefinition],
) -> list[dict[str, str]]:
    lookup_types = {"lookup", "reference", "masterdetail", "hierarchy"}
    hints: list[dict[str, str]] = []
    for api_name, field_def in sorted(object_fields.items(), key=lambda item: item[0].lower()):
        lowered = field_def.field_type.lower()
        if field_def.is_picklist:
            hints.append({
                "api_name": api_name,
                "validation_type": "picklist",
                "hint": "Validate allowed values from metadata",
            })
        elif lowered in {"date", "datetime"}:
            hints.append({
                "api_name": api_name,
                "validation_type": "date",
                "hint": "Convert by target upload tool",
            })
        elif lowered in {"boolean", "checkbox"}:
            hints.append({
                "api_name": api_name,
                "validation_type": "boolean",
                "hint": "Normalize TRUE/FALSE",
            })
        elif lowered == "phone":
            hints.append({
                "api_name": api_name,
                "validation_type": "phone",
                "hint": "Preserve formatting",
            })
        elif lowered == "email":
            hints.append({
                "api_name": api_name,
                "validation_type": "email",
                "hint": "Validate format",
            })
        elif lowered == "url":
            hints.append({
                "api_name": api_name,
                "validation_type": "url",
                "hint": "Validate format",
            })
        elif field_def.is_external_id_field:
            hints.append({
                "api_name": api_name,
                "validation_type": "external_id",
                "hint": "Preserve as text; detect duplicates",
            })
        elif lowered in {"currency", "double", "int", "percent", "number"}:
            hints.append({
                "api_name": api_name,
                "validation_type": "numeric",
                "hint": "Numeric validation",
            })
        elif lowered in lookup_types:
            target = field_def.reference_to or "Unknown"
            hints.append({
                "api_name": api_name,
                "validation_type": "lookup",
                "hint": f"Reference {target}; do not invent IDs",
            })
    return hints


def _build_field_option(field_def: FieldDefinition) -> WorkbenchFieldOption:
    type_label = format_field_type(field_def)
    display_label = f"{field_def.api_name} — {field_def.label} — {type_label}"
    search_text = " ".join(
        filter(
            None,
            [
                field_def.api_name.lower(),
                field_def.label.lower(),
                normalize_header_for_matching(field_def.api_name),
                normalize_header_for_matching(field_def.label),
                " ".join(sorted(tokenize_header(field_def.api_name))),
                " ".join(sorted(tokenize_header(field_def.label))),
                field_def.reference_to.lower() if field_def.reference_to else "",
                type_label.lower(),
            ],
        )
    )
    return WorkbenchFieldOption(
        api_name=field_def.api_name,
        label=field_def.label,
        field_type=field_def.field_type,
        display_label=display_label,
        writeability=field_def.writeability,
        reference_to=field_def.reference_to,
        search_text=search_text,
    )


def format_field_type(field_def: FieldDefinition) -> str:
    field_type = field_def.field_type or "Unknown"
    lowered = field_type.lower()
    if lowered in {"lookup", "reference", "masterdetail"}:
        target = field_def.reference_to or "Unknown"
        return f"Lookup({target})"
    if lowered == "hierarchy":
        target = field_def.reference_to or "Account"
        return f"Lookup({target})"
    if lowered == "picklist":
        return "Picklist"
    if lowered == "multipicklist":
        return "MultiPicklist"
    if lowered in {"textarea", "text area"}:
        return "Text"
    if lowered in {"longtextarea", "long text area"}:
        return "Long Text"
    if lowered in {"string", "text"}:
        return "Text"
    if lowered in {"boolean", "checkbox"}:
        return "Boolean"
    if lowered == "double":
        return "Number"
    if lowered == "int":
        return "Number"
    if lowered == "phone":
        return "Phone"
    if lowered == "email":
        return "Email"
    if lowered == "url":
        return "URL"
    if lowered == "currency":
        return "Currency"
    if lowered == "percent":
        return "Percent"
    if lowered == "date":
        return "Date"
    if lowered == "datetime":
        return "DateTime"
    if lowered == "externalid":
        return "External ID"
    return field_type
