"""Read-only batched Salesforce record lookup by identifier field."""

from __future__ import annotations

import re
from typing import Any

from clients.salesforce_client import SalesforceQueryClient

BATCH_SIZE = 200
_SOQL_LITERAL_ESCAPE = re.compile(r"([\\'])")

MatchRecord = dict[str, str]


def escape_soql_literal(value: str) -> str:
    return _SOQL_LITERAL_ESCAPE.sub(r"\\\1", value.replace("\n", " ").replace("\r", " "))


def lookup_records_by_field(
    client: SalesforceQueryClient,
    object_name: str,
    identifier_field: str,
    values: list[str],
    *,
    include_salesforce_id: bool = True,
) -> dict[str, Any]:
    """
    Look up records by identifier values using batched SOQL queries.

    Returns a mapping of normalized identifier value -> list of matching records.
    Never performs create/update/delete operations.
    """
    deduped_values = _dedupe_values(values)
    if not deduped_values:
        return {
            "object_name": object_name,
            "identifier_field": identifier_field,
            "queried_value_count": 0,
            "batch_count": 0,
            "matches_by_value": {},
            "query_errors": [],
        }

    select_fields = [identifier_field]
    if include_salesforce_id and identifier_field != "Id":
        select_fields.insert(0, "Id")

    matches_by_value: dict[str, list[MatchRecord]] = {}
    query_errors: list[str] = []
    batch_count = 0

    for batch in _batch_values(deduped_values, BATCH_SIZE):
        batch_count += 1
        quoted = ", ".join(f"'{escape_soql_literal(value)}'" for value in batch)
        soql = (
            f"SELECT {', '.join(select_fields)} "
            f"FROM {object_name} "
            f"WHERE {identifier_field} IN ({quoted})"
        )
        try:
            payload = client.query(soql)
        except Exception as exc:
            query_errors.append(str(exc))
            continue

        for record in payload.get("records", []):
            raw_value = record.get(identifier_field)
            if raw_value is None:
                continue
            normalized = _normalize_value(raw_value)
            entry = {field: str(record.get(field, "")) for field in select_fields if field in record}
            matches_by_value.setdefault(normalized, []).append(entry)

    return {
        "object_name": object_name,
        "identifier_field": identifier_field,
        "queried_value_count": len(deduped_values),
        "batch_count": batch_count,
        "matches_by_value": matches_by_value,
        "query_errors": query_errors,
    }


def _dedupe_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for raw in values:
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        normalized = _normalize_value(text)
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(text)
    return deduped


def _normalize_value(value: Any) -> str:
    return str(value).strip().casefold()


def _batch_values(values: list[str], batch_size: int) -> list[list[str]]:
    return [values[index:index + batch_size] for index in range(0, len(values), batch_size)]
