> Generated from read-only codebase audit. No code was modified.

# Europe SFA Data Load Copilot — Read-Only Workflow Audit

**Scope:** Upload → header mapping → column exclusion → row validation → proposed corrections → user approval → `corrected_df` → revalidation → download  
**Entry point:** `app.py` orchestrates via `workflow/copilot.py`  
**Primary validation orchestrator:** `engines/validation_engine.py` → `run_validation()`  
**Row-level plan builder:** `services/row_correction_plan_service.py` → `build_row_correction_plan()`  
**Approval UI:** `ui/data_preparation_review.py` → `render_data_preparation_review()`  
**Download gating:** `services/download_readiness_service.py` → `evaluate_download_readiness()` → `validators/workbench_readiness_validator.py` → `evaluate_workbench_readiness()`

---

## Workflow Call Chain (Summary)

```
app.py
  ├─ load_uploaded_csv()                          [core/csv_loader.py]
  ├─ DIT: run_template_comparison → render_prepare_file → apply_correction_changes
  │        → render_date_format_review → build_row_correction_plan_proposal
  │        → render_data_preparation_review → apply_file_preparation
  │        → revalidate_after_corrections → render_preparation_results
  └─ Workbench: render_mapping_confirmation → build_mapped_dataframe
               → run_full_validation → render_picklist_validation / render_salesforce_record_check
               → render_date_format_review → build_row_correction_plan_proposal
               → build_workbench_preparation_plan_proposal → render_data_preparation_review
               → apply_file_preparation (apply_workbench_preparation)
               → revalidate_after_corrections → check_download_allowed → render_preparation_results
```

---

## Feature Audit Table

