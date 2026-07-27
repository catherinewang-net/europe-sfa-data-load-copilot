"""Resolve preparation task selections into workflow behavior."""

from __future__ import annotations

from core.config import DEFAULT_PREPARATION_TASK, PREPARATION_TASKS


def get_preparation_task_options() -> list[str]:
    return list(PREPARATION_TASKS.keys())


def get_default_preparation_task() -> str:
    return DEFAULT_PREPARATION_TASK


def get_preparation_task_description(preparation_task: str | None) -> str | None:
    if not preparation_task:
        return None
    return PREPARATION_TASKS[preparation_task]["description"]


def resolve_load_operation(preparation_task: str | None) -> str | None:
    if not preparation_task:
        return None
    return PREPARATION_TASKS[preparation_task]["load_operation"]


def is_preparation_only(preparation_task: str | None) -> bool:
    if not preparation_task:
        return False
    return bool(PREPARATION_TASKS[preparation_task]["preparation_only"])


def preparation_only_message(upload_method: str | None) -> str:
    tool = upload_method or "the selected tool"
    return (
        f"Your file has been prepared for {tool}. "
        "Insert or Update requirements were not checked."
    )


def load_action_not_evaluated_message(upload_method: str | None) -> str:
    tool = upload_method or "the selected tool"
    return f"Prepared for {tool}. Load-action-specific checks were not performed."
