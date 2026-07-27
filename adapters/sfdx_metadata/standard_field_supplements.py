"""Supplement object field metadata with standard Salesforce fields missing from SFDX XML."""

from __future__ import annotations

from adapters.sfdx_metadata.models import FieldDefinition

WRITEABILITY_CONFIRMED = "Confirmed writable"
WRITEABILITY_POSSIBLE = "Possibly writable"
WRITEABILITY_READONLY = "Read-only"
WRITEABILITY_UNKNOWN = "Writeability unknown"

ADDRESS_COMPONENTS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "BillingAddress": (
        ("BillingStreet", "Billing Street", "TextArea"),
        ("BillingCity", "Billing City", "Text"),
        ("BillingState", "Billing State/Province", "Text"),
        ("BillingPostalCode", "Billing Zip/Postal Code", "Text"),
        ("BillingCountry", "Billing Country", "Text"),
        ("BillingLatitude", "Billing Latitude", "Double"),
        ("BillingLongitude", "Billing Longitude", "Double"),
        ("BillingGeocodeAccuracy", "Billing Geocode Accuracy", "Picklist"),
    ),
    "ShippingAddress": (
        ("ShippingStreet", "Shipping Street", "TextArea"),
        ("ShippingCity", "Shipping City", "Text"),
        ("ShippingState", "Shipping State/Province", "Text"),
        ("ShippingPostalCode", "Shipping Zip/Postal Code", "Text"),
        ("ShippingCountry", "Shipping Country", "Text"),
        ("ShippingLatitude", "Shipping Latitude", "Double"),
        ("ShippingLongitude", "Shipping Longitude", "Double"),
        ("ShippingGeocodeAccuracy", "Shipping Geocode Accuracy", "Picklist"),
    ),
    "MailingAddress": (
        ("MailingStreet", "Mailing Street", "TextArea"),
        ("MailingCity", "Mailing City", "Text"),
        ("MailingState", "Mailing State/Province", "Text"),
        ("MailingPostalCode", "Mailing Zip/Postal Code", "Text"),
        ("MailingCountry", "Mailing Country", "Text"),
        ("MailingLatitude", "Mailing Latitude", "Double"),
        ("MailingLongitude", "Mailing Longitude", "Double"),
        ("MailingGeocodeAccuracy", "Mailing Geocode Accuracy", "Picklist"),
    ),
}

OBJECT_ADDRESS_COMPOUNDS: dict[str, tuple[str, ...]] = {
    "Account": ("BillingAddress", "ShippingAddress"),
    "Contact": ("MailingAddress",),
    "Contract": ("BillingAddress", "ShippingAddress"),
    "Order": ("BillingAddress", "ShippingAddress"),
}


READ_ONLY_FIELD_NAMES = {
    "CreatedDate",
    "CreatedById",
    "LastModifiedDate",
    "LastModifiedById",
    "SystemModstamp",
    "IsDeleted",
    "LastViewedDate",
    "LastReferencedDate",
    "LastActivityDate",
}


def infer_writeability(api_name: str, field_type: str, load_operation: str | None = None) -> str:
    if api_name in READ_ONLY_FIELD_NAMES or field_type.lower() in {"formula", "autonumber"}:
        return WRITEABILITY_READONLY
    if api_name == "Id":
        return WRITEABILITY_CONFIRMED if load_operation == "Update" else WRITEABILITY_READONLY
    if field_type.lower() in {"lookup", "reference", "hierarchy", "masterdetail"}:
        return WRITEABILITY_POSSIBLE
    if field_type.lower() in {
        "string", "textarea", "phone", "email", "url", "picklist", "multipicklist",
        "double", "currency", "percent", "date", "datetime", "boolean", "int", "id",
        "text", "textarea", "longtextarea", "checkbox",
    }:
        return WRITEABILITY_POSSIBLE
    return WRITEABILITY_UNKNOWN


def _std(
    api_name: str,
    label: str,
    field_type: str,
    *,
    reference_to: str | None = None,
    required: bool = False,
    external_id: bool = False,
    unique: bool = False,
    id_lookup: bool = False,
) -> FieldDefinition:
    return FieldDefinition(
        api_name=api_name,
        label=label,
        field_type=field_type,
        required=required,
        reference_to=reference_to,
        external_id=external_id,
        unique=unique,
        id_lookup=id_lookup,
    )