| # | Feature | Status | Implementation file | Function | Connected to UI? | Applied to corrected_df? | Included in readiness? | Test coverage | Recommended next action |
|---|---------|--------|---------------------|----------|------------------|--------------------------|------------------------|---------------|-------------------------|
| 1 | **Whitespace validation** | **Partially Implemented** | `validators/phone_validator.py`, `validators/address_validator.py`, `engines/formatting_review.py` | `validate_phones()`, `validate_addresses()`, `_detect_whitespace_issues()` | Partial — row fixes via `ui/data_preparation_review.py`; general column trim only in disconnected `ui/formatting_review.py` (not called from `app.py`) | Partial — phone/address trims via `apply_row_corrections()` in `services/row_correction_plan_service.py`; general trim not wired | Partial — blocking whitespace issues in `manual_review` block download via `evaluate_workbench_readiness()` | `tests/test_row_validation.py` (phone/address trim only) | Wire `build_formatting_review()` into Workbench/DIT flows; add NBSP/tab/internal-space handling in `validators/common.py` |
| 2 | **Blank rows & empty columns** | **Partially Implemented** | `core/csv_loader.py`, `engines/formatting_review.py`, `services/workbench_preparation_service.py` | `filter_blank_header_columns()`, `_detect_blank_rows()`, `build_workbench_preparation_plan()` | Partial — blank/Unnamed headers at upload; blank-row removal UI disconnected | **Not Applied** — blank-row removal never reaches `corrected_df` (summary key `blank_rows` missing from row plan) | No — blank rows not counted in readiness | `tests/test_blank_headers.py`, `tests/test_workbench_mapping_flow.py` | Add blank-row detection to `build_row_correction_plan()` and connect removal in `apply_row_corrections()` |
| 3 | **Date validation** | **Fully Implemented** (Workbench); **Partially Implemented** (DIT picklist gap separate) | `services/date_conversion_service.py`, `validators/date_validator.py`, `ui/date_format_review.py` | `resolve_date_field_columns()`, `validate_dates()`, `analyze_cell()`, `apply_date_conversions()`, `attach_date_validation_state()` | Yes — `render_date_format_review()` in `app.py` (lines 225–247, 529–553) | Yes — via date review + `apply_row_corrections()` for safe date issues | Yes — `date_unresolved` blocks download in `evaluate_workbench_readiness()` and DIT `can_download` check | `tests/test_date_conversion.py`, `tests/test_row_validation.py` | Consolidate duplicate date paths (date review vs row-plan dates); add mixed-format UI test |
| 4 | **Leading zeroes** | **Partially Implemented** | `validators/identifier_validator.py`, `rules/formatting_rules.json` | `validate_identifiers()`, `resolve_identifier_fields()` | Yes — shown in Data Preparation Review summary | Yes — safe `.0` removal and confirmed zfill rules via `apply_row_corrections()` | Yes — unconfirmed leading-zero/sci-notation issues are `blocking` → block download | `tests/test_row_validation.py` | Expand `formatting_rules.json` coverage for EAN/SKU/route IDs; add metadata-driven external-ID length rules |
| 5 | **Scientific notation** | **Partially Implemented** | `validators/identifier_validator.py`, `validators/phone_validator.py` | `validate_identifiers()`, `validate_phones()` | Yes — surfaced as manual review in Data Preparation Review | **Not Applied** — flagged `blocking=True`, no auto-correction (preserve as text) | Yes — blocks download via `row_correction_plan.has_blocking_manual_review` | `tests/test_row_validation.py` (identifiers only) | Add explicit warning UI + optional string-prefix correction with approval |
| 6 | **Phone validation** | **Partially Implemented** | `validators/phone_validator.py` | `validate_phones()`, `resolve_phone_fields()` | Yes | Partial — trim/spaces/`.0` applied when approved; letters/sci-notation not fixable | Yes — blocking phone issues block download | `tests/test_row_validation.py` | Add length/separator normalization (no country-code guessing); connect `formatting_review._normalize_phone()` |
| 7 | **Address validation** | **Partially Implemented** | `validators/address_validator.py`, `validators/csv_structure_validator.py` | `validate_addresses()`, `validate_csv_structure()` | Yes | Yes — trim, line-break→space, postal `.0` via `apply_row_corrections()` | Yes — malformed CSV rows block via `manual_review` | `tests/test_row_validation.py` | Add comma-in-unquoted-field heuristics; CSV quoting guidance in UI |
| 8 | **Malformed CSV structure** | **Partially Implemented** | `validators/csv_structure_validator.py`, `engines/formatting_review.py` | `validate_csv_structure()`, `_detect_raw_csv_malformation()` | Yes — row plan summary + manual review | **Not Applied** — no auto-repair; manual review only | Yes — `blocking=True` issues block download | `tests/test_row_validation.py` (too-many-fields only) | Add explicit unclosed-quote detection; fail fast on `csv.reader` errors |
| 9 | **Boolean validation** | **Partially Implemented** | `validators/boolean_validator.py` | `validate_boolean_fields()`, `resolve_boolean_fields()` | Yes — requires confirmation in Data Preparation Review | Yes — via `apply_row_corrections()` when approved | Partial — invalid booleans block; convertible ones need approval first | `tests/test_row_validation.py` | Surface boolean issues more prominently in summary metrics |
| 10 | **Numeric/decimal validation** | **Partially Implemented** | `validators/numeric_validator.py` | `validate_numeric_fields()`, `resolve_numeric_fields()` | Yes — blocking manual review items | **Not Applied** — detect-only, no proposed conversion | Yes — `blocking=True` | **None** | Add safe European→dot-decimal conversion with approval; add tests |
| 11 | **Required field validation** | **Partially Implemented** | `validators/load_action_validator.py`, `engines/data_preparation.py`, `validators/picklist_validator.py`, `engines/template_comparison.py` | `validate_load_action()`, `_apply_type_column()`, `_is_required_field()`, DIT header comparison | Yes — Workbench mapping + load-action UI; DIT template comparison | Partial — Type auto-populated in `apply_preparation()`; Id manual for Update | Yes — Update Id blanks, picklist blank-required, template missing headers | `tests/test_correction_workflow.py`, `tests/test_preparation_task.py` | Unify Insert/Update required-field rules across DIT and Workbench |
| 12 | **Duplicate identifiers** | **Partially Implemented** | `validators/duplicate_key_validator.py` | `validate_duplicate_keys()`, `resolve_external_id_fields()` | Yes — manual review in Data Preparation Review | **Not Applied** — detect-only | Yes — blocking duplicates block download | `tests/test_row_validation.py` | Extend to business keys (EAN/SKU) via metadata unique flags |
| 13 | **Picklist validation** | **Fully Implemented** (Workbench); **Not Connected** (DIT) | `validators/picklist_validator.py`, `ui/picklist_validation.py`, `services/picklist_correction_service.py` | `validate_picklists()`, `render_picklist_validation()`, `apply_picklist_corrections()` | Workbench only — `app.py` lines 466–489; DIT skips (no `mapping_rows`) | Yes — applied to `mapped_df` before preparation, flows into `corrected_df` | Yes — `has_blocking_issues` blocks download | `tests/test_picklist_validation.py` (39 tests) | Add DIT picklist path or document as Workbench-only; add "Not Checked" status for unmapped picklists |
| 14 | **Multipicklist** | **Fully Implemented** | `validators/picklist_validator.py`, `services/picklist_correction_service.py` | `_split_multipicklist_value()`, `_validate_cell()`, `_apply_replacement()` | Yes — Workbench picklist UI | Yes — semicolon-aware replacement | Yes | `tests/test_picklist_validation.py` | None critical |
| 15 | **Lookup/dependency checks** | **Not Implemented** (stub); **Partial** (live record check) | `engines/dependency_checker.py`, `validators/record_existence_validator.py`, `ui/salesforce_record_check.py` | `check_dependencies()` (empty stub), `validate_record_existence()`, `render_salesforce_record_check()` | Record check yes (Workbench); dependency rules no | N/A — manual review only | Partial — record existence blocks Update download | `tests/test_record_existence_validation.py` | Implement `rules/dependencies.json` loader; no invented IDs policy |
| 16 | **Header mapping** | **Fully Implemented** | `services/workbench_mapping_service.py`, `services/header_matching_service.py`, `ui/mapping_confirmation.py`, `ui/prepare_file.py` | `build_workbench_mapping_rows()`, `analyze_header_matching()`, `render_mapping_confirmation()`, DIT `render_prepare_file()` | Yes | Yes — `build_mapped_df()` / `apply_correction_changes()` produce mapped headers in `corrected_df` | Yes — unresolved mappings block download | `tests/test_header_matching.py`, `tests/test_workbench_mapping_flow.py`, `tests/test_blank_headers.py` | None critical |
| 17 | **User approval** | **Fully Implemented** | `ui/data_preparation_review.py`, `ui/date_format_review.py`, `ui/picklist_validation.py`, `ui/prepare_file.py` | `render_data_preparation_review()`, `render_date_format_review()`, `render_picklist_validation()`, `render_prepare_file()` | Yes | N/A | N/A | `tests/test_preparation_flow.py`, `tests/test_correction_workflow.py` | Retire unused `ui/data_quality_review.py` to avoid confusion |
| 18 | **corrected_df flow** | **Fully Implemented** | `services/file_preparation_service.py`, `services/workbench_preparation_service.py`, `services/revalidation_service.py`, `ui/components.py` | `prepare_file()`, `apply_workbench_preparation()`, `revalidate_prepared_file()`, `render_preparation_results()` | Yes | Yes — `original_df` never mutated; `corrected_df` is download source | Yes | `tests/test_row_validation.py`, `tests/test_correction_workflow.py` | Merge picklist change_log into preparation `change_log` for complete audit trail |
| 19 | **Readiness logic** | **Fully Implemented** | `services/preparation_flow_service.py`, `validators/workbench_readiness_validator.py`, `services/readiness_service.py`, `core/config.py` | `evaluate_preparation_readiness()`, `evaluate_workbench_readiness()`, `evaluate_upload_readiness()` | Yes — `render_readiness()` in `ui/components.py` | N/A | N/A | `tests/test_preparation_flow.py`, `tests/test_correction_workflow.py` | Align DIT download gate with `check_download_allowed()` (currently simpler inline check) |
| 20 | **Download outputs** | **Partially Implemented** | `ui/components.py` | `render_preparation_results()` | Yes | Yes — `corrected_df.to_csv()` | N/A | Partial — `tests/test_correction_workflow.py` | Add validation report JSON download; explicit CSV quoting options for address fields |

