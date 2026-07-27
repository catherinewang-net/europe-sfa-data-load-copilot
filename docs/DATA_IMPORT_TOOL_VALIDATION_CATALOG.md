# Data Import Tool Validation Catalog

**Project:** Europe SFA Data Load Copilot  
**Audit date:** 26 July 2026  
**EUSFA source repo:** `EUSFA_SFDX_REPO_PATH` (read-only)  
**Primary entry point:** `EUSFA_DataImportValidationService.validateCsvForTemplate()`  
**UI:** `force-app/main/default/lwc/eusfa_dataImportTool/eusfa_dataImportTool.js`

---

## 1. DIT Validation Classes Found

| Class | Object / Template | Role |
|-------|-------------------|------|
| `EUSFA_DataImportValidationService` | All templates | Header/column validation, mandatory blanks, CSV parse, delegates per-template validators |
| `EUSFA_CustomerImportValidationService` | Account / Customers | Row + cross-row validation |
| `EUSFA_ProspectImportValidationService` | Account / Prospects | Row + cross-row validation |
| `EUSFA_PromotionImportValidationService` | Promotion / Retail Promotion | Row validation + live lookups |
| `EUSFA_RouteSalesGeoImportValidator` | Route_Sales_Geo__c / Retail Sales Geo | Hierarchy level, district, market |
| `EUSFA_RoutingImportValidationService` | CTR / Customer to Route | Route, sequence, cross-row rules |
| `EUSFA_ProductImportValidationService` | Product2 / Products | Hierarchy, competitor, duplicates |
| `EUSFA_OrderConfImportValidationSvc` | Order / Order | Order confirmation upload |
| `EUSFA_OrderItemConfImportValidationSvc` | OrderItem / Order Item | Order item confirmation upload |
| `EUSFA_ImportTemplateService` | All | Template CSV generation from `Template_Config__mdt` |

Supporting: `EUSFA_PromotionLookupService` (live Account/Product lookups for promotions).

---

## 2. Template_Config__mdt

Custom metadata type: `Template_Config__mdt`  
Fields: `Object_API_Name__c`, `Template_Label__c`, `Fields__c` (JSON api→label map), `Is_Active__c`.

Copilot mirrors this via `adapters.get_metadata_adapter()` + `reference_templates/data_import_tool/*.csv`.

---

## 3. Validation Catalog (by source class)

### 3.1 EUSFA_DataImportValidationService (generic)

| Template | Field | Condition | Message (summary) | Severity | Copilot? | Copilot file | Gap |
|----------|-------|-----------|-------------------|----------|----------|--------------|-----|
| All | (file) | No base64 CSV | No file provided. | Error | Partial | `core/csv_loader.py` | No pre-upload empty check |
| All | (template) | No object/label | No template selected. | Error | Yes | `engines/template_comparison.py` | — |
| All | (file) | Blank CSV | CSV file appears empty. | Error | Partial | `core/csv_loader.py` | — |
| All | (header) | No header row | CSV file contains no header row. | Error | Yes | `core/csv_loader.py` | — |
| All | Fields__c | Invalid JSON | Invalid JSON in Fields__c | Error | N/A | metadata adapter | — |
| All | (config) | Empty Fields__c | Template configuration contains no fields… | Warning | Yes | template comparison | — |
| All | (extra col) | Column not in template | Column 'X' is not part of the selected template… | Warning | Yes | `engines/template_comparison.py` | — |
| All | (missing col) | Required column absent | Missing required template column(s): … | Error | Yes | `engines/template_comparison.py` | — |
| All | (optional col) | Optional column absent | Template column removed: 'X'… | Warning | Partial | template comparison | Customer/Prospect skip in SF |
| All | * columns | Mandatory blank | Row N: Mandatory field "X" is blank. | Error | Partial | `validators/load_action_validator.py` | DIT uses asterisk headers, not full row scan |
| All | (decode) | Base64 failure | Unable to decode CSV data. | Error | No | — | Not applicable to Copilot upload |
| All | (config) | Config not found | Template configuration not found… | Error | Yes | `services/template_service.py` | — |

### 3.2 EUSFA_CustomerImportValidationService (Customers)

