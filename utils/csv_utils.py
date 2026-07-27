"""Backward-compatible re-exports — prefer core.csv_loader."""

from core.csv_loader import load_uploaded_csv, read_csv_headers

__all__ = ["load_uploaded_csv", "read_csv_headers"]
