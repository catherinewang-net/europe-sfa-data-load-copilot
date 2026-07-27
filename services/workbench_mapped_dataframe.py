"""Build mapped Workbench dataframes from user mapping decisions."""

from __future__ import annotations

from typing import Any

import pandas as pd

from services.constants import (
    MAPPING_ACTION_EXCLUDE,
    MAPPING_ACTION_KEEP,
    MAPPING_ACTION_MAP,
    MAPPING_STATUS_CONFIRMED,
    MAPPING_STATUS_EXACT_API,
    MAPPING_STATUS_EXCLUDED,
)
from services.workbench_mapping_service import (
    _row_column,
    _row_is_resolved,
    detect_target_collisions,
    get_excluded_columns,
    is_valid_mapping_row,
)


def build_mapped_df(
    original_df: pd.DataFrame,
    mapping_rows: list[dict[str, Any]],
) -> pd.DataFrame:
    """Apply keep/map/exclude decisions to a copy of the uploaded dataframe."""
    rows = [row for row in mapping_rows if is_valid_mapping_row(row)]
    collisions = detect_target_collisions(rows)
    if collisions:
        raise ValueError(collisions[0]["message"])

    working = original_df.copy()
    excluded = get_excluded_columns(rows)
    drop_columns = [column for column in excluded if column in working.columns]
    if drop_columns:
        working = working.drop(columns=drop_columns)

    rename_map: dict[str, str] = {}
    for row in rows:
        column = _row_column(row)
        if column not in working.columns:
            continue
        if row.get("status") == MAPPING_STATUS_EXCLUDED or row.get("action") == MAPPING_ACTION_EXCLUDE:
            continue
        if not _row_is_resolved(row):
            continue

        action = row.get("action")
        if action == MAPPING_ACTION_KEEP or row.get("status") == MAPPING_STATUS_EXACT_API:
            rename_map[column] = column
            continue

        if action == MAPPING_ACTION_MAP or row.get("status") == MAPPING_STATUS_CONFIRMED:
            target = row.get("confirmed_api_field")
            if not target:
                raise ValueError(f"Column `{column}` is mapped but has no target API field.")
            rename_map[column] = target

    if rename_map:
        working = working.rename(columns=rename_map)

    return working
