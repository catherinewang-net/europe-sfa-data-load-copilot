"""Generate human-readable validation summaries."""

from __future__ import annotations

from collections import Counter
from typing import Any


def generate_summary(reports: list[dict]) -> str:
    """Build a plain-language summary of validation results across all files."""
    if not reports:
        return "No files were validated."

    lines: list[str] = []
    total_errors = 0
    total_warnings = 0
    total_corrections = 0

    lines.append("## PepFlow AI Validation Summary\n")

    for report in reports:
        filename = report.get("filename", "unknown")
        template = report.get("template", "unknown")
        issues = report.get("issues", [])
        corrections = report.get("corrections", [])

        errors = [i for i in issues if i.get("severity") == "error"]
        warnings = [i for i in issues if i.get("severity") == "warning"]
        total_errors += len(errors)
        total_warnings += len(warnings)
        total_corrections += len(corrections)

        status = "PASS" if not errors else "FAIL"
        lines.append(f"### {filename} ({template}) — {status}")
        lines.append(f"- Rows: {report.get('row_count', 0)}")
        lines.append(f"- Errors: {len(errors)} | Warnings: {len(warnings)} | Auto-corrections: {len(corrections)}")

        if errors:
            lines.append("\n**Top errors:**")
            for issue in errors[:5]:
                row = issue.get("row", "—")
                field = issue.get("field", "—")
                msg = issue.get("message", "")
                lines.append(f"  - Row {row}, `{field}`: {msg}")
            if len(errors) > 5:
                lines.append(f"  - ... and {len(errors) - 5} more")

        if corrections:
            lines.append("\n**Auto-corrections applied:**")
            for corr in corrections[:3]:
                lines.append(
                    f"  - Row {corr['row']}, `{corr['field']}`: "
                    f"`{corr['original']}` → `{corr['corrected']}`"
                )

        lines.append("")

    lines.append("---")
    lines.append(f"**Overall:** {total_errors} error(s), {total_warnings} warning(s), {total_corrections} auto-correction(s)")

    if total_errors == 0:
        lines.append("\nAll files passed validation. Data is ready for load.")
    else:
        lines.append("\nValidation failed. Please fix errors before loading data.")
        _append_recommendations(lines, reports)

    return "\n".join(lines)


def _append_recommendations(lines: list[str], reports: list[dict]) -> None:
    """Add actionable recommendations based on issue patterns."""
    all_issues: list[dict] = []
    for report in reports:
        all_issues.extend(report.get("issues", []))

    if not all_issues:
        return

    lines.append("\n**Recommendations:**")

    field_counts = Counter(i.get("field") for i in all_issues if i.get("field"))
    validator_counts = Counter(i.get("validator") for i in all_issues)

    top_field = field_counts.most_common(1)
    if top_field:
        field, count = top_field[0]
        lines.append(f"- Focus on fixing `{field}` — {count} issue(s) found across files.")

    top_validator = validator_counts.most_common(1)
    if top_validator:
        validator, count = top_validator[0]
        hints = {
            "template": "Check that your CSV headers match the expected template.",
            "formatting": "Review data types, date formats, and email/phone patterns.",
            "business": "Verify business rules such as country codes and required fields.",
            "dependency": "Ensure referenced IDs exist in related files (e.g., account_id in contacts).",
        }
        if validator in hints:
            lines.append(f"- {hints[validator]}")

    dependency_issues = [i for i in all_issues if i.get("validator") == "dependency"]
    if dependency_issues:
        lines.append("- Load account files before contact and territory files to resolve cross-file references.")


def generate_summary_dict(reports: list[dict]) -> dict[str, Any]:
    """Return structured summary data for programmatic use."""
    total_errors = sum(
        len([i for i in r.get("issues", []) if i.get("severity") == "error"])
        for r in reports
    )
    total_warnings = sum(
        len([i for i in r.get("issues", []) if i.get("severity") == "warning"])
        for r in reports
    )
    return {
        "status": "pass" if total_errors == 0 else "fail",
        "file_count": len(reports),
        "total_errors": total_errors,
        "total_warnings": total_warnings,
        "total_corrections": sum(len(r.get("corrections", [])) for r in reports),
        "summary_text": generate_summary(reports),
    }
