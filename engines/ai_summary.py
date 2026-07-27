"""AI summary — explains deterministic results in plain English."""

from __future__ import annotations

from typing import Any


def generate_copilot_summary(
    upload_method: str,
    template: str,
    validation_result: dict[str, Any] | None = None,
    preparation_result: dict[str, Any] | None = None,
    readiness: dict[str, Any] | None = None,
) -> str:
    """Build a plain-English executive summary of the copilot session."""
    lines = [
        "## PepFlow AI Summary\n",
        f"**Upload method:** {upload_method}",
        f"**Template:** {template}\n",
    ]

    if preparation_result:
        summary = preparation_result.get("summary", {})
        lines.append("### Automatic preparation")
        for category, count in summary.items():
            if count:
                lines.append(f"- {category.replace('_', ' ').title()}: {count}")
        lines.append("")

    if validation_result:
        errors = [
            i for i in validation_result.get("issues", [])
            if i.get("severity") == "error"
        ]
        warnings = [
            i for i in validation_result.get("issues", [])
            if i.get("severity") == "warning"
        ]
        lines.append("### Validation")
        lines.append(f"- Errors: {len(errors)}")
        lines.append(f"- Warnings: {len(warnings)}")

        manual = validation_result.get("manual_review", [])
        if manual:
            lines.append(f"- Manual review items: {len(manual)}")
        lines.append("")

    if readiness:
        lines.append(f"### Upload readiness: {readiness['status']}")
        lines.append(readiness.get("explanation", ""))

    return "\n".join(lines)
