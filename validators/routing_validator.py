"""Config-driven routing and customer-to-route validation."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

_RULES_PATH = Path(__file__).resolve().parent.parent / "rules" / "routing_rules.json"


def _load_routing_rules() -> dict[str, Any]:
    if not _RULES_PATH.exists():
        return {"templates": {}}
    with _RULES_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def _parse_date(value: Any) -> date | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def validate_routing_rules(
    df: pd.DataFrame,
    template: str,
) -> dict[str, Any]:
    """Validate routing import and customer-to-route business rules from config."""
    config = _load_routing_rules().get("templates", {}).get(template)
    if not config:
        return {"issues": [], "manual_review": [], "checked": False, "template": template}

    issues: list[dict[str, Any]] = []
    manual_review: list[dict[str, Any]] = []

    if template == "Routing Import":
        _validate_routing_import(df, config, issues, manual_review)
    elif template == "Customer to Route":
        _validate_customer_to_route(df, config, issues, manual_review)

    return {
        "issues": issues,
        "manual_review": manual_review,
        "checked": True,
        "template": template,
        "blocking_count": sum(1 for item in manual_review if item.get("blocking")),
    }


def _validate_routing_import(
    df: pd.DataFrame,
    config: dict[str, Any],
    issues: list[dict[str, Any]],
    manual_review: list[dict[str, Any]],
) -> None:
    route_field = config.get("route_field")
    customer_field = config.get("customer_field")
    invalid_values = {str(value).strip() for value in config.get("invalid_route_values", [])}
    start_fields = [field for field in config.get("start_date_fields", []) if field in df.columns]
    end_fields = [field for field in config.get("end_date_fields", []) if field in df.columns]
    sequence_fields = [field for field in config.get("sequence_fields", []) if field in df.columns]
    today = date.today()

    if route_field and route_field in df.columns:
        for idx, raw_value in df[route_field].items():
            value = str(raw_value).strip()
            if not value:
                continue
            if value in invalid_values or value.lstrip("0") == "":
                item = _manual_item(
                    row=idx + 2,
                    field=route_field,
                    referenced_value=value,
                    parent_object="Route",
                    reason=f"Route ID must not be zero (row {idx + 2}).",
                    blocking=True,
                    category="routing_invalid_route_id",
                )
                issues.append(item)
                manual_review.append(item)

    for end_field in end_fields:
        for idx, raw_value in df[end_field].items():
            parsed = _parse_date(raw_value)
            if parsed and parsed < today:
                item = _manual_item(
                    row=idx + 2,
                    field=end_field,
                    referenced_value=str(raw_value),
                    parent_object="Route",
                    reason=f"Routing end date is in the past (row {idx + 2}).",
                    blocking=True,
                    category="routing_past_date",
                )
                issues.append(item)
                manual_review.append(item)

    if config.get("detect_overlapping_periods") and customer_field in df.columns and start_fields and end_fields:
        periods: dict[tuple[str, str], list[tuple[int, date, date]]] = {}
        start_field = start_fields[0]
        end_field = end_fields[0]
        for idx, row in df.iterrows():
            customer = str(row.get(customer_field, "")).strip()
            route = str(row.get(route_field, "")).strip() if route_field else ""
            start = _parse_date(row.get(start_field))
            end = _parse_date(row.get(end_field))
            if not customer or not route or not start or not end:
                continue
            key = (customer, route)
            periods.setdefault(key, []).append((idx + 2, start, end))

        for (customer, route), entries in periods.items():
            ordered = sorted(entries, key=lambda item: item[1])
            for index in range(len(ordered) - 1):
                row_a, start_a, end_a = ordered[index]
                row_b, start_b, _end_b = ordered[index + 1]
                if start_b <= end_a:
                    item = _manual_item(
                        row=row_b,
                        field=start_field,
                        referenced_value=f"{customer}/{route}",
                        parent_object="Route",
                        reason=(
                            f"Overlapping route periods for customer '{customer}' and route '{route}' "
                            f"(rows {row_a} and {row_b})."
                        ),
                        blocking=True,
                        category="routing_overlap",
                    )
                    issues.append(item)
                    manual_review.append(item)

    if config.get("require_unique_sequence_per_route_day") and route_field in df.columns:
        seen: dict[tuple[str, str, str], int] = {}
        for idx, row in df.iterrows():
            route = str(row.get(route_field, "")).strip()
            if not route:
                continue
            for sequence_field in sequence_fields:
                sequence = str(row.get(sequence_field, "")).strip()
                if not sequence:
                    continue
                key = (route, sequence_field, sequence)
                if key in seen:
                    item = _manual_item(
                        row=idx + 2,
                        field=sequence_field,
                        referenced_value=sequence,
                        parent_object="Route",
                        reason=(
                            f"Duplicate route sequence '{sequence}' for route '{route}' on "
                            f"{sequence_field} (rows {seen[key]} and {idx + 2})."
                        ),
                        blocking=True,
                        category="routing_duplicate_sequence",
                    )
                    issues.append(item)
                    manual_review.append(item)
                else:
                    seen[key] = idx + 2


def _validate_customer_to_route(
    df: pd.DataFrame,
    config: dict[str, Any],
    issues: list[dict[str, Any]],
    manual_review: list[dict[str, Any]],
) -> None:
    duplicate_fields = [field for field in config.get("duplicate_key_fields", []) if field in df.columns]
    required_fields = [field for field in config.get("required_fields", []) if field in df.columns]
    threshold = int(config.get("large_file_row_threshold", 0))

    for field in required_fields:
        for idx, raw_value in df[field].items():
            if not str(raw_value).strip():
                item = _manual_item(
                    row=idx + 2,
                    field=field,
                    referenced_value="",
                    parent_object="Route",
                    reason=f"Required route reference is blank (row {idx + 2}).",
                    blocking=True,
                    category="customer_to_route_required_route",
                )
                issues.append(item)
                manual_review.append(item)

    if duplicate_fields:
        seen: dict[tuple[str, ...], int] = {}
        for idx, row in df.iterrows():
            key = tuple(str(row.get(field, "")).strip() for field in duplicate_fields)
            if not any(key):
                continue
            if key in seen:
                item = _manual_item(
                    row=idx + 2,
                    field=", ".join(duplicate_fields),
                    referenced_value=" / ".join(key),
                    parent_object="Route",
                    reason=(
                        f"Duplicate customer-to-route key ({' / '.join(key)}) "
                        f"(rows {seen[key]} and {idx + 2})."
                    ),
                    blocking=True,
                    category="customer_to_route_duplicate",
                )
                issues.append(item)
                manual_review.append(item)
            else:
                seen[key] = idx + 2

    if threshold and len(df) > threshold:
        item = {
            "validator": "routing",
            "severity": "warning",
            "field": None,
            "message": (
                f"Customer to Route file has {len(df)} rows, exceeding the recommended "
                f"threshold of {threshold}. Consider splitting the upload."
            ),
            "blocking": False,
            "category": "customer_to_route_large_file",
        }
        issues.append(item)


def _manual_item(
    *,
    row: int,
    field: str,
    referenced_value: str,
    parent_object: str,
    reason: str,
    blocking: bool,
    category: str,
) -> dict[str, Any]:
    return {
        "validator": "routing",
        "severity": "error" if blocking else "warning",
        "row": row,
        "field": field,
        "referenced_value": referenced_value,
        "parent_object": parent_object,
        "upload_order": "Resolve in source file before upload",
        "reason": reason,
        "message": reason,
        "blocking": blocking,
        "category": category,
    }
