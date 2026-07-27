"""Generate Retail Promotion fault-injection test CSVs (one-off generator)."""

from __future__ import annotations

import csv
import os
from copy import deepcopy
from pathlib import Path

_DEFAULT_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "test_data"
    / "retail_promotion"
    / "RO_Promotion_Source.csv"
)
SOURCE = Path(os.environ.get("RETAIL_PROMOTION_SOURCE_CSV", str(_DEFAULT_SOURCE)))
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "test_data" / "retail_promotion"
FAULTY_FILE = OUTPUT_DIR / "RO_Promotion_Faulty_Validation_Test.csv"
MALFORMED_FILE = OUTPUT_DIR / "RO_Promotion_Malformed_Row_Test.csv"
LOG_FILE = OUTPUT_DIR / "RO_Promotion_Fault_Injection_Log.csv"

LOG_COLUMNS = [
    "output_file",
    "csv_row_number",
    "column",
    "original_value",
    "faulty_value",
    "validation_being_tested",
    "expected_copilot_behavior",
]


def read_source_rows() -> tuple[list[str], list[list[str]]]:
    with SOURCE.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        rows = list(reader)
    if not rows:
        raise ValueError("Source CSV is empty")
    return rows[0], rows[1:]


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def col_index(header: list[str], label: str) -> int:
    for idx, name in enumerate(header):
        if name == label or name.lstrip("*") == label.lstrip("*"):
            return idx
    raise KeyError(label)


def set_cell(rows: list[list[str]], row_idx: int, col: int, value: str) -> str:
    original = rows[row_idx][col]
    rows[row_idx][col] = value
    return original


