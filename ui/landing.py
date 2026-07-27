"""PepFlow AI landing hero."""

from __future__ import annotations

import streamlit as st

from core.config import APP_DESCRIPTION, APP_NAME, APP_TAGLINE


def render_landing_hero() -> None:
    """Render the product landing header above connection controls."""
    st.markdown(
        f"""
        <div class="pepflow-hero">
            <h1 class="pepflow-hero-title">{APP_NAME}</h1>
            <p class="pepflow-hero-tagline">{APP_TAGLINE}</p>
            <p class="pepflow-hero-description">{APP_DESCRIPTION}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
