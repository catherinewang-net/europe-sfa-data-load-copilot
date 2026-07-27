# DIT Lessons Learned Audit

**Project:** Europe SFA Data Load Copilot  
**Audit date:** 23 July 2026  
**Scope:** Data Import Tool (DIT) workflow only — read-only codebase review against lessons-learned CSV  
**Source lessons file:** `R1 Mock TCO - Lessons Learned(FINAL - Improvement Areas ) (1).csv`  
**Prior gap analysis:** `docs/COPILOT_FEATURE_AUDIT.md`  
**Methodology:** Traced active DIT path in `app.py` (`upload_method == "Data Import Tool"`); verified connection to `corrected_df`, readiness, and download; did not mark **Fully Covered** without evidence across UI → corrected_df → readiness → download → tests.

---

## DIT Workflow Trace (Source of Truth)

| Step | DIT behaviour | Primary implementation |
|------|---------------|----------------------|
| 1 Select DIT | Upload method selector | `app.py`, `core/config.py` |
| 2 Select fixed DIT template | Template dropdown | `core/reference_templates.py`, `services/template_service.py` |
| 3 Upload CSV | UTF-8 load, blank-header filter | `core/csv_loader.py` |
| 4 Compare to exact template | Header match, order, missing/extra | `engines/template_comparison.py` → `compare_to_reference()` |
| 5 Prepare headers | User approves rename/reorder/add/exclude | `ui/prepare_file.py`, `services/correction_plan_service.py`, `services/data_import_preparation_service.py` |
| 6 Validate every retained row | Row plan + validation bundle | `services/row_correction_plan_service.py`, `engines/validation_engine.py` |
| 7 Propose safe corrections | Safe + confirmation issues | `services/row_correction_plan_service.py` |
| 8 User approval | Data Preparation Review | `ui/data_preparation_review.py` |
| 9 Apply to corrected_df | Non-mutating copy | `services/file_preparation_service.py` → `prepare_file()` |
| 10 Revalidate corrected_df | Post-apply validation | `services/revalidation_service.py` |
| 11 Show readiness | Phase-aware readiness panel | `services/preparation_flow_service.py` → `evaluate_preparation_readiness()` |
| 12 Download DIT-ready CSV | Friendly headers, UTF-8 CSV | `ui/components.py` → `render_preparation_results()` |

**DIT output requirements checked:**
- Friendly headers / column order: **Yes** — enforced via DIT reference templates + correction plan (`reference_templates/data_import_tool/*.csv`)
- Asterisk required fields: **Partial** — template comparison + `required_csv_labels` in Template_Config
- DD/MM/YYYY dates: **Yes** — `services/date_conversion_service.py`, `ui/date_format_review.py`
- External IDs as text: **Partial** — `validators/identifier_validator.py` (leading zero / sci-notation detect; no auto-fix for blocking sci-notation)
- UTF-8 download: **Yes** — `corrected_df.to_csv()` (no API names in output columns)
- No blocking errors when READY: **Partial** — download gate in `app.py` lines 360–362 checks only `manual_review` + `date_unresolved`; **does not** check `picklist_validation.has_blocking_issues`

**Metadata source of truth:** `adapters.get_metadata_adapter()` via `services/template_service.py` + Template_Config / SFDX metadata.

---

## A. Lessons Learned Coverage Matrix

Full matrix (62 non-header source records, rows 2–63): **`docs/DIT_LESSONS_LEARNED_COVERAGE.csv`**

Row numbers = 1-based CSV record index (header = row 1). Multiline cells in the source file (e.g. row 22 Customers, row 51 Non-Object) count as single records.

### DIT-relevant records (summary table)

| Row | Category | Issue (abbrev.) | Coverage status | Priority |
|-----|----------|-----------------|-----------------|----------|
| 22 | Customers | Addresses, commas, Key Account deps, picklists, External ID, GTM, Type column | **Partially Covered** | P1 |
| 23 | Route Sales Geo | No learning recorded | **Needs Clarification** | P3 |
| 24 | Prospects | Commas in fields; slow multi-file loads | **Partially Covered** | P2 |
| 27 | Customer To Route | File splitting; duplicate route+sequence | **Partially Covered** | P1 |
| 28 | Routing Import | Route ID=0; past dates; overlaps | **Partially Covered** | P1 |
| 29 | Account Relationship | Must reference existing accounts/customers | **Not Covered** | P1 |
| 33 | Key Accounts | Market-specific naming; address commas | **Partially Covered** | P2 |
| 41 | Contracts | Picklists, dates, SAP codes, active customers | **Partially Covered** | P1 |
| 42 | Product Hierarchies | Load-order dependency (Pepsi before competitors) | **Not Covered** | P1 |
| 43 | Products | Picklists; currency symbols | **Partially Covered** | P1 |
| 44 | Wholesalers | Bad data only found post-load | **Partially Covered** | P2 |
| 47 | Assortment Products | Cross-template match; 40-char limit; SKU rules | **Not Covered** | P1 |
| 49 | Retail Promotions | Merged rows; missing products; comma multi-values | **Partially Covered** | P1 |
| 51 | Non-Object specific | Template compliance; picklists; upload-only failures | **Partially Covered** | P1 |

