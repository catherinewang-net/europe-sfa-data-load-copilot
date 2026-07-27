"""Template column validation against reference CSV headers."""

from __future__ import annotations

from collections import Counter
from typing import Any


def validate_template(
    uploaded_headers: list[str],
    expected_headers: list[str],
) -> dict[str, Any]:
    """Compare uploaded CSV headers against a reference template."""
    headers = list(uploaded_headers)
    expected = list(expected_headers)

    header_counts = Counter(headers)
    duplicate_columns = sorted(
        name for name, count in header_counts.items() if count > 1
    )

    actual_set = set(headers)
    expected_set = set(expected)

    matching_headers = [col for col in expected if col in actual_set]
    missing_columns = [col for col in expected if col not in actual_set]
    extra_columns = list(dict.fromkeys(
        col for col in headers if col not in expected_set
    ))

    order_differences = _find_order_differences(headers, expected)

    if expected:
        match_percentage = round((len(matching_headers) / len(expected)) * 100, 1)
    else:
        match_percentage = 100.0

    template_match = (
        not missing_columns
        and not extra_columns
        and not duplicate_columns
        and not order_differences
    )

    return {
        "template_match": template_match,
        "matching_headers": matching_headers,
        "missing_columns": missing_columns,
        "extra_columns": extra_columns,
        "duplicate_columns": duplicate_columns,
        "order_differences": order_differences,
        "match_percentage": match_percentage,
        "uploaded_column_count": len(headers),
        "expected_column_count": len(expected),
    }


def _find_order_differences(
    uploaded_headers: list[str],
    expected_headers: list[str],
) -> list[dict[str, Any]]:
    """Identify headers present in both lists but in different positions."""
    differences: list[dict[str, Any]] = []

    for index, header in enumerate(expected_headers):
        if header not in uploaded_headers:
            continue
        actual_index = uploaded_headers.index(header)
        if actual_index != index:
            differences.append({
                "header": header,
                "expected_position": index + 1,
                "actual_position": actual_index + 1,
            })

    return differences


def detect_upload_method_mismatch(
    uploaded_headers: list[str],
    selected_method: str,
    template: str,
    selected_result: dict[str, Any],
    load_reference_headers,
    get_other_upload_method,
) -> str | None:
    """Detect if the uploaded file better matches the other upload method."""
    other_method = get_other_upload_method(selected_method)

    try:
        other_headers, _ = load_reference_headers(other_method, template)
    except (FileNotFoundError, ValueError):
        return None

    other_result = validate_template(uploaded_headers, other_headers)
    selected_match = selected_result["match_percentage"]
    other_match = other_result["match_percentage"]

    if other_match > selected_match + 10 and other_match >= 50:
        return (
            f"This file appears to be formatted for the {other_method} "
            f"rather than {selected_method}."
        )

    return None
