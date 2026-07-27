"""Reusable action-card helpers for data preparation UI."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import streamlit as st

TECHNICAL_DETAILS_TITLE = "View Technical Details"

CLEANUP_CATEGORY_CONFIG: tuple[tuple[str, str], ...] = (
    ("whitespace", "Whitespace"),
    ("dates", "Dates"),
    ("identifiers", "Identifier Format"),
    ("phones", "Phone Formatting"),
    ("addresses", "Address Formatting"),
    ("punctuation", "Punctuation"),
    ("blank_rows", "Blank Rows"),
    ("csv_structure", "CSV Structure"),
    ("numeric", "Numeric Formatting"),
    ("eans", "EAN Cleanup"),
    ("federation_ids", "User ID Cleanup"),
    ("salesforce_record_check", "Salesforce Record Check"),
)

ALL_CLEANUP_CATEGORIES: tuple[str, ...] = tuple(category for category, _label in CLEANUP_CATEGORY_CONFIG)


def build_action_card_body(
    *,
    applied: bool,
    description: str,
    success_message: str | None = None,
) -> str:
    """Return user-facing card body text (testable without Streamlit)."""
    if applied and success_message:
        return success_message
    return description


def _category_action_text(category: str, count: int) -> str:
    if category == "whitespace":
        word = "value" if count == 1 else "values"
        return f"{count} {word} will be trimmed"
    if category == "dates":
        word = "date" if count == 1 else "dates"
        return f"{count} {word} will be converted"
    if category == "identifiers":
        word = "value" if count == 1 else "values"
        return f"{count} identifier {word} need review"
    if category == "phones":
        word = "value" if count == 1 else "values"
        return f"{count} {word} can be corrected"
    if category == "addresses":
        word = "value" if count == 1 else "values"
        return f"{count} {word} need cleanup"
    if category == "blank_rows":
        word = "blank row" if count == 1 else "blank rows"
        return f"{count} {word} will be removed"
    if category == "punctuation":
        word = "value" if count == 1 else "values"
        return f"{count} {word} will be normalized"
    if category == "csv_structure":
        word = "issue" if count == 1 else "issues"
        return f"{count} structure {word} will be fixed"
    if category == "numeric":
        word = "value" if count == 1 else "values"
        return f"{count} {word} will be converted"
    if category == "eans":
        word = "value" if count == 1 else "values"
        return f"{count} EAN {word} can restore leading zeroes"
    if category == "federation_ids":
        word = "value" if count == 1 else "values"
        return f"{count} User ID {word} can restore leading zeroes"
    if category == "salesforce_record_check":
        word = "value" if count == 1 else "values"
        return f"{count} {word} need review"
    word = "value" if count == 1 else "values"
    return f"{count} {word} will be corrected"


def _category_status_icon(issues: list[dict[str, Any]]) -> str:
    if all(issue.get("safe") for issue in issues):
        return "✓"
    return "⚠"


def build_cleanup_category_summaries(
    row_correction_plan: dict[str, Any] | None,
    *,
    categories: tuple[str, ...] = ALL_CLEANUP_CATEGORIES,
) -> list[dict[str, Any]]:
    """Build grouped category summary lines for the Data Cleanup card."""
    plan = row_correction_plan or {"issues": []}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for issue in plan.get("issues", []):
        category = issue.get("category", "")
        if category not in categories:
            continue
        if not (issue.get("safe") or issue.get("requires_confirmation")):
            continue
        grouped.setdefault(category, []).append(issue)

    summaries: list[dict[str, Any]] = []
    label_by_category = dict(CLEANUP_CATEGORY_CONFIG)
    for category, label in CLEANUP_CATEGORY_CONFIG:
        if category not in categories:
            continue
        cat_issues = grouped.get(category, [])
        if not cat_issues:
            continue
        count = len(cat_issues)
        icon = _category_status_icon(cat_issues)
        action_text = _category_action_text(category, count)
        summaries.append({
            "category": category,
            "label": label_by_category.get(category, label),
            "icon": icon,
            "count": count,
            "line": f"{label} — {icon} {action_text}",
        })
    return summaries


def format_cleanup_summary_intro(cleanup_count: int) -> str:
    """Return the intro line for the Data Cleanup card."""
    item_word = "item" if cleanup_count == 1 else "items"
    return f"{cleanup_count} cleanup {item_word} found."


def build_data_cleanup_description(
    *,
    trim_count: int,
    blank_count: int,
    other_count: int,
    cleanup_rows: int,
    cleanup_count: int,
) -> str:
    """Return user-facing description text for the Data Cleanup card."""
    rows = cleanup_rows or cleanup_count
    row_word = "row" if rows == 1 else "rows"

    if trim_count and not blank_count and not other_count:
        issue_word = "issue" if trim_count == 1 else "issues"
        return f"{trim_count} whitespace {issue_word} were found across {rows} {row_word}."

    parts: list[str] = []
    if trim_count:
        parts.append(f"{trim_count} whitespace issue(s)")
    if blank_count:
        parts.append(f"{blank_count} blank row(s)")
    if other_count:
        parts.append(f"{other_count} other cleanup item(s)")

    item_word = "item" if cleanup_count == 1 else "items"
    return (
        f"{cleanup_count} cleanup {item_word} across {rows} {row_word}: "
        + ", ".join(parts)
        + "."
    )


def build_cleanup_action_buttons(
    trim_count: int,
    blank_count: int,
    other_count: int,
    *,
    categories: tuple[str, ...],
) -> list[tuple[str, str, tuple[str, ...]]]:
    """Return (label, key_suffix, categories) tuples for cleanup action buttons."""
    actions: list[tuple[str, str, tuple[str, ...]]] = []
    if trim_count:
        actions.append(("Apply Whitespace Cleanup", "trim_whitespace", ("whitespace",)))
    if blank_count:
        actions.append(("Remove Blank Rows", "remove_blank_rows", ("blank_rows",)))
    if other_count:
        actions.append((
            "Apply Other Cleanup",
            "other_cleanup",
            tuple(
                category for category in categories
                if category not in {"whitespace", "blank_rows"}
            ),
        ))
    return actions


def render_technical_details_expander(
    content: str | None = None,
    *,
    title: str = TECHNICAL_DETAILS_TITLE,
    render_fn: Callable[[], None] | None = None,
    expanded: bool = False,
) -> None:
    """Render a collapsed technical-details expander used across preparation UI."""
    if not content and render_fn is None:
        return
    with st.expander(title, expanded=expanded):
        if render_fn is not None:
            render_fn()
        elif content:
            st.markdown(content)


def format_header_order_details(order_differences: list[dict[str, Any]]) -> str:
    """Format column-order diagnostics for a technical details expander."""
    if not order_differences:
        return "No column order differences detected."
    lines = [
        f"- `{diff['header']}`: expected position {diff['expected_position']}, "
        f"found {diff['actual_position']}"
        for diff in order_differences
    ]
    return "\n".join(lines)


def format_structure_change_details(lines: list[str]) -> str:
    """Format structural change summaries for a View Details expander."""
    if not lines:
        return "No structural changes proposed."
    return "\n".join(f"- {line}" for line in lines)


def format_issue_details(issues: list[dict[str, Any]], *, limit: int = 25) -> str:
    """Format row-level issue diagnostics for a View Details expander."""
    if not issues:
        return "No issues detected."
    lines: list[str] = []
    for issue in issues[:limit]:
        row_label = f"Row {issue['row']}" if issue.get("row") else "File"
        field_label = issue.get("field") or issue.get("friendly_column") or "(structure)"
        confidence = issue.get("address_confidence") or issue.get("confidence")
        confidence_text = f"; confidence: {confidence}" if confidence is not None else ""
        lines.append(
            f"- {row_label} `{field_label}`: {issue.get('reason', 'Issue detected')} "
            f"(original: `{issue.get('original_value', '')}` → proposed: "
            f"`{issue.get('proposed_value', '')}`{confidence_text})"
        )
    if len(issues) > limit:
        lines.append(f"... and {len(issues) - limit} more issue(s) not shown.")
    return "\n".join(lines)


def get_issue_ids_for_categories(
    row_correction_plan: dict[str, Any] | None,
    categories: tuple[str, ...],
    *,
    safe_only: bool = False,
) -> set[str]:
    """Collect issue IDs belonging to the given categories."""
    plan = row_correction_plan or {"issues": []}
    issue_ids: set[str] = set()
    for issue in plan.get("issues", []):
        if issue.get("category") not in categories:
            continue
        if safe_only and not issue.get("safe"):
            continue
        if not safe_only and not (issue.get("safe") or issue.get("requires_confirmation")):
            continue
        issue_ids.add(issue["issue_id"])
    return issue_ids


def count_fixable_issues(
    row_correction_plan: dict[str, Any] | None,
    categories: tuple[str, ...],
) -> tuple[int, int]:
    """Return (fixable_count, rows_affected) for the given categories."""
    plan = row_correction_plan or {"issues": []}
    fixable = [
        issue for issue in plan.get("issues", [])
        if issue.get("category") in categories
        and (issue.get("safe") or issue.get("requires_confirmation"))
    ]
    rows = {issue.get("row") for issue in fixable if issue.get("row") is not None}
    return len(fixable), len(rows)


def render_data_cleanup_card(
    *,
    cleanup_count: int,
    category_summaries: list[dict[str, Any]],
    details: str | None = None,
    applied: bool = False,
    success_message: str | None = None,
    show_technical_details: bool = True,
    show_action_buttons: bool = True,
) -> str | None:
    """
    Render the Data Cleanup action card using native Streamlit widgets.

    Returns ``apply_all``, ``review_individual``, ``skip``, or None.
    """
    intro = format_cleanup_summary_intro(cleanup_count)
    body = build_action_card_body(
        applied=applied,
        description=intro,
        success_message=success_message,
    )

    with st.container(border=True):
        st.subheader("🧹 Data Cleanup")
        st.caption(body)
        if not applied:
            for summary in category_summaries:
                st.markdown(summary["line"])
            if show_action_buttons:
                action_cols = st.columns(3)
                with action_cols[0]:
                    if st.button(
                        "Apply All Safe Changes",
                        type="primary",
                        key="data_prep_apply_safe_card",
                        use_container_width=True,
                    ):
                        return "apply_all"
                with action_cols[1]:
                    if st.button(
                        "Review Individually",
                        key="data_prep_review_individual",
                        use_container_width=True,
                    ):
                        return "review_individual"
                with action_cols[2]:
                    if st.button(
                        "Skip",
                        key="data_prep_skip",
                        use_container_width=True,
                    ):
                        return "skip"

    if show_technical_details and details:
        render_technical_details_expander(details)
    return None


def render_action_card(
    title: str,
    description: str,
    button_label: str,
    *,
    key: str,
    details: str | None = None,
    applied: bool = False,
    success_message: str | None = None,
    disabled: bool = False,
    type: str = "primary",
    show_technical_details: bool = True,
) -> bool:
    """
    Render a preparation action card.

    Returns True when the primary action button was clicked.
    """
    body = build_action_card_body(
        applied=applied,
        description=description,
        success_message=success_message,
    )
    with st.container(border=True):
        st.subheader(title)
        st.caption(body)
        clicked = st.button(
            button_label,
            type=type,
            key=key,
            disabled=disabled or applied,
            use_container_width=True,
        )

    if show_technical_details and details:
        render_technical_details_expander(details)
    return clicked


def render_action_card_with_callback(
    title: str,
    description: str,
    button_label: str,
    on_apply: Callable[[], Any],
    *,
    key: str,
    details: str | None = None,
    applied: bool = False,
    success_message: str | None = None,
    disabled: bool = False,
) -> Any | None:
    """Render an action card and invoke ``on_apply`` when the button is clicked."""
    if render_action_card(
        title,
        description,
        button_label,
        key=key,
        details=details,
        applied=applied,
        success_message=success_message,
        disabled=disabled,
    ):
        return on_apply()
    return None