### Coverage area mapping (A–L) for DIT-relevant lessons

| Area | Row(s) | DIT status |
|------|--------|------------|
| A Template/header readiness | 22, 51 | **Partial** — strong header compare; Type not in DIT Customers template |
| B Row formatting / whitespace | 22, 24, 33 | **Partial** — phone/address/whitespace validators active; general column trim limited |
| C Dates | 22, 28, 41 | **Partial** — DD/MM/YYYY conversion strong; no routing past-date business rule |
| D Identifiers / External IDs | 22, 27 | **Partial** — duplicate External ID; no market-composite key |
| E Picklists | 22, 41, 43, 51 | **Partial** — validation runs but DIT mapping + correction UI gaps |
| F Booleans | — | **Partial** — generic validator connected |
| G Numeric / currency | 43 | **Partial** — detect/block; limited safe conversion |
| H Phone / address | 22, 33 | **Partial** — trim/line-break; comma-in-field detect-only |
| I CSV structure | 22, 24, 33 | **Partial** — field-count mismatch; no quote repair |
| J Required fields | 22, 41 | **Partial** — template required headers; load-action N/A for DIT |
| K Dependencies / lookups | 22, 29, 41, 42, 47, 49 | **Not Covered** — `dependency_checker.py` stub |
| L User approval / corrected output | All relevant | **Partial** — row corrections work; picklist corrections Workbench-only |

### Picklist-specific DIT check (required)

| Requirement | Status | Evidence |
|-------------|--------|----------|
| API field from template metadata | **Gap** | `build_dit_mapping_rows()` sets `confirmed_api_field` = friendly column name, not API name from `csv_label_to_api` |
| Metadata type check | **Partial** | `validate_picklists()` skips fields when API lookup fails |
| Stored API values from adapter | **Yes** | `adapters.get_metadata_adapter().get_picklist_value_details()` |
| Not label-only | **Yes** | Validator compares API values |
| Record-type restrictions | **Yes** | `has_record_type_picklist_restriction()` in `validators/picklist_validator.py` |
| DIT UI for corrections | **No** | `render_picklist_validation()` only in Workbench branch (`app.py` ~474–496) |
| Applied to corrected_df | **No** | `apply_picklist_corrections()` not called on DIT path |
| Blocks download when invalid | **Inconsistent** | `evaluate_preparation_readiness()` checks picklist blocking; inline `can_download` in `app.py` does not |

---

## B. DIT Gap Summary

| Metric | Count |
|--------|------:|
| **Total records reviewed** | 62 |
| **Fully Covered** | 0 |
| **Partially Covered** | 12 |
| **Not Covered** | 4 |
| **Not Relevant to DIT** | 44 |
| **Needs Clarification** | 2 |
| **Implemented but Workbench Only** | 3 features (picklist correction UI, record existence live check, `check_download_allowed()` unified gate) |
| **Implemented but Not Connected to DIT** | 1 (picklist correction flow) |
| **Implemented but Not Applied to corrected_df** | 2 (picklist replacements; sci-notation / some numeric fixes) |
| **Implemented but Not Included in DIT Readiness (download gate)** | 1 (picklist blocking bypassed at download button) |

---

## C. Top Gaps (ranked)

### 1. Upload failure risk — Cross-template dependency validation (P1)
- **Rows:** 29, 41, 42, 47, 49, 51  
- **Gap:** `engines/dependency_checker.py` returns empty; Account Relationship, Contracts→Customers, Product Hierarchies load order, Assortment cross-refs not checked  
- **Risk:** Upload fails in SFA after Copilot shows READY

### 2. Upload failure risk — DIT picklist validation disconnected from friendly headers (P1)
- **Rows:** 22, 41, 43, 51  
- **Gap:** After header prep, columns are friendly labels (`*L1 Channel`) but `build_dit_mapping_rows()` treats them as API names; picklist metadata lookup misses fields  
- **Risk:** Invalid picklist values (DISCOUNTER, GTM Status, contract duration) pass undetected

