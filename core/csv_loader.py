"""CSV loading utilities."""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

import pandas as pd

_BLANK_HEADER_PATTERN = re.compile(r"^Unnamed:\s*\d+$", re.IGNORECASE)


def is_blank_header(header: str) -> bool:
    """Return True for empty, whitespace-only, or pandas placeholder headers."""
    text = str(header).strip()
    if not text:
        return True
    return bool(_BLANK_HEADER_PATTERN.match(text))


def filter_blank_header_columns(
    df: pd.DataFrame,
    raw_headers: list[str],
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Drop columns whose headers are blank or unusable placeholders."""
    skipped_headers: list[str] = []
    keep_indices: list[int] = []
    for index, header in enumerate(raw_headers):
        if is_blank_header(header):
            skipped_headers.append(str(header))
            continue
        keep_indices.append(index)

    if not keep_indices:
        raise ValueError("The uploaded CSV file has no usable column headers.")

    filtered_headers = [str(raw_headers[index]).strip() for index in keep_indices]
    if len(keep_indices) == len(raw_headers):
        aligned = df.copy()
        aligned.columns = filtered_headers
        return aligned, filtered_headers, skipped_headers

    filtered_df = df.iloc[:, keep_indices].copy()
    filtered_df.columns = filtered_headers
    return filtered_df, filtered_headers, skipped_headers


def sanitize_uploaded_columns(
    df: pd.DataFrame,
    raw_headers: list[str] | None = None,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Align dataframe columns to trimmed, valid uploaded headers."""
    headers = list(raw_headers or df.columns)
    df_copy = df.copy()
    if len(df_copy.columns) != len(headers):
        headers = [str(column) for column in df_copy.columns]
    df_copy, valid_headers, skipped = filter_blank_header_columns(df_copy, headers)
    return df_copy, valid_headers, skipped


def read_csv_headers(file_path: Path) -> list[str]:
    """Read the header row from a CSV file on disk."""
    if not file_path.exists():
        raise FileNotFoundError(file_path.name)

    with open(file_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        try:
            headers = next(reader)
        except StopIteration as exc:
            raise ValueError(f"Reference template is empty: {file_path.name}") from exc

    if not headers or all(not col.strip() for col in headers):
        raise ValueError(f"Reference template has no column headers: {file_path.name}")

    return headers


def load_uploaded_csv(uploaded_file) -> tuple[pd.DataFrame, list[str]]:
    """Load an uploaded CSV preserving all values as text."""
    content = uploaded_file.getvalue().decode("utf-8-sig")
    if not content.strip():
        raise ValueError("The uploaded CSV file is empty.")

    reader = csv.reader(io.StringIO(content))
    try:
        raw_headers = next(reader)
    except StopIteration as exc:
        raise ValueError("The uploaded CSV file is empty.") from exc

    if not raw_headers or all(is_blank_header(col) for col in raw_headers):
        raise ValueError("The uploaded CSV file has no column headers.")

    df = pd.read_csv(io.StringIO(content), dtype=str, keep_default_na=False)
    df, raw_headers, skipped_headers = filter_blank_header_columns(df, raw_headers)
    df.attrs["raw_headers"] = raw_headers
    df.attrs["skipped_headers"] = skipped_headers

    return df, raw_headers