| Field | Condition | Message | Severity | Copilot? | Copilot file | Gap |
|-------|-----------|---------|----------|----------|--------------|-----|
| External Id, Name, L1 Channel, Market | Required empty | Required field(s) empty: … | Error | Partial | picklist/load_action | No unified required-row scan |
| Any string/textarea | Length > max | Field(s) exceed max length: … | Error | Partial | metadata field length | Not all fields |
| Phone | Invalid format | Invalid phone format… | Error | Yes | `validators/phone_validator.py` | — |
| Email | Invalid format | Invalid email format: … | Error | No | — | **Gap** |
| Date fields | Invalid format | Invalid date format (dd/MM/yyyy…) | Error | Yes | `validators/date_validator.py` | — |
| Picklists | Invalid value | Invalid picklist value(s): … | Error | Yes | `validators/picklist_validator.py` | — |
| External Id | Duplicate in file | Duplicate External Id [X] found on rows: … | Error | Yes | `validators/duplicate_key_validator.py` | — |

Address labels: Street→ShippingStreet, City→ShippingCity, Country→ShippingCountry, Postal Code→ShippingPostalCode. No separate street/city split validation in SF.

### 3.3 EUSFA_ProspectImportValidationService (Prospects)

| Field | Condition | Message | Severity | Copilot? | Gap |
|-------|-----------|---------|----------|----------|-----|
| Name, L1 Channel, Market, Currency Code | Required empty | Required field(s) empty: … | Error | Partial | Same as Customers |
| Phone, Email, Date, Picklist, Numeric | Type validation | PROSPECT_ERR_* messages | Error | Partial | Email/numeric gaps |
| External Id | Duplicate | Duplicate External Id [X]… | Error | Yes | — |

Address labels include State (ShippingState).

### 3.4 EUSFA_PromotionImportValidationService (Retail Promotion)

| Field | Condition | Message | Severity | Copilot? | Gap |
|-------|-----------|---------|----------|----------|-----|
| Name, dates, type, market | Required empty | Required field(s) empty: … | Error | Partial | Date ordering rules |
| Retailer + Store Id | Both populated | Provide either Key Account or Account External ID, not both | Error | No | **Gap** |
| Neither key nor seg | All blank | PS Value Segmentation Snacks is required | Error | No | **Gap** |
| Start/End/Influence dates | Bad format | Invalid X Date format. Expected DD/MM/YYYY | Error | Yes | date_validator |
| End ≤ Start | Date order | End Date must be greater than Start Date | Error | No | **Gap** |
| Influence ≥ Start | Date order | Influence Date must be earlier than Start Date | Error | No | **Gap** |
| Promotion Type, L3 Seg | Invalid picklist | Invalid … Valid values: … | Error | Yes | picklist_validator |
| Store Id | Not in SF | Store not found (formatted) | Error | Partial | record_existence (optional live) |
| Retailer | Not in SF | Retailer not found | Error | Partial | — |
| Material Id | Not in SF | Material not found | Error | Partial | — |

### 3.5 EUSFA_RouteSalesGeoImportValidator (Retail Sales Geo)

| Field | Condition | Message | Severity | Copilot? | Gap |
|-------|-----------|---------|----------|----------|-----|
| Hierarchy Level | Not District/Route | Invalid Hierarchy Level [X]… | Error | No | **Gap** |
| District | Blank when Level=Route | District is required when Hierarchy Level is Route | Error | No | **Gap** |
| Market | Invalid picklist | Invalid Market value [X] | Error | Partial | picklist_validator |

### 3.6 EUSFA_RoutingImportValidationService (Customer to Route)

| Condition | Message | Copilot? | Copilot file |
|-----------|---------|----------|--------------|
| Route Id = 0, duplicates, sequences | Various row/cross-row errors | Partial | `validators/routing_validator.py` |

### 3.7 EUSFA_ProductImportValidationService (Products)

| Condition | Message | Copilot? | Gap |
|-----------|---------|----------|-----|
| Mandatory fields by hierarchy | Required field(s) empty / Competitor rules | Partial | Product hierarchy rules |
| Duplicate External Id | Duplicate External Id within CSV | Partial | duplicate_key_validator |
| Competitor name/level | Product Name must contain "competitor"… | No | **Gap** |
| EAN Code | Maps to Product2.EAN__c | Partial | **New** `validators/ean_validator.py` |

### 3.8 EUSFA_OrderConfImportValidationSvc / EUSFA_OrderItemConfImportValidationSvc