### 3. Upload failure risk — DIT download gate ignores picklist blocking (P1)
- **Rows:** 22, 41, 43, 51  
- **Gap:** `app.py` `can_download = not manual_review and not date_unresolved` omits `picklist_validation.has_blocking_issues`  
- **Risk:** User downloads CSV that will fail on upload despite readiness panel warning

### 4. Data corruption / manual rework — No DIT picklist correction path (P1)
- **Rows:** 22, 41, 43  
- **Gap:** Workbench has `render_picklist_validation()` + `apply_picklist_corrections()`; DIT only shows counts in Data Preparation Review  
- **Risk:** Users must fix picklists externally; rework loops

### 5. User confusion — Workbench-only features appear available but differ on DIT (P2)
- **Rows:** 7 (Customers Workbench note), 51  
- **Gap:** Lessons explicitly mention Workbench formatting/splitting; Copilot DIT path lacks file-split guidance and unified readiness/download logic  
- **Risk:** Teams pick wrong tool or wrong file shape

### 6. Manual rework — Route / Customer-to-Route specific rules missing (P1)
- **Rows:** 27, 28  
- **Gap:** No route ID≠0, route+sequence duplicate, or row-split warnings  
- **Risk:** Large batch failures mid-load

### 7. Implementation effort (lower urgency) — String length / domain validators (P2)
- **Rows:** 47  
- **Gap:** No 40-character or assortment SKU cardinality checks  
- **Risk:** Late upload failures

---

## D. Recommended Implementation Plan

### Must Have Before Demo

1. **Fix DIT picklist mapping** — Update `build_dit_mapping_rows()` to resolve `confirmed_api_field` from `Template_Config` / `csv_label_to_api` using friendly DIT headers.  
   - Files: `workflow/copilot.py`, `services/template_service.py`  
   - Tests: extend `tests/test_dit_picklist.py` with friendly-header columns (`*L1 Channel`)

2. **Connect picklist corrections to DIT path** — Add `render_picklist_validation()` + `apply_picklist_validation_result()` to DIT branch in `app.py` (mirror Workbench ~474–496).  
   - Ensure corrections flow into `corrected_df` before download

3. **Align DIT download gate** — Replace inline `can_download` check with `check_download_allowed()` or include `picklist_validation.has_blocking_issues` + validation bundle blocking issues  
   - Files: `app.py`, `validators/data_import_readiness_validator.py`

4. **Implement dependency checker MVP** — Load `rules/dependencies.json` for Account Relationship, Contracts→Customers, Product Hierarchies→Products, Retail Promotions→Products  
   - Files: `engines/dependency_checker.py`  
   - Surface as blocking manual review (no invented IDs)

5. **Routing / Customer-to-Route validators** — Route ID ≠ 0; composite duplicate (route + sequence); optional row-count warning (>8000)  
   - Files: new rules or template-specific validators called from `row_correction_plan_service.py`

### Should Have Next

6. **CSV comma / quoting improvements** — Unclosed-quote detection; UI guidance; optional safe quoting for address fields  
7. **Numeric / currency symbol safe fixes** — Approve-and-apply strip for currency symbols (`validators/numeric_validator.py`)  
8. **Market-aware External ID guidance** — Warn when same External ID used across markets without composite key  
9. **Merge picklist change_log into preparation change_log** — Complete audit trail in download artifacts  
10. **E2E DIT UI tests** — Cover header prep → date review → row approval → picklist → download

### Future Enhancement

11. File-split helper for large templates (Customer To Route, Prospects)  
12. Template version / SharePoint management (process — out of code scope)  
13. Consolidated template UX / in-app DIT vs Workbench decision guide  
14. Domain validators: GTM Status allowed values, assortment 40-char limit, promotion merge detection  
15. Validation report JSON download artifact

---

## E. Regression Test Plan

