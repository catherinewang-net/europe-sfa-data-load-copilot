"""Backward-compatible re-exports — prefer engines.data_preparation."""

from engines.data_preparation import apply_preparation as convert_to_workbench
from engines.template_comparison import is_dit_format

__all__ = ["convert_to_workbench", "is_dit_format"]