def main() -> None:
    header, data_rows = read_source_rows()
    rows = deepcopy(data_rows)
    log: list[dict[str, str]] = []

    idx = {name: col_index(header, name) for name in header}
    c_name = idx["*Promotion Name"]
    c_key = idx["Key Account/Banner Value"]
    c_acct = idx["Account External ID"]
    c_seg = idx["PS Value Segmentation Snacks"]
    c_mat = idx["Material ID"]
    c_start = idx["*Start Date(dd/mm/yyyy)"]
    c_end = idx["*End Date(dd/mm/yyyy)"]
    c_infl = idx["*Influence Date(dd/mm/yyyy)"]
    c_type = idx["*Promotion Type"]
    c_place = idx["Placement Type"]
    c_market = idx["*Market"]

    def inject(
        row_number: int,
        column: str,
        faulty_value: str,
        validation: str,
        expected: str,
        *,
        original_value: str | None = None,
    ) -> None:
        row_idx = row_number - 2
        col = idx[column]
        original = original_value if original_value is not None else rows[row_idx][col]
        set_cell(rows, row_idx, col, faulty_value)
        log.append(
            {
                "output_file": FAULTY_FILE.name,
                "csv_row_number": str(row_number),
                "column": column,
                "original_value": original,
                "faulty_value": faulty_value,
                "validation_being_tested": validation,
                "expected_copilot_behavior": expected,
            }
        )

    # DATE TESTS — different columns / rows
    inject(2, "*Start Date(dd/mm/yyyy)", "06/07/2026", "Date format (DIT zero-padded DD/MM/YYYY)", "Convertable date → propose correction to target tool format")
    inject(3, "*Start Date(dd/mm/yyyy)", "2026-07-06", "Date format (Workbench ISO YYYY-MM-DD)", "Convertable date → propose correction to target tool format")
    inject(4, "*Start Date(dd/mm/yyyy)", "6/7/2026", "Date format (single-digit D/M/YYYY)", "Convertable date → propose correction with day-first parsing")
    inject(5, "*End Date(dd/mm/yyyy)", "07/06/2026", "Date format (US-style MM/DD/YYYY ambiguous)", "Ambiguous date → require source-format confirmation before conversion")
    inject(6, "*End Date(dd/mm/yyyy)", "31/02/2026", "Invalid calendar date", "Invalid calendar date → manual review required")
    inject(7, "*Influence Date(dd/mm/yyyy)", "July 6, 2026", "Text date value", "Invalid date text → manual review required")
    inject(8, "*Influence Date(dd/mm/yyyy)", "46209", "Excel serial-like numeric date", "Possible Excel date serial → confirmation required")
    inject(9, "*Influence Date(dd/mm/yyyy)", "", "Blank date (metadata optional; template-required)", "Blank required/template-required date → blocking issue")

    # REQUIRED FIELD TESTS — separate rows
    inject(10, "*Promotion Name", "", "Required field blank (Name)", "Blank required field → blocking issue")
    inject(11, "*Market", "", "Required field blank (Market__c picklist)", "Blank required field → blocking issue")

    # PICKLIST TESTS — metadata-confirmed picklists only
    inject(12, "*Promotion Type", "INVALID PICKLIST VALUE", "Invalid picklist (Promotion_Type__c)", "Invalid picklist → flag against Salesforce metadata")
    inject(13, "*Promotion Type", " In store ", "Picklist with surrounding spaces (Promotion_Type__c)", "Whitespace → propose safe trimming; value valid after trim")
    inject(14, "*Promotion Type", "leaflet", "Incorrect picklist capitalization (Promotion_Type__c)", "Invalid picklist capitalization → flag or propose canonical value")
    inject(15, "PS Value Segmentation Snacks", "INVALID PICKLIST VALUE", "Invalid picklist (L3_Snacks_Value_Segmentation__c)", "Invalid picklist → flag against Salesforce metadata")
    inject(16, "PS Value Segmentation Snacks", " A+ ", "Picklist with surrounding spaces (L3_Snacks_Value_Segmentation__c)", "Whitespace → propose safe trimming; value valid after trim")
    inject(17, "PS Value Segmentation Snacks", "a+", "Incorrect picklist capitalization (L3_Snacks_Value_Segmentation__c)", "Invalid picklist capitalization → flag or propose canonical value")
    inject(18, "*Market", "INVALID PICKLIST VALUE", "Invalid picklist (Market__c)", "Invalid picklist → flag against Salesforce metadata")

    # WHITESPACE TESTS
    inject(19, "*Promotion Name", "  Rewe - DDU 6X330ML", "Leading whitespace in Name", "Whitespace → propose safe trimming")
    inject(20, "Key Account/Banner Value", "Profi   ", "Trailing whitespace in Key Account lookup text", "Whitespace → propose safe trimming")
    inject(21, "Placement Type", "End  of  gondola  +", "Repeated internal spaces in Placement Type text", "Whitespace → propose safe trimming/normalization")

    original_name_22 = rows[20][c_name]
    faulty_name_22 = "Auchan - Promo 23\nPepsi 1.5L "
    inject(
        22,
        "*Promotion Name",
        faulty_name_22,
        "Embedded line break in text field (Name)",
        "Embedded line break in text → flag for manual review or safe normalization",
        original_value=original_name_22,
    )

    # LOOKUP TESTS
    inject(23, "Key Account/Banner Value", "LOOKUP_DOES_NOT_EXIST", "Invalid lookup reference (Key_Account__c)", "Invalid lookup → manual review; do not invent Salesforce IDs")
    inject(24, "Account External ID", "LOOKUP_DOES_NOT_EXIST", "Invalid lookup reference (Account_External_ID__c)", "Invalid lookup → manual review; do not invent Salesforce IDs")
    # Row 17 already has blank Key Account — log as control comparison
    log.append(
        {
            "output_file": FAULTY_FILE.name,
            "csv_row_number": "17",
            "column": "Key Account/Banner Value",
            "original_value": "",
            "faulty_value": "",
            "validation_being_tested": "Blank optional lookup (Key_Account__c)",
            "expected_copilot_behavior": "Blank optional lookup allowed; no blocking issue unless business rule requires value",
        }
    )

    # IDENTIFIER TESTS — Material ID (Product.External_Id__c)
    log.append(
        {
            "output_file": FAULTY_FILE.name,
            "csv_row_number": "24",
            "column": "Material ID",
            "original_value": data_rows[22][c_mat],
            "faulty_value": data_rows[22][c_mat],
            "validation_being_tested": "Duplicate Material ID partner row (unchanged)",
            "expected_copilot_behavior": "Duplicate External ID → blocking review when uniqueness enforced",
        }
    )
    inject(
        25,
        "Material ID",
        data_rows[22][c_mat],
        "Duplicate Material ID matching row 24",
        "Duplicate External ID → blocking review when uniqueness enforced",
    )
    inject(26, "Material ID", "1.23457E+11", "Scientific notation identifier", "Scientific notation → identifier warning; preserve as text")
    inject(27, "Material ID", "340056393.0", "Decimal suffix on identifier", "Trailing .0 → propose removal of accidental decimal suffix")
    inject(28, "Material ID", "34049181", "Leading zero removed from Material ID", "Leading zero removed → identifier warning or propose zero-padding when rule applies")
    inject(29, "Material ID", "0340049181", "Leading zero preserved Material ID (control)", "Correct leading-zero identifier → accept without change")

    # VALID PICKLIST CONTROL ROW — unchanged valid value retained on row 2 Promotion Type
    log.append(
        {
            "output_file": FAULTY_FILE.name,
            "csv_row_number": "2",
            "column": "*Promotion Type",
            "original_value": rows[0][c_type],
            "faulty_value": rows[0][c_type],
            "validation_being_tested": "Valid picklist control (Promotion_Type__c)",
            "expected_copilot_behavior": "Valid picklist value kept unchanged",
        }
    )

    # Metadata fields not present in Retail Promotion CSV template
    for field_name, note in [
        ("Methods (MultiPicklist)", "Not mapped in Retail Promotion template CSV; multipicklist semicolon test not injected"),
        ("IsActive (Boolean)", "Not mapped in Retail Promotion template CSV; boolean normalization tests not injected"),
        ("Numeric/Currency fields", "No numeric or currency fields mapped in Retail Promotion template CSV"),
    ]:
        log.append(
            {
                "output_file": FAULTY_FILE.name,
                "csv_row_number": "N/A",
                "column": field_name,
                "original_value": "N/A",
                "faulty_value": "N/A",
                "validation_being_tested": "Template column unavailable",
                "expected_copilot_behavior": note,
            }
        )

    write_csv(FAULTY_FILE, header, rows)

    # Malformed row file — raw text lines for structural defects
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    source_text = SOURCE.read_text(encoding="utf-8-sig")
    source_lines = source_text.splitlines()
    malformed_lines = list(source_lines)

    comma_row_number = len(malformed_lines) + 1
    unmatched_row_number = comma_row_number + 1
    short_row_number = unmatched_row_number + 1

    malformed_lines.append(
        "Carrefour - Cupon Brand Pepsi, unquoted comma test,Carrefour,,,340060000,12/7/2026,20/11/2026,28/06/2026,Coupon,End of gondola +,RO"
    )
    malformed_lines.append(
        'Carrefour - unmatched quote test,Carrefour,,,340060001,12/7/2026,20/11/2026,28/06/2026,Coupon,"End of gondola +,RO'
    )
    malformed_lines.append(
        "Short row missing columns,Carrefour,,,340060002,12/7/2026"
    )

    MALFORMED_FILE.write_text("\n".join(malformed_lines) + "\n", encoding="utf-8")

    log.extend(
        [
            {
                "output_file": MALFORMED_FILE.name,
                "csv_row_number": str(comma_row_number),
                "column": "*Promotion Name",
                "original_value": "(synthetic row)",
                "faulty_value": "Carrefour - Cupon Brand Pepsi, unquoted comma test",
                "validation_being_tested": "Unquoted comma inside text value",
                "expected_copilot_behavior": "Malformed row → CSV structure error; extra parsed column",
            },
            {
                "output_file": MALFORMED_FILE.name,
                "csv_row_number": str(unmatched_row_number),
                "column": "Placement Type",
                "original_value": "(synthetic row)",
                "faulty_value": '"End of gondola +,RO',
                "validation_being_tested": "Unmatched quotation mark",
                "expected_copilot_behavior": "Malformed row → CSV structure error",
            },
            {
                "output_file": MALFORMED_FILE.name,
                "csv_row_number": str(short_row_number),
                "column": "(row)",
                "original_value": "(synthetic row)",
                "faulty_value": "6 columns vs 11 header columns",
                "validation_being_tested": "Row with fewer columns than header",
                "expected_copilot_behavior": "Malformed row → CSV structure error; column count mismatch",
            },
        ]
    )

    with LOG_FILE.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(log)

    modified_rows = sorted({int(item["csv_row_number"]) for item in log if item["csv_row_number"].isdigit()})
    print(f"SOURCE_ROWS={len(data_rows)}")
    print(f"MODIFIED_ROWS={len(modified_rows)}")
    print(f"FAULTY_FILE={FAULTY_FILE}")
    print(f"MALFORMED_FILE={MALFORMED_FILE}")
    print(f"LOG_FILE={LOG_FILE}")


if __name__ == "__main__":
    main()