Order and Order Item confirmation templates — mandatory field and cross-row rules. Copilot: partial via template comparison and date/picklist validators; full parity not implemented.

---

## 4. EAN Fields by Object (from EUSFA metadata)

| Object | API Field | CSV Label (template) | Notes |
|--------|-----------|----------------------|-------|
| Product2 | `EAN__c` | EAN Code | Products template (`PROD_LABEL_EAN`) |
| UoM__c | `EAN_Code__c` | EAN Code | Units of Measure template |
| Account | `GLN__c` | GLN | Customers — GLN not EAN; 13-digit identifier |

Copilot rules: `rules/ean_rules.json` (configurable lengths, optional checksum).

---

## 5. Federation ID Fields

| Object | API Field | In DIT templates? | Notes |
|--------|-----------|-------------------|-------|
| User | `FederationIdentifier` | No | SSO registration (`EUSFAPepEURegHandler`); Copilot rule for values starting with 9 |

Copilot rules: `rules/federation_id_rules.json`.

---

## 6. Address Fields by Object

### Account (Customers template)

| CSV Label | API Field | Role |
|-----------|-----------|------|
| Street | ShippingStreet | Street |
| City | ShippingCity | City |
| Country | ShippingCountry | Country |
| Postal Code | ShippingPostalCode | Postal |

### Account (Prospects template)

| CSV Label | API Field | Role |
|-----------|-----------|------|
| Street | ShippingStreet | Street |
| City | ShippingCity | City |
| State | ShippingState | State/region |
| Country | ShippingCountry | Country |
| Postal Code | ShippingPostalCode | Postal |

### Standard Salesforce address components (metadata)

BillingStreet/City/State/PostalCode/Country, Shipping*, Mailing* — resolved by column name markers in `validators/address_validator.py`.

---

## 7. Live Salesforce Client

| Component | Status |
|-----------|--------|
| `clients/salesforce_client.py` | **Exists** — `EnvSalesforceClient` / `UnavailableSalesforceClient` |
| `services/salesforce_record_lookup_service.py` | **Exists** — batched SOQL lookup |
| EAN live check | **New** — optional via `validators/ean_validator.py` |

When credentials absent: show *"EAN format was checked, but existence in Salesforce was not verified."*

---

## 8. Copilot Coverage Summary

| Area | EUSFA DIT | Copilot before this change | After implementation |
|------|-----------|---------------------------|---------------------|
| CSV structure (field count) | parseCsvLine | Partial | Extended: quotes, line breaks |
| Excel/punctuation | NBSP in headers | Partial (whitespace) | `text_sanitization_validator.py` |
| EAN | Product row rules | Partial (identifier) | `ean_validator.py` + live check |
| Federation ID | Not in DIT | No | `federation_id_validator.py` |
| Address structure | Not in DIT | Partial (whitespace) | Extended address_validator |
| DIT template validators | Full Apex | Partial | Catalog documents gaps |

---

## 9. Files Changed (implementation)

| File | Change |
|------|--------|
| `docs/DATA_IMPORT_TOOL_VALIDATION_CATALOG.md` | Created (this file) |
| `validators/csv_structure_validator.py` | Unclosed quotes, embedded breaks, column shift |
| `validators/text_sanitization_validator.py` | Smart quotes, dashes, NBSP |
| `validators/ean_validator.py` | EAN text, checksum, duplicates, live SF |
| `validators/federation_id_validator.py` | Leading-zero pattern for 9-prefix IDs |
| `validators/address_validator.py` | Street/city/state/postal/country rules |
| `validators/common.py` | Shared punctuation helpers, CSV export quoting |
| `rules/ean_rules.json` | EAN field config |
| `rules/federation_id_rules.json` | Federation ID config |
| `services/row_correction_plan_service.py` | Wire new validators |
| `services/preparation_flow_service.py` | Data Preparation Issues sections |
| `ui/data_preparation_issues.py` | Grouped issue UI |
| `ui/data_preparation_review.py` | Integrate issues section |
| `ui/components.py` | CSV download with QUOTE_MINIMAL |
| `tests/test_dit_validation_rules.py` | 16 scenario tests |

---

## 10. Custom Labels & Flows

Promotion errors use constants in `EUSFA_Constants.cls` (not Custom Labels). Prospect errors use `PROSPECT_ERR_*` constants. No dedicated Flow for validation — LWC calls Apex `@AuraEnabled validateCsvForTemplate`.