_CUSTOM_OBJECT_CORE_SYSTEM_FIELDS: dict[str, FieldDefinition] = {
    "Id": _std("Id", "Record ID", "Id"),
    "Name": _std("Name", "Name", "Text"),
    "OwnerId": _std("OwnerId", "Owner", "Reference", reference_to="User"),
    "RecordTypeId": _std("RecordTypeId", "Record Type ID", "Reference", reference_to="RecordType"),
    "CurrencyIsoCode": _std("CurrencyIsoCode", "Currency ISO Code", "Picklist"),
}

STANDARD_OBJECT_FIELDS: dict[str, dict[str, FieldDefinition]] = {
    "Assortment": {
        "Name": _std("Name", "Name", "Text"),
        "OwnerId": _std("OwnerId", "Owner", "Reference", reference_to="User"),
        "CurrencyIsoCode": _std("CurrencyIsoCode", "Currency ISO Code", "Picklist"),
        "Description": _std("Description", "Description", "TextArea"),
    },
    "AssortmentProduct": {
        "AssortmentId": _std("AssortmentId", "Assortment ID", "Reference", reference_to="Assortment"),
        "DefaultOrderQuantity": _std("DefaultOrderQuantity", "Default Order Quantity", "Double"),
        "IsFavorite": _std("IsFavorite", "Favorite", "Boolean"),
        "CurrencyIsoCode": _std("CurrencyIsoCode", "Currency ISO Code", "Picklist"),
    },
    "Contact": {
        "AccountId": _std("AccountId", "Account ID", "Reference", reference_to="Account"),
        "BuyerAttributes": _std("BuyerAttributes", "Buyer Attributes", "Picklist"),
        "ContactSource": _std("ContactSource", "Creation Source", "Picklist"),
        "CurrencyIsoCode": _std("CurrencyIsoCode", "Currency ISO Code", "Picklist"),
        "Department": _std("Department", "Department", "Text"),
        "DepartmentGroup": _std("DepartmentGroup", "Department Group", "Picklist"),
        "Email": _std("Email", "Email", "Email"),
        "EmailBouncedDate": _std("EmailBouncedDate", "Email Bounced Date", "DateTime"),
        "EmailBouncedReason": _std("EmailBouncedReason", "Email Bounced Reason", "Text"),
        "Fax": _std("Fax", "Business Fax", "Phone"),
        "FirstName": _std("FirstName", "First Name", "Text"),
        "Jigsaw": _std("Jigsaw", "Data.com Key", "Text"),
        "LastName": _std("LastName", "Last Name", "Text", required=True),
        "MiddleName": _std("MiddleName", "Middle Name", "Text"),
        "MobilePhone": _std("MobilePhone", "Mobile Phone", "Phone"),
        "OwnerId": _std("OwnerId", "Owner", "Reference", reference_to="User"),
        "Phone": _std("Phone", "Business Phone", "Phone"),
        "ReportsToId": _std("ReportsToId", "Reports To ID", "Reference", reference_to="Contact"),
        "Salutation": _std("Salutation", "Salutation", "Picklist"),
        "Suffix": _std("Suffix", "Suffix", "Text"),
        "Title": _std("Title", "Title", "Text"),
        "TitleType": _std("TitleType", "Seniority Level", "Picklist"),
    },
    "Contract": {
        "AccountId": _std("AccountId", "Account ID", "Reference", reference_to="Account"),
        "CompanySignedDate": _std("CompanySignedDate", "Company Signed Date", "Date"),
        "CompanySignedId": _std("CompanySignedId", "Company Signed By", "Reference", reference_to="User"),
        "ContractTerm": _std("ContractTerm", "Contract Term (months)", "Int"),
        "CurrencyIsoCode": _std("CurrencyIsoCode", "Currency ISO Code", "Picklist"),
        "CustomerSignedDate": _std("CustomerSignedDate", "Customer Signed Date", "Date"),
        "CustomerSignedId": _std("CustomerSignedId", "Customer Signed By", "Reference", reference_to="Contact"),
        "CustomerSignedTitle": _std("CustomerSignedTitle", "Customer Signed Title", "Text"),
        "Description": _std("Description", "Description", "TextArea"),
        "Name": _std("Name", "Contract Name", "Text"),
        "OwnerExpirationNotice": _std("OwnerExpirationNotice", "Owner Expiration Notice", "Picklist"),
        "OwnerId": _std("OwnerId", "Owner", "Reference", reference_to="User"),
        "Pricebook2Id": _std("Pricebook2Id", "Price Book ID", "Reference", reference_to="Pricebook2"),
        "SpecialTerms": _std("SpecialTerms", "Special Terms", "TextArea"),
        "StartDate": _std("StartDate", "Contract Start Date", "Date"),
        "Status": _std("Status", "Status", "Picklist"),
    },
    "Order": {
        "AccountId": _std("AccountId", "Account ID", "Reference", reference_to="Account"),
        "BillToContactId": _std("BillToContactId", "Bill To Contact ID", "Reference", reference_to="Contact"),
        "CompanyAuthorizedById": _std("CompanyAuthorizedById", "Company Authorized By", "Reference", reference_to="User"),
        "CompanyAuthorizedDate": _std("CompanyAuthorizedDate", "Company Authorized Date", "Date"),
        "ContractId": _std("ContractId", "Contract ID", "Reference", reference_to="Contract"),
        "CurrencyIsoCode": _std("CurrencyIsoCode", "Currency ISO Code", "Picklist"),
        "CustomerAuthorizedById": _std("CustomerAuthorizedById", "Customer Authorized By", "Reference", reference_to="Contact"),
        "CustomerAuthorizedDate": _std("CustomerAuthorizedDate", "Customer Authorized Date", "Date"),
        "Description": _std("Description", "Description", "TextArea"),
        "EffectiveDate": _std("EffectiveDate", "Order Start Date", "Date", required=True),
        "EndDate": _std("EndDate", "Order End Date", "Date"),
        "IsReductionOrder": _std("IsReductionOrder", "Reduction Order", "Boolean"),
        "Name": _std("Name", "Order Name", "Text"),
        "OrderReferenceNumber": _std("OrderReferenceNumber", "Order Reference Number", "Text"),
        "OriginalOrderId": _std("OriginalOrderId", "Original Order ID", "Reference", reference_to="Order"),
        "OwnerId": _std("OwnerId", "Owner", "Reference", reference_to="User"),
        "PoDate": _std("PoDate", "PO Date", "Date"),
        "PoNumber": _std("PoNumber", "PO Number", "Text"),
        "Pricebook2Id": _std("Pricebook2Id", "Price Book ID", "Reference", reference_to="Pricebook2"),
        "ShipToContactId": _std("ShipToContactId", "Ship To Contact ID", "Reference", reference_to="Contact"),
        "Status": _std("Status", "Status", "Picklist"),
    },
    "OrderItem": {
        "Description": _std("Description", "Line Description", "TextArea"),
        "EndDate": _std("EndDate", "End Date", "Date"),
        "OrderId": _std("OrderId", "Order ID", "Reference", reference_to="Order", required=True),
        "OriginalOrderItemId": _std("OriginalOrderItemId", "Original Order Item ID", "Reference", reference_to="OrderItem"),
        "PricebookEntryId": _std("PricebookEntryId", "Price Book Entry ID", "Reference", reference_to="PricebookEntry", required=True),
        "Product2Id": _std("Product2Id", "Product ID", "Reference", reference_to="Product2"),
        "Quantity": _std("Quantity", "Quantity", "Double", required=True),
        "ServiceDate": _std("ServiceDate", "Line Item Start Date", "Date"),
        "UnitPrice": _std("UnitPrice", "Unit Price", "Currency"),
    },
    "Product2": {
        "AvailabilityDate": _std("AvailabilityDate", "Availability Date", "Date"),
        "BasedOnId": _std("BasedOnId", "Based On ID", "Reference", reference_to="Product2"),
        "ConfigureDuringSale": _std("ConfigureDuringSale", "Configure During Sale", "Picklist"),
        "CurrencyIsoCode": _std("CurrencyIsoCode", "Currency ISO Code", "Picklist"),
        "Description": _std("Description", "Product Description", "TextArea"),
        "DiscontinuedDate": _std("DiscontinuedDate", "Discontinued Date", "Date"),
        "DisplayUrl": _std("DisplayUrl", "Display URL", "URL"),
        "EndOfLifeDate": _std("EndOfLifeDate", "End Of Life Date", "Date"),
        "ExternalDataSourceId": _std(
            "ExternalDataSourceId", "External Data Source ID", "Reference", reference_to="ExternalDataSource",
        ),
        "ExternalId": _std("ExternalId", "External ID", "Text", external_id=True),
        "Family": _std("Family", "Product Family", "Picklist"),
        "HelpText": _std("HelpText", "Help Text", "LongTextArea"),
        "IsActive": _std("IsActive", "Active", "Boolean"),
        "IsAssetizable": _std("IsAssetizable", "Assetizable", "Boolean"),
        "IsSoldOnlyWithOtherProds": _std("IsSoldOnlyWithOtherProds", "Sold Only With Other Products", "Boolean"),
        "Name": _std("Name", "Product Name", "Text"),
        "ProductCode": _std("ProductCode", "Product Code", "Text"),
        "QuantityUnitOfMeasure": _std("QuantityUnitOfMeasure", "Quantity Unit Of Measure", "Picklist"),
        "StockKeepingUnit": _std("StockKeepingUnit", "Product SKU", "Text"),
        "Type": _std("Type", "Product Type", "Picklist"),
        "UsedFor": _std("UsedFor", "Used For", "Picklist"),
    },
    "Promotion": {
        "CampaignId": _std("CampaignId", "Campaign ID", "Reference", reference_to="Campaign"),
        "Category": _std("Category", "Category", "Picklist"),
        "CurrencyIsoCode": _std("CurrencyIsoCode", "Currency ISO Code", "Picklist"),
        "Description": _std("Description", "Description", "TextArea"),
        "EndDate": _std("EndDate", "End Date", "Date"),
        "IsActive": _std("IsActive", "Active", "Boolean"),
        "Level": _std("Level", "Level", "Picklist"),
        "Methods": _std("Methods", "Methods", "MultiPicklist"),
        "Name": _std("Name", "Promotion Name", "Text"),
        "Objective": _std("Objective", "Objective", "Picklist"),
        "OwnerId": _std("OwnerId", "Owner", "Reference", reference_to="User"),
        "StartDate": _std("StartDate", "Start Date", "Date"),
    },
}

