"""Preparation task card selector for Step 3."""

from __future__ import annotations

import streamlit as st

from core.config import PREPARATION_TASKS
from services.preparation_task_service import (
    get_default_preparation_task,
    get_preparation_task_options,
)

SESSION_KEY = "preparation_task_selection"


def render_preparation_task_selector() -> str:
    """Render selectable preparation task cards and return the selected task key."""
    options = get_preparation_task_options()
    if SESSION_KEY not in st.session_state:
        st.session_state[SESSION_KEY] = get_default_preparation_task()

    cols = st.columns(len(options))
    for index, (col, key) in enumerate(zip(cols, options)):
        task = PREPARATION_TASKS[key]
        selected = st.session_state[SESSION_KEY] == key
        card_class = "prep-task-card prep-task-card-selected" if selected else "prep-task-card"
        with col:
            st.markdown(
                f"""
                <div class="{card_class}">
                    <div class="prep-task-title">{task["label"]}</div>
                    <div class="prep-task-desc">{task["description"]}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button(
                task["label"],
                key=f"prep_task_select_{index}",
                use_container_width=True,
            ):
                st.session_state[SESSION_KEY] = key
                st.rerun()

    return st.session_state[SESSION_KEY]
