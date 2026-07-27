# Europe SFA Data Load Copilot

## Purpose

AI-assisted application that helps the Europe SFA team prepare CSV files before uploading them into Salesforce.

The copilot reduces manual effort by validating, preparing, and explaining files — it does **not** replace Workbench or the Data Import Tool.

## Architecture

```
app.py                     # Streamlit orchestrator only
│
├── ui/                    # Display components
├── workflow/              # Orchestrates engine calls
├── core/                  # Config, CSV loading, reference templates
├── engines/
│   ├── template_comparison.py
│   ├── validation_engine.py
│   ├── field_mapping.py
│   ├── data_preparation.py
│   ├── dependency_checker.py
│   ├── upload_readiness.py
│   └── ai_summary.py
├── validators/            # Low-level deterministic validators
└── rules/
    ├── tool_mappings.json
    └── templates.json
```

## Data flow

```
UI → Workflow → Engines → Validators / Rules
```

## Upload methods

| Method | Headers | Dates |
|--------|---------|-------|
| Data Import Tool | Business-friendly names | DD/MM/YYYY |
| Workbench | Salesforce API names | YYYY-MM-DD |

Reference templates for Data Import Tool live in `reference_templates/data_import_tool/`.

Workbench has no standard CSV templates — business templates are converted to API field names via `rules/tool_mappings.json`.

## Account object templates

These templates all map to Salesforce **Account** with different **Type** values:

- Customers → Customer
- Wholesalers → Wholesaler
- Prospects → Prospect
- Payers → Payer
- Key Account → Key Account

## User workflow

1. Select upload method
2. Select business template
3. Select load action (Workbench only): Insert or Update
4. Upload CSV
5. Compare against reference template
6. Review formatting changes (Workbench + DIT file)
7. Approve changes → download corrected CSV
8. Review upload readiness

## Automatic preparation (with approval)

Safe changes proposed before applying:

- Rename headers (DIT → API)
- Convert dates
- Populate Type column
- Trim whitespace
- Remove blank rows
- Add Id column
- Reorder columns

Never automatic:

- Invent Salesforce IDs
- Guess lookup values
- Resolve dependencies
- Make business decisions

## Run

```bash
.\venv\Scripts\Activate.ps1
streamlit run app.py
```