| Gap ID | Test CSV scenario | Expected detection | Expected correction | User action | Readiness | Download output |
|--------|-------------------|--------------------|---------------------|-------------|-----------|-----------------|
| G1 Picklist mapping | Customers DIT file with `*L1 Channel` = `INVALID` after header prep | Invalid picklist flagged with allowed values | Suggested replacement shown in picklist UI | Approve replacement | NOT READY until fixed | CSV contains corrected API picklist value under friendly header |
| G2 Picklist download gate | Same file; decline all fixes | Blocking picklist issue | None | — | NOT READY | Download button disabled |
| G3 Dependency AR | Account Relationship referencing non-existent `*External Id` | Blocking manual review: reference not in Customers load | None (no invented IDs) | Fix source or load Customers first | NOT READY | No download |
| G4 Contracts customer | Contract row for inactive/missing customer External ID | Cross-template dependency error | None | Fix reference | NOT READY | No download |
| G5 Route ID zero | Routing Import with Route ID = `0` | Blocking issue: invalid route ID | None | Manual fix | NOT READY | No download |
| G6 Route+sequence dup | Customer To Route: two rows same route + sequence | Duplicate composite key error | None | Manual fix | NOT READY | No download |
| G7 Commas in street | Customers `Street` = `10, Downing Street` (unquoted CSV) | CSV structure malformed row / too many fields | Manual review only (or quoted fix if implemented) | Fix or approve quoting | NOT READY until resolved | Clean CSV if fixed |
| G8 Date format | Contract date `2026-01-15` | Date review: convertible to `15/01/2026` | Auto-convert on approval | Approve date plan | READY after revalidation | DD/MM/YYYY in download |
| G9 External ID sci | `*External Id` = `1.23E+10` | Identifier blocking manual review | None (preserve text) | Manual fix in source | NOT READY | No download |
| G10 Type column | Customers missing `Type` (DIT template has no Type) | No template missing-header for Type; document as Workbench-only requirement | N/A | Use Workbench or add column manually | Clarify in UI | N/A |
| G11 Currency in Products | Product price `€12,50` | Numeric blocking or safe strip proposal | Strip symbol if approved | Approve | READY if fixed | Dot-decimal numeric |
| G12 Past routing date | Routing Import end date in past | Manual review (once business rule added) | None | Manual fix | NOT READY | No download |
| G13 Product hierarchy order | Product Brand Group referencing competitor before Pepsi SKU | Dependency warning before upload | None | Load Products first | NOT READY | No download |
| G14 Assortment 41 chars | Assortment Products 41-char string | Length validation error | Truncate proposal (future) | Manual fix | NOT READY | No download |
| G15 Ready happy path | Valid Customers DIT file matching template | Template match; no blocking issues | Header reorder if needed | Approve safe fixes | READY | Friendly headers; UTF-8; no API names; dates DD/MM/YYYY |

---

## Workbench vs DIT Active-Path Check

Features that exist in codebase but are **not** on the active DIT path in `app.py`:

| Feature | Workbench | DIT | Gap |
|---------|-----------|-----|-----|
| Picklist validation UI + apply | Yes (`render_picklist_validation`) | Detect only in validation bundle | **Not Connected** |
| Record existence live check | Yes | Runs via `run_validation()` but Insert-focused | Partial |
| Mapping confirmation | Yes | Header prep via `render_prepare_file` | Different UX — OK |
| `check_download_allowed()` | Yes (Workbench download) | Inline partial check | **Not Connected** |
| Blank row removal | Partial both | In row plan | Connected (recent) |
| Whitespace trim | Partial both | Phone/address/whitespace validators | Connected |
| Formatting review engine | Disconnected both | Disconnected | Not in either active path |
| Type auto-population | Workbench prep plan | DIT Customers template has no Type column | Template-specific |

---

## Comparison with `COPILOT_FEATURE_AUDIT.md`

| Prior finding | Current DIT status |
|---------------|-------------------|
| DIT picklist skipped (no mapping_rows) | **Partially addressed** — `build_dit_mapping_rows()` added; mapping uses friendly names incorrectly |
| Blank rows not in row plan | **Addressed** — `validate_blank_rows()` + `_apply_blank_row_removals()` in `row_correction_plan_service.py` |
| Download gate simpler for DIT | **Still open** — picklist not in download `can_download` |
| Dependency checker stub | **Still open** |
| Formatting review disconnected | **Still open** (both paths) |

---

## Executive Summary

- **62** lessons-learned records reviewed (**44** not relevant to DIT data prep; **12** partially covered; **4** not covered; **0** fully covered under strict DIT criteria).
- **Top 5 gaps:** (1) cross-template dependency validation stub, (2) DIT picklist API mapping from friendly headers, (3) download button bypasses picklist blocking, (4) no DIT picklist correction UI/applied fixes, (5) route/customer-to-route specific validation missing.
- **Output files:** this report + `docs/DIT_LESSONS_LEARNED_COVERAGE.csv`.
- **No code was modified** during this audit.
