"""Shared constants for metadata-driven validation."""

from __future__ import annotations

MAPPING_SOURCE_SALESFORCE = "Salesforce Template Metadata"
MAPPING_SOURCE_USER = "User Confirmed"
MAPPING_SOURCE_FALLBACK = "Manual Configuration Fallback"
MAPPING_SOURCE_UNMAPPED = "Unmapped"

MAPPING_STATUS_CONFIRMED = "Confirmed"
MAPPING_STATUS_CONFIRMED_METADATA = "Confirmed from Salesforce Metadata"
MAPPING_STATUS_NEEDS_CONFIRMATION = "Needs Confirmation"
MAPPING_STATUS_INVALID = "Invalid Mapping"
MAPPING_STATUS_UNMAPPED = "Unmapped"
MAPPING_STATUS_EXCLUDED = "Do Not Include"
MAPPING_STATUS_EXACT_API = "Exact API Header"
MAPPING_STATUS_UNRESOLVED = "Unresolved"

MAPPING_ACTION_MAP = "map"
MAPPING_ACTION_KEEP = "keep"
MAPPING_ACTION_EXCLUDE = "exclude"

FORBIDDEN_CSV_HEADERS = {
    "UNCONFIRMED",
    "NEEDS_CONFIRMATION",
    "UNMAPPED",
    "DO_NOT_INCLUDE",
    "UNKNOWN",
    "PLACEHOLDER",
}

ACCOUNT_TEMPLATE_TYPE_VALUES: dict[str, str] = {
    "Customers": "Customer",
    "Wholesalers": "Wholesaler",
    "Prospects": "Prospect",
    "Payers": "Payer",
    "Key Account": "Key Account",
}

ACCOUNT_TEMPLATE_RECORD_TYPES: dict[str, str | None] = {
    "Customers": "Customer",
    "Wholesalers": "Wholesaler",
    "Prospects": "Prospect",
    "Payers": "Payer",
    "Key Account": None,
}

PICKLIST_STATUS_VALID = "Valid"
PICKLIST_STATUS_INVALID = "Invalid Picklist Value"
PICKLIST_STATUS_BLANK_REQUIRED = "Blank Required Value"
PICKLIST_STATUS_METADATA_UNAVAILABLE = "Metadata Unavailable"
PICKLIST_STATUS_RECORD_TYPE_FALLBACK = "Record Type Fallback Used"
PICKLIST_STATUS_MULTI_INVALID = "Multipicklist Value Invalid"
PICKLIST_STATUS_WHITESPACE_CLEANUP = "Whitespace Cleanup Suggested"
PICKLIST_STATUS_NEEDS_REVIEW = "Needs Review"
PICKLIST_STATUS_NEEDS_USER_ACTION = "Needs User Action"
PICKLIST_METADATA_SOURCE_LOCAL = "local"

RECORD_CHECK_NOT_EVALUATED = "Not Evaluated"
RECORD_CHECK_SKIPPED = "Live Check Skipped"
RECORD_CHECK_UNAVAILABLE = "Live Salesforce Check Unavailable"
RECORD_CHECK_POSSIBLE_EXISTING = "Possible Existing Record"
RECORD_CHECK_NEW_IDENTIFIER = "New Identifier"
RECORD_CHECK_FOUND = "Existing Record Found"
RECORD_CHECK_NOT_FOUND = "Record Not Found"
RECORD_CHECK_DUPLICATE_MATCH = "Duplicate Match"

LOOKUP_STATUS_VALID = "Valid Lookup"
LOOKUP_STATUS_NEEDS_REVIEW = "Needs Review"
LOOKUP_STATUS_NOT_FOUND = "Record Not Found"
LOOKUP_STATUS_MULTIPLE = "Multiple Matches"
LOOKUP_STATUS_NOT_CHECKED = "Not Checked"
LOOKUP_STATUS_PARENT_FIRST = "Parent Must Be Loaded First"

LOOKUP_METHOD_SALESFORCE_ID = "Salesforce Id"
LOOKUP_METHOD_EXTERNAL_ID = "External ID"
LOOKUP_METHOD_BUSINESS_KEY = "Business Key"
LOOKUP_METHOD_NAME = "Name-based"
LOOKUP_METHOD_COMPOSITE = "Composite Key"
LOOKUP_METHOD_UNKNOWN = "Unknown"

PREREQ_STATUS_ALREADY_LOADED = "Already loaded"
PREREQ_STATUS_INCLUDED = "Included in this deployment"
PREREQ_STATUS_NOT_LOADED = "Not loaded"
PREREQ_STATUS_UNKNOWN = "Unknown"
