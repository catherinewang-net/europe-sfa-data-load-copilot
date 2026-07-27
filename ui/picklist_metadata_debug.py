"""Temporary picklist metadata debug panel."""

from __future__ import annotations

import streamlit as st

from services.picklist_field_catalog import build_picklist_metadata_debug_report


def render_picklist_metadata_debug(
    object_name: str | None,
    record_type_name: str | None = None,
) -> None:
    if not object_name:
        return

    with st.expander("Picklist Metadata Debug", expanded=False):
        report = build_picklist_metadata_debug_report(object_name, record_type_name)
        st.markdown(
            f"**Resolved object:** `{report.get('object_name')}`  \n"
            f"**Record type:** `{report.get('record_type_name') or '—'}`  \n"
            f"**Object field count:** {report.get('object_field_count')}  \n"
            f"**Picklist fields:** {report.get('picklist_field_count')}  \n"
            f"**Multipicklist fields:** {report.get('multipicklist_field_count')}"
        )

        missing = report.get("fields_with_missing_value_set_metadata") or []
        st.markdown(f"**Fields with missing value-set metadata ({len(missing)}):**")
        if missing:
            st.code(", ".join(missing))
        else:
            st.markdown("- None")

        for field in report.get("fields", []):
            st.markdown(
                f"- `{field['field_api_name']}` ({field['field_type']}) — "
                f"{field['value_set_source']}"
                + (f" `{field['value_set_name']}`" if field.get("value_set_name") else "")
                + f" — allowed values: {len(field.get('allowed_values', []))}"
                + f" — record-type restrictions: {field.get('record_type_restrictions_available')}"
            )