SYSTEM_FIELDS: dict[str, dict[str, FieldDefinition]] = {
    "Account": {
        "Id": _std("Id", "Record ID", "Id"),
        "RecordTypeId": _std("RecordTypeId", "Record Type ID", "Reference", reference_to="RecordType"),
        "CurrencyIsoCode": _std("CurrencyIsoCode", "Account Currency", "Picklist"),
    },
    "Account_Relationship__c": {
        **_CUSTOM_OBJECT_CORE_SYSTEM_FIELDS,
        "Name": _std("Name", "Account Relationship Name", "AutoNumber"),
    },
    "Product2": {
        "Id": _std("Id", "Record ID", "Id"),
    },
    "Promotion": {
        "Id": _std("Id", "Record ID", "Id"),
    },
}


def _copy_field_def(
    field_def: FieldDefinition,
    *,
    writeability: str | None = None,
) -> FieldDefinition:
    return FieldDefinition(
        api_name=field_def.api_name,
        label=field_def.label,
        field_type=field_def.field_type,
        required=field_def.required,
        global_value_set=field_def.global_value_set,
        standard_value_set=field_def.standard_value_set,
        inline_picklist_values=field_def.inline_picklist_values,
        reference_to=field_def.reference_to,
        writeability=writeability or field_def.writeability,
        external_id=field_def.external_id,
        unique=field_def.unique,
        id_lookup=field_def.id_lookup,
    )


