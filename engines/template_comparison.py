"""Template comparison against reference CSV headers."""

from __future__ import annotations

from typing import Any

from services.metadata_provider_factory import get_metadata_adapter
from core.reference_templates import (
    get_other_upload_method,
    load_reference_headers,
)
from services.header_matching_service import analyze_header_matching, enrich_template_comparison
from services.template_service import resolve_template
from validators.template_validator import (
    detect_upload_method_mismatch,
    validate_template,
)


def compare_to_reference(
    uploaded_headers: list[str],
    upload_method: str,
    template: str,
    load_operation: str | None = None,
) -> dict[str, Any]:
    """Compare uploaded headers to the selected reference template."""
    expected_headers, reference_path = load_reference_headers(upload_method, template)
    base_result = validate_template(uploaded_headers, expected_headers)

    template_context = resolve_template(template)
    valid_fields: set[str] = set()
    if template_context and template_context.salesforce_object:
        valid_fields = set(
            get_metadata_adapter().get_object_fields(template_context.salesforce_object).keys()
        )

    analysis = analyze_header_matching(
        uploaded_headers,
        expected_headers,
        upload_method,
        template_context,
        load_operation,
        valid_object_fields=valid_fields,
    )
    result = enrich_template_comparison(base_result, analysis)

    mismatch_warning = detect_upload_method_mismatch(
        uploaded_headers,
        upload_method,
        template,
        result,
        load_reference_headers,
        get_other_upload_method,
    )

    return {
        "comparison": result,
        "reference_path": reference_path,
        "mismatch_warning": mismatch_warning,
        "upload_method": upload_method,
        "template": template,
    }


def is_dit_format(uploaded_headers: list[str], template: str) -> bool:
    """Return True when uploaded headers match the DIT reference template."""
    try:
        dit_headers, _ = load_reference_headers("Data Import Tool", template)
    except (FileNotFoundError, ValueError):
        return False

    result = validate_template(uploaded_headers, dit_headers)
    return result["match_percentage"] >= 50