---

## Summary Sections

### 1. Top Five Missing Features

1. **Lookup/dependency checks** — `engines/dependency_checker.py` → `check_dependencies()` returns empty stub with note *"Dependency rules not yet configured"*. Called from `run_validation()` but does nothing.
2. **General column whitespace trim** — `engines/formatting_review.py` → `_detect_whitespace_issues()` exists but `ui/formatting_review.py` is never invoked from `app.py`.
3. **Blank row removal in corrected_df** — `_detect_blank_rows()` exists only in formatting review; `workbench_preparation_service.py` references `summary.blank_rows` which `row_correction_plan_service.py` never populates.
4. **Validation report download** — No validation report artifact; only change log, mapping report, and manual review JSON in `render_preparation_results()`.
5. **DIT picklist validation** — `run_full_validation()` skips picklist when `mapping_rows` is absent (DIT path in `app.py` line 263–270 passes no mappings).

### 2. Top Five Partially Implemented Features

1. **Whitespace validation** — Phone/address only; no NBSP, tabs, or general-field trim in active flow.
2. **Phone validation** — No length check in `validate_phones()`; separator stripping only in disconnected formatting review.
3. **Numeric/decimal validation** — Detect-only (`validators/numeric_validator.py`); no conversion path; zero tests.
4. **Leading zeroes** — Rule-driven for known patterns; `digits_look_truncated()` heuristic blocks without fix for unconfirmed fields.
5. **Malformed CSV** — Field-count mismatch only; no unclosed-quote or parser-error surfacing.