def supplement_object_fields(
    object_name: str,
    field_map: dict[str, FieldDefinition],
    load_operation: str | None = None,
) -> dict[str, FieldDefinition]:
    """Add compound-address components and core system fields not present as field-meta.xml."""
    supplemented = dict(field_map)

    compounds = OBJECT_ADDRESS_COMPOUNDS.get(object_name, ())
    for compound_name in compounds:
        components = ADDRESS_COMPONENTS.get(compound_name, ())
        for api_name, label, field_type in components:
            if api_name in supplemented:
                continue
            supplemented[api_name] = FieldDefinition(
                api_name=api_name,
                label=label,
                field_type=field_type,
                required=False,
                writeability=infer_writeability(api_name, field_type, load_operation),
            )

    for api_name, field_def in STANDARD_OBJECT_FIELDS.get(object_name, {}).items():
        if api_name not in supplemented:
            supplemented[api_name] = _copy_field_def(
                field_def,
                writeability=infer_writeability(api_name, field_def.field_type, load_operation),
            )

    system_fields = dict(SYSTEM_FIELDS.get(object_name, {}))
    if object_name.endswith("__c") and not system_fields:
        system_fields = dict(_CUSTOM_OBJECT_CORE_SYSTEM_FIELDS)

    for api_name, field_def in system_fields.items():
        if api_name not in supplemented:
            supplemented[api_name] = _copy_field_def(
                field_def,
                writeability=infer_writeability(api_name, field_def.field_type, load_operation),
            )

    for api_name, field_def in list(supplemented.items()):
        if field_def.writeability != WRITEABILITY_UNKNOWN:
            continue
        supplemented[api_name] = _copy_field_def(
            field_def,
            writeability=infer_writeability(api_name, field_def.field_type, load_operation),
        )

    return supplemented
