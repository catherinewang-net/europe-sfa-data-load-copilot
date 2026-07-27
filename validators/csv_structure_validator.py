"""CSV row structure validation."""

from __future__ import annotations

import csv
import io
from typing import Any

from validators.common import build_issue


def validate_csv_structure(
    raw_csv_content: str | None,
    header_count: int,
) -> list[dict[str, Any]]:
    if not raw_csv_content:
        return []

    issues: list[dict[str, Any]] = []
    normalized = raw_csv_content.replace("\r\n", "\n").replace("\r", "\n")
    if normalized.startswith("\ufeff"):
        normalized = normalized[1:]

    lines = normalized.split("\n")
    header_line_index = _first_non_blank_line_index(lines)
    if header_line_index is None:
        return issues

    header_tokens = _parse_csv_line(lines[header_line_index])
    expected_count = len(header_tokens) if header_tokens else header_count

    for line_number, message, preview, blocking in _scan_raw_csv_issues(
        lines,
        header_line_index,
        expected_count,
    ):
        issue = build_issue(
            issue_id=f"csv:structure:{line_number}:{hash(message) & 0xffff}",
            category="csv_structure",
            field=None,
            row=line_number,
            original_value=preview[:120],
            proposed_value="(manual review required)",
            reason=message,
            safe=False,
            blocking=blocking,
            confidence=1.0 if blocking else 0.9,
        )
        issue["address_confidence"] = "Invalid Structure" if blocking else "Needs Review"
        issues.append(issue)

    reader = csv.reader(io.StringIO(normalized))
    try:
        headers = next(reader)
    except StopIteration:
        return issues

    expected_count = len(headers) if headers else header_count
    for line_number, row in enumerate(reader, start=2):
        if not row or all(not cell.strip() for cell in row):
            continue
        actual_count = len(row)
        if actual_count == expected_count:
            continue

        status = "Too many fields" if actual_count > expected_count else "Too few fields"
        preview = ",".join(row)[:120]
        message = (
            f"Row {line_number} contains {actual_count} values but the header contains "
            f"{expected_count} columns. {status}. "
            "A comma in an address may not be correctly quoted."
        )
        if _issue_exists(issues, line_number, message):
            continue
        issue = build_issue(
            issue_id=f"csv:structure:{line_number}",
            category="csv_structure",
            field=None,
            row=line_number,
            original_value=preview,
            proposed_value="(manual review required)",
            reason=message,
            safe=False,
            blocking=True,
            confidence=1.0,
        )
        issue["address_confidence"] = "Invalid Structure"
        issues.append(issue)

    return issues


def _scan_raw_csv_issues(
    lines: list[str],
    header_line_index: int,
    expected_count: int,
) -> list[tuple[int, str, str, bool]]:
    findings: list[tuple[int, str, str, bool]] = []
    row_number = header_line_index + 2
    index = header_line_index + 1

    while index < len(lines):
        if not lines[index].strip():
            index += 1
            row_number += 1
            continue

        merged = lines[index]
        tokens, in_quotes = _parse_csv_line_with_state(merged)
        lookahead = index + 1

        while in_quotes and lookahead < len(lines):
            merged += "\n" + lines[lookahead]
            tokens, in_quotes = _parse_csv_line_with_state(merged)
            lookahead += 1

        preview = merged[:120]
        if in_quotes:
            findings.append((
                row_number,
                f"Row {row_number} contains an unclosed quotation mark.",
                preview,
                True,
            ))
        elif len(tokens) != expected_count:
            status = "Too many fields" if len(tokens) > expected_count else "Too few fields"
            findings.append((
                row_number,
                (
                    f"Row {row_number} contains {len(tokens)} values but the header contains "
                    f"{expected_count} columns. {status}. "
                    "A comma in an address may not be correctly quoted."
                ),
                preview,
                True,
            ))
        elif "\n" in merged and len(tokens) == expected_count:
            findings.append((
                row_number,
                (
                    f"Row {row_number} contains embedded line breaks. "
                    "Verify address commas and quoting."
                ),
                preview,
                False,
            ))

        index = lookahead
        row_number += 1

    return findings


def _parse_csv_line(line: str) -> list[str]:
    tokens, _ = _parse_csv_line_with_state(line)
    return tokens


def _parse_csv_line_with_state(line: str) -> tuple[list[str], bool]:
    tokens: list[str] = []
    current = ""
    in_quotes = False
    index = 0
    length = len(line)

    while index < length:
        char = line[index]
        if in_quotes:
            if char == '"':
                if index + 1 < length and line[index + 1] == '"':
                    current += '"'
                    index += 2
                    continue
                in_quotes = False
                index += 1
                continue
            current += char
            index += 1
            continue

        if char == '"':
            in_quotes = True
            index += 1
            continue
        if char == ",":
            tokens.append(current)
            current = ""
            index += 1
            continue
        current += char
        index += 1

    tokens.append(current)
    return tokens, in_quotes


def _first_non_blank_line_index(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if line.strip():
            return index
    return None


def _issue_exists(issues: list[dict[str, Any]], row: int, message: str) -> bool:
    return any(issue.get("row") == row and issue.get("reason") == message for issue in issues)