### 3. Features Implemented but Not Connected to UI

| Feature | File | Function | Notes |
|---------|------|----------|-------|
| Formatting review (whitespace, blank rows, phone normalize, leading zeros) | `engines/formatting_review.py`, `ui/formatting_review.py` | `detect_formatting_issues()`, `render_formatting_review()` | Exported from `workflow/copilot.py` but never called in `app.py` |
| Legacy data quality review UI | `ui/data_quality_review.py` | `render_data_quality_review()` | Superseded by `ui/data_preparation_review.py` |
| Formatting readiness gate | `workflow/copilot.py` | `mappings_ready_for_formatting()` | Not referenced in `app.py` |
| Dependency checker | `engines/dependency_checker.py` | `check_dependencies()` | Runs but returns empty results |
| Workbench blank-row prep change | `services/workbench_preparation_service.py` | `build_workbench_preparation_plan()` lines 112–123 | Never triggered (`blank_rows` summary key absent) |

### 4. Validators That Run but Don't Affect Readiness

| Validator | File | Why it doesn't block readiness |
|-----------|------|-------------------------------|
| Template extra-column warnings | `engines/validation_engine.py` | Severity `warning` only; not in `evaluate_workbench_readiness()` reasons |
| Insert Id populated warning | `validators/load_action_validator.py` | Severity `warning`; doesn't set `blocks_download` |
| Dependency checker | `engines/dependency_checker.py` | Always returns empty issues |
| Picklist "Needs Review" (non-blocking) | `validators/picklist_validator.py` | `blocking=False`; only Invalid/Blank Required block |
| DIT template comparison info-level issues | `engines/validation_engine.py` | Deferred while correction plan pending |
| Record existence (Insert, non-blocking cases) | `validators/record_existence_validator.py` | Only blocks when `blocks_download=True` (Update-focused) |

