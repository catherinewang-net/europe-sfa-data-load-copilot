"""Upload readiness assessment."""

from __future__ import annotations

from typing import Any

from services.readiness_service import evaluate_upload_readiness


def assess_readiness(
    validation_result: dict[str, Any] | None = None,
    preparation_result: dict[str, Any] | None = None,
    comparison_result: dict[str, Any] | None = None,
    correction_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Determine whether the file is ready for upload."""
    return evaluate_upload_readiness(
        validation_result=validation_result,
        preparation_result=preparation_result,
        comparison_result=comparison_result,
        correction_plan=correction_plan,
    )