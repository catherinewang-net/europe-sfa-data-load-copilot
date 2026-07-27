"""Temporary Workbench field metadata debug panel."""

from __future__ import annotations

import streamlit as st

from services.workbench_field_catalog_service import build_field_metadata_debug_report


def render_field_metadata_debug(
    template_name: str,
    load_operation: str | None,
    skipped_headers: list[str] | None = None,
) -> None:
    with st.expander("Field Metadata Debug", expanded=False):
        report = build_field_metadata_debug_report(template_name, load_operation)
        st.markdown(
            f"**Template:** `{report.get('template_name')}`  \n"
            f"**Resolved object:** `{report.get('object_name')}`  \n"
            f"**Template_Config object:** `{report.get('template_config_object')}`  \n"
            f"**Metadata available:** {report.get('metadata_available')}  \n"
            f"**Adapter raw field count:** {report.get('adapter_raw_field_count')}  \n"
            f"**Catalog / dropdown field count:** {report.get('dropdown_field_count')}  \n"
            f"**Metadata fields not in checklist:** {report.get('metadata_fields_not_in_checklist_count', 0)}  \n"
            f"**Checklist fields found:** "
            f"{report.get('checklist_fields_found_count', 0)}/"
            f"{report.get('checklist_field_count', 0)}  \n"
            f"**Template_Config limits dropdown:** {report.get('template_config_limits_dropdown')}  \n"
            f"**Lookup fields excluded:** {report.get('lookup_fields_excluded')}"
        )

        if report.get("object_resolution_failed"):
            st.error("Object resolution failed — template could not be mapped to a Salesforce object.")

        invalid_xml = report.get("invalid_xml_fields") or []
        if invalid_xml:
            st.markdown("**Invalid XML metadata files:**")
            for item in invalid_xml:
                st.warning(f"`{item['api_name']}` — {item['message']}")

        mismatches = report.get("verification_mismatches") or []
        if mismatches:
            st.markdown("**Verification mismatch classifications:**")
            by_class: dict[str, list[dict]] = {}
            for item in mismatches:
                by_class.setdefault(item["classification"], []).append(item)
            for classification in (
                "Found in metadata",
                "Missing from metadata",
                "Present but filtered from UI",
                "Invalid XML",
                "Possible spelling mismatch",
                "Object resolution failed",
            ):
                items = by_class.get(classification, [])
                if not items:
                    continue
                st.markdown(f"*{classification} ({len(items)}):*")
                for item in items:
                    if classification == "Found in metadata":
                        continue
                    st.markdown(f"- `{item['field']}` — {item['detail']}")

        spelling = report.get("possible_spelling_mismatches") or {}
        if spelling:
            st.markdown("**Possible spelling / capitalization issues:**")
            for field_name, suggestions in spelling.items():
                st.markdown(f"- `{field_name}` → similar: {', '.join(f'`{s}`' for s in suggestions)}")

        skipped = skipped_headers or []
        st.markdown(f"**Skipped blank CSV headers ({len(skipped)}):**")
        if skipped:
            for header in skipped:
                st.markdown(f"- `{header}`")
        else:
            st.markdown("- None")

        removed = report.get("removed_by_filtering") or []
        st.markdown("**Fields removed by filtering:**")
        if removed:
            for item in removed:
                st.markdown(f"- `{item['api_name']}` — {item['reason']}")
        else:
            st.markdown("- None")

        st.markdown("**Filtering rules currently applied:**")
        for rule in report.get("filtering_rules_applied", []):
            st.markdown(f"- {rule}")

        found = report.get("checklist_fields_found") or []
        st.markdown(f"**Verification checklist fields found ({len(found)}):**")
        if found:
            st.code(", ".join(found))
        else:
            st.markdown("- None")

        missing = report.get("missing_checklist_fields") or []
        st.markdown(f"**Missing from verification checklist ({len(missing)}):**")
        if missing:
            st.code(", ".join(missing))
        else:
            st.markdown("- None")

        picklists = report.get("picklist_fields_discovered") or []
        st.markdown(f"**Picklist fields discovered ({len(picklists)}):**")
        if picklists:
            for field in picklists:
                sample = field.get("allowed_values_sample") or []
                sample_text = ", ".join(sample)
                if field.get("allowed_value_count", 0) > len(sample):
                    sample_text = f"{sample_text}, ..."
                st.markdown(
                    f"- `{field['api_name']}` — {field['label']} — "
                    f"{field['field_type']} "
                    f"({field.get('value_set_source') or 'Unknown'}"
                    f"{': ' + field['value_set_name'] if field.get('value_set_name') else ''}; "
                    f"{field.get('allowed_value_count', 0)} values"
                    f"{': ' + sample_text if sample_text else ''})"
                )
        else:
            st.markdown("- None")

        lookups = report.get("lookup_fields_discovered") or []
        st.markdown(f"**Lookup / reference fields discovered ({len(lookups)}):**")
        if lookups:
            for field in lookups:
                st.markdown(
                    f"- `{field['api_name']}` — {field['label']} — "
                    f"{field['field_type']} -> `{field['reference_to']}`"
                )
        else:
            st.markdown("- None")

        dates = report.get("date_fields_discovered") or []
        st.markdown(f"**Date / DateTime fields discovered ({len(dates)}):**")
        if dates:
            for field in dates:
                st.markdown(f"- `{field['api_name']}` — {field['label']} — {field['field_type']}")
        else:
            st.markdown("- None")

        booleans = report.get("boolean_fields_discovered") or []
        st.markdown(f"**Boolean fields discovered ({len(booleans)}):**")
        if booleans:
            for field in booleans:
                st.markdown(f"- `{field['api_name']}` — {field['label']} — {field['field_type']}")
        else:
            st.markdown("- None")

        external_ids = report.get("external_id_fields_discovered") or []
        st.markdown(f"**External ID fields discovered ({len(external_ids)}):**")
        if external_ids:
            for field in external_ids:
                st.markdown(f"- `{field['api_name']}` — {field['label']} — {field['field_type']}")
        else:
            st.markdown("- None")

        extra_metadata = report.get("metadata_fields_not_in_checklist") or []
        st.markdown(f"**Additional metadata fields not in checklist ({len(extra_metadata)}):**")
        if extra_metadata:
            st.code(", ".join(extra_metadata[:40]) + (" ..." if len(extra_metadata) > 40 else ""))
        else:
            st.markdown("- None")

        validation_hints = report.get("special_validation_hints") or []
        st.markdown(f"**Special validation hints ({len(validation_hints)}):**")
        if validation_hints:
            by_type: dict[str, list[dict]] = {}
            for item in validation_hints:
                by_type.setdefault(item["validation_type"], []).append(item)
            for validation_type in sorted(by_type):
                items = by_type[validation_type]
                st.markdown(f"*{validation_type} ({len(items)}):*")
                for item in items[:8]:
                    st.markdown(f"- `{item['api_name']}` — {item['hint']}")
                if len(items) > 8:
                    st.markdown(f"- ... and {len(items) - 8} more")
        else:
            st.markdown("- None")

        type_summary = report.get("field_type_summary") or {}
        st.markdown("**Field type summary:**")
        if type_summary:
            for field_type, count in sorted(type_summary.items(), key=lambda item: (-item[1], item[0])):
                st.markdown(f"- {field_type}: {count}")
        else:
            st.markdown("- None")

        duplicates = report.get("duplicate_api_names") or []
        if duplicates:
            st.warning(f"Duplicate API names: {', '.join(duplicates)}")

        missing_labels = report.get("fields_with_missing_labels") or []
        if missing_labels:
            st.caption(f"Fields using API name as label (sample): {', '.join(missing_labels[:10])}")

        unknown_types = report.get("fields_with_unknown_types") or []
        if unknown_types:
            st.caption(f"Fields with unknown types (sample): {', '.join(unknown_types[:10])}")

        sample = report.get("sample_fields") or []
        if sample:
            st.markdown("**Sample dropdown labels:**")
            for label in sample:
                st.markdown(f"- {label}")


def render_account_field_metadata_debug(
    template_name: str,
    load_operation: str | None,
    skipped_headers: list[str] | None = None,
) -> None:
    """Backward-compatible alias for the generic field metadata debug panel."""
    render_field_metadata_debug(template_name, load_operation, skipped_headers)