### 5. Corrections in UI but Not in Downloaded CSV

| Correction | Where approved | Gap |
|------------|----------------|-----|
| Picklist replacements | `ui/picklist_validation.py` → updates `mapped_df` | Applied to `corrected_df` indirectly, but **not included in preparation `change_log`** |
| Skipped/declined safe fixes | Data Preparation Review "Skip" | User sees proposals but `corrected_df` lacks those fixes (by design) |
| Formatting review categories | Disconnected UI | Never reach any dataframe |
| Blank row removal | Workbench prep plan | `apply_row_corrections()` has no handler for `remove_blank_rows` issue IDs |
| Manual-review-only issues (sci notation, duplicates, numeric format) | Data Preparation Review | Intentionally not auto-applied; remain in source values unless user fixes file externally |

### 6. Recommended Implementation Order

1. **Connect formatting review to main flow** — Wire `build_formatting_review()` + approval into Workbench/DIT after mapping; highest impact for whitespace, blank rows, phone normalization.
2. **Fix blank-row pipeline** — Add blank-row issues to `build_row_correction_plan()` / `apply_row_corrections()`; fix `blank_rows` summary key mismatch in `workbench_preparation_service.py`.
3. **Unify download readiness** — Use `check_download_allowed()` for DIT (currently inline manual-review check at `app.py` lines 354–359); ensures picklist/row-plan/date gates are consistent.
4. **Numeric conversion with approval** — Extend `numeric_validator.py` with safe conversion proposals; add tests (currently zero).
5. **Implement dependency rules** — Load `rules/dependencies.json` in `dependency_checker.py`; complement live record check without inventing IDs.
6. **DIT picklist support** — Build synthetic `mapping_rows` from DIT header rename map so `validate_picklists()` runs for DIT uploads.
7. **Download artifacts** — Add validation report JSON; improve CSV quoting for address fields in `render_preparation_results()`.
8. **Audit trail completeness** — Merge picklist `change_log` into preparation result before download.

---

## Test Coverage Overview

| Area | Test file | Coverage quality |
|------|-----------|------------------|
| Row validators (date, phone, address, boolean, duplicate, CSV) | `tests/test_row_validation.py` | Good |
| Date conversion | `tests/test_date_conversion.py` | Good (73 references) |
| Picklist + multipicklist | `tests/test_picklist_validation.py` | Strong (39 tests) |
| Header mapping / blank headers | `tests/test_header_matching.py`, `tests/test_blank_headers.py`, `tests/test_workbench_mapping_flow.py` | Good |
| Preparation readiness | `tests/test_preparation_flow.py` | Good |
| Correction workflow | `tests/test_correction_workflow.py` | Good |
| Record existence | `tests/test_record_existence_validation.py` | Good |
| Numeric validation | — | **None** |
| Dependency checker | — | **None** |
| Formatting review UI integration | — | **None** |
| End-to-end app/UI | — | **None** (unit tests only) |

---

## Key Architectural Observations

- **Two parallel correction systems** coexist: `engines/formatting_review.py` (disconnected) and `services/row_correction_plan_service.py` (active). This causes duplicated logic and gaps (blank rows, general whitespace, phone normalization).
- **Workbench path is substantially richer** than DIT: picklist UI, record check, mapping confirmation, and `check_download_allowed()` are Workbench-only.
- **`original_df` immutability is enforced** — confirmed by `apply_row_corrections()` and `apply_preparation()` copying dataframes; tested in `tests/test_row_validation.py`.
- **Date handling is the most mature subsystem** — metadata-driven field resolution, dedicated review UI, post-conversion revalidation via `attach_date_validation_state()`, and download blocking on unresolved dates.

No code was modified during this audit.
