"""Reusable in-app editors for unresolved row-level validation issues."""

from __future__ import annotations

import re
from typing import Any

import streamlit as st

from services.issue_edit_service import (
    analyze_date_suggestion,
    clear_edit,
    collect_editable_issues,
    expected_date_format_label,
    get_issue_edits,
    revalidate_after_issue_edit,
    save_pending_edit,
    validate_replacement,
)
from services.date_conversion_service import FIELD_TYPE_DATE

FIX_ISSUES_TITLE = "Fix Issues in Copilot"
OPEN_ISSUE_KEY = "fix_issues_open_expander"
ALL_RESOLVED_MESSAGE = "✅ All editable issues have been corrected."
CORRECTION_SAVED_MESSAGE = "✅ Correction saved"


def build_issue_session_key(issue: dict[str, Any]) -> str:
    """Stable widget key prefix, e.g. ``date_issue_StartDate_row_5``."""
    issue_type = issue.get("issue_type") or "issue"
    field = re.sub(r"[^\w]", "", issue.get("field") or "field")
    row = issue.get("row") or 0
    return f"{issue_type}_issue_{field}_row_{row}"


def _issue_header(issue: dict[str, Any]) -> str:
    row = issue.get("row")
    field = issue.get("friendly_column") or issue.get("field") or "Field"
    return f"Row {row} — {field}" if row else str(field)


def build_issue_expander_label(issue: dict[str, Any]) -> str:
    """Compact one-line label for collapsed issue expanders."""
    row = issue.get("row")
    field = issue.get("friendly_column") or issue.get("field") or "Field"
    problem = issue.get("problem") or "Issue detected"
    if issue.get("issue_type") == "duplicate" and issue.get("duplicate_rows"):
        problem = "Duplicate identifier"
    return f"Row {row} — {field} — {problem}"


def _problem_label(issue: dict[str, Any]) -> str:
    problem = issue.get("problem") or "Issue detected"
    if issue.get("issue_type") == "duplicate" and issue.get("duplicate_rows"):
        rows = ", ".join(str(row) for row in issue["duplicate_rows"])
        return f"Duplicate identifier appears on rows {rows}"
    return problem


def build_issue_status_summary(issues: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """Return header line and bullet lines for the Fix Issues summary."""
    count = len(issues)
    item_word = "issue" if count == 1 else "issues"
    header = f"{count} {item_word} need attention"

    by_type: dict[str, int] = {}
    for issue in issues:
        issue_type = issue.get("issue_type") or "other"
        by_type[issue_type] = by_type.get(issue_type, 0) + 1

    lines: list[str] = []
    if by_type.get("date"):
        n = by_type["date"]
        word = "issue" if n == 1 else "issues"
        lines.append(f"- {n} date {word}")
    if by_type.get("duplicate"):
        n = by_type["duplicate"]
        word = "issue" if n == 1 else "issues"
        lines.append(f"- {n} duplicate identifier {word}")
    if by_type.get("numeric"):
        n = by_type["numeric"]
        word = "issue" if n == 1 else "issues"
        lines.append(f"- {n} numeric {word}")
    if by_type.get("text"):
        n = by_type["text"]
        word = "issue" if n == 1 else "issues"
        lines.append(f"- {n} text {word}")
    other = sum(
        count for key, count in by_type.items()
        if key not in {"date", "duplicate", "numeric", "text", "picklist"}
    )
    if other:
        word = "issue" if other == 1 else "issues"
        lines.append(f"- {other} other {word}")
    return header, lines


def _render_validation_message(edit_key: str, session_state: dict[str, Any]) -> None:
    entry = get_issue_edits(session_state).get(edit_key, {})
    message = entry.get("validation_message")
    if message:
        if entry.get("validated"):
            st.success(message)
        else:
            st.error(message)


def render_date_issue_editor(
    issue: dict[str, Any],
    *,
    upload_method: str,
    source_date_format: str | None = None,
    session_key_prefix: str = "date_issue",
    session_state: dict[str, Any] | None = None,
    inside_expander: bool = False,
) -> dict[str, Any] | None:
    """Render a date issue editor. Returns approved correction when saved."""
    state = session_state if session_state is not None else st.session_state
    edit_key = issue["edit_key"]
    field_type = issue.get("field_type", FIELD_TYPE_DATE)
    current = issue.get("current_value", "")
    subtype = issue.get("date_subtype", "invalid_calendar")
    pending = get_issue_edits(state).get(edit_key, {})
    default_value = pending.get("proposed", "")

    if not inside_expander:
        st.markdown(f"**{_issue_header(issue)}**")
    st.caption(f"Current value: `{current}`")
    st.caption(f"Problem: {_problem_label(issue)}")
    st.caption(f"Required format: {expected_date_format_label(upload_method)}")

    suggestion = issue.get("suggested_value")
    if not suggestion:
        analysis = analyze_date_suggestion(
            current,
            upload_method,
            source_date_format,
            field_type,
        )
        suggestion = analysis.get("suggested_value")

    mode = pending.get("mode", "default")
    if subtype in {"unsupported_text", "excel_serial"} and mode != "manual":
        if subtype == "unsupported_text":
            st.info(f"Suggested value: `{suggestion}`" if suggestion else "No unambiguous parsed date available.")
        else:
            st.info(
                f"Possible converted date: `{suggestion}`"
                if suggestion
                else "Possible Excel serial date detected."
            )
        action_cols = st.columns(2)
        with action_cols[0]:
            if st.button(
                "Use Suggested Date",
                key=f"{session_key_prefix}_use_suggested",
                disabled=not suggestion,
            ):
                save_pending_edit(
                    state,
                    edit_key,
                    original=current,
                    proposed=suggestion or "",
                    validated=True,
                    extra={
                        "validation_message": CORRECTION_SAVED_MESSAGE,
                        "mode": "suggested",
                    },
                )
                clear_edit(state, edit_key)
                return {
                    **issue,
                    "original_value": current,
                    "proposed_value": suggestion or "",
                }
        with action_cols[1]:
            if st.button("Enter Another Date", key=f"{session_key_prefix}_manual"):
                save_pending_edit(
                    state,
                    edit_key,
                    original=current,
                    proposed=pending.get("proposed", ""),
                    validated=False,
                    extra={"mode": "manual"},
                )
                st.rerun()
        if mode != "manual" and not pending.get("validated"):
            _render_validation_message(edit_key, state)
            return None

    proposed = st.text_input(
        "Enter corrected value",
        value=default_value,
        key=f"{session_key_prefix}_input",
        placeholder=expected_date_format_label(upload_method),
    )
    save_pending_edit(
        state,
        edit_key,
        original=current,
        proposed=proposed,
        validated=pending.get("validated", False),
        extra={
            "validation_message": pending.get("validation_message"),
            "mode": pending.get("mode", "manual"),
        },
    )

    if st.button("Save Correction", key=f"{session_key_prefix}_save", type="primary"):
        result = validate_replacement(issue, proposed, upload_method)
        if not result["valid"]:
            save_pending_edit(
                state,
                edit_key,
                original=current,
                proposed=proposed,
                validated=False,
                extra={
                    "validation_message": result["message"],
                    "mode": pending.get("mode", "manual"),
                },
            )
            st.rerun()
        clear_edit(state, edit_key)
        return {
            **issue,
            "original_value": current,
            "proposed_value": result.get("normalized_value", proposed),
        }

    _render_validation_message(edit_key, state)
    return None


def render_picklist_issue_editor(
    issue: dict[str, Any],
    *,
    upload_method: str,
    session_key_prefix: str = "picklist_issue",
    session_state: dict[str, Any] | None = None,
    inside_expander: bool = False,
) -> dict[str, Any] | None:
    """Render a picklist dropdown editor. Returns approved correction when saved."""
    state = session_state if session_state is not None else st.session_state
    edit_key = issue["edit_key"]
    current = issue.get("current_value", "")
    allowed_values = issue.get("allowed_values") or []
    pending = get_issue_edits(state).get(edit_key, {})

    if not inside_expander:
        st.markdown(f"**{_issue_header(issue)}**")
    st.caption(f"Current: `{current}`")
    st.caption(f"Problem: {_problem_label(issue)}")

    options = ["— Select —", *allowed_values]
    selected = st.selectbox(
        "Correct value",
        options=options,
        index=options.index(pending.get("proposed")) if pending.get("proposed") in options else 0,
        key=f"{session_key_prefix}_select",
    )
    proposed = "" if selected == "— Select —" else selected
    save_pending_edit(
        state,
        edit_key,
        original=current,
        proposed=proposed,
        validated=pending.get("validated", False),
        extra={"validation_message": pending.get("validation_message")},
    )

    if st.button("Save Correction", key=f"{session_key_prefix}_save", type="primary"):
        result = validate_replacement(issue, proposed, upload_method)
        if not result["valid"]:
            save_pending_edit(
                state,
                edit_key,
                original=current,
                proposed=proposed,
                validated=False,
                extra={"validation_message": result["message"]},
            )
            st.rerun()
        clear_edit(state, edit_key)
        return {
            **issue,
            "original_value": current,
            "proposed_value": result.get("normalized_value", proposed),
        }

    _render_validation_message(edit_key, state)
    return None


def render_duplicate_issue_editor(
    issue: dict[str, Any],
    *,
    upload_method: str,
    session_key_prefix: str = "duplicate_issue",
    session_state: dict[str, Any] | None = None,
    inside_expander: bool = False,
) -> dict[str, Any] | None:
    """Render an editor for one row in a duplicate identifier group."""
    duplicate_rows = issue.get("duplicate_rows") or []
    if duplicate_rows:
        st.caption(
            f"Duplicate value `{issue.get('duplicate_value', issue.get('current_value', ''))}` "
            f"also appears on row(s) {', '.join(str(row) for row in duplicate_rows if row != issue.get('row'))}."
        )
    return render_text_issue_editor(
        issue,
        upload_method=upload_method,
        session_key_prefix=session_key_prefix,
        session_state=session_state,
        inside_expander=inside_expander,
    )


def render_text_issue_editor(
    issue: dict[str, Any],
    *,
    upload_method: str,
    session_key_prefix: str = "text_issue",
    session_state: dict[str, Any] | None = None,
    inside_expander: bool = False,
) -> dict[str, Any] | None:
    """Render a generic text replacement editor."""
    state = session_state if session_state is not None else st.session_state
    edit_key = issue["edit_key"]
    current = issue.get("current_value", "")
    pending = get_issue_edits(state).get(edit_key, {})

    if not inside_expander:
        st.markdown(f"**{_issue_header(issue)}**")
    st.caption(f"Current value: `{current}`")
    st.caption(f"Problem: {_problem_label(issue)}")

    proposed = st.text_input(
        "Enter corrected value",
        value=pending.get("proposed", ""),
        key=f"{session_key_prefix}_input",
    )
    save_pending_edit(
        state,
        edit_key,
        original=current,
        proposed=proposed,
        validated=pending.get("validated", False),
        extra={"validation_message": pending.get("validation_message")},
    )

    if st.button("Save Correction", key=f"{session_key_prefix}_save", type="primary"):
        result = validate_replacement(issue, proposed, upload_method)
        if not result["valid"]:
            save_pending_edit(
                state,
                edit_key,
                original=current,
                proposed=proposed,
                validated=False,
                extra={"validation_message": result["message"]},
            )
            st.rerun()
        clear_edit(state, edit_key)
        return {
            **issue,
            "original_value": current,
            "proposed_value": result.get("normalized_value", proposed),
        }

    _render_validation_message(edit_key, state)
    return None


def render_numeric_issue_editor(
    issue: dict[str, Any],
    *,
    upload_method: str,
    session_key_prefix: str = "numeric_issue",
    session_state: dict[str, Any] | None = None,
    inside_expander: bool = False,
) -> dict[str, Any] | None:
    """Render a numeric replacement editor."""
    return render_text_issue_editor(
        {**issue, "issue_type": "numeric"},
        upload_method=upload_method,
        session_key_prefix=session_key_prefix,
        session_state=session_state,
        inside_expander=inside_expander,
    )


def render_issue_editor(
    issue: dict[str, Any],
    *,
    upload_method: str,
    source_date_format: str | None = None,
    session_key_prefix: str = "issue_editor",
    session_state: dict[str, Any] | None = None,
    inside_expander: bool = False,
) -> dict[str, Any] | None:
    """Route an editable issue to the appropriate editor."""
    issue_type = issue.get("issue_type")
    if issue_type == "date":
        return render_date_issue_editor(
            issue,
            upload_method=upload_method,
            source_date_format=source_date_format,
            session_key_prefix=session_key_prefix,
            session_state=session_state,
            inside_expander=inside_expander,
        )
    if issue_type == "picklist":
        return render_picklist_issue_editor(
            issue,
            upload_method=upload_method,
            session_key_prefix=session_key_prefix,
            session_state=session_state,
            inside_expander=inside_expander,
        )
    if issue_type == "duplicate":
        return render_duplicate_issue_editor(
            issue,
            upload_method=upload_method,
            session_key_prefix=session_key_prefix,
            session_state=session_state,
            inside_expander=inside_expander,
        )
    if issue_type == "numeric":
        return render_numeric_issue_editor(
            issue,
            upload_method=upload_method,
            session_key_prefix=session_key_prefix,
            session_state=session_state,
            inside_expander=inside_expander,
        )
    return render_text_issue_editor(
        issue,
        upload_method=upload_method,
        session_key_prefix=session_key_prefix,
        session_state=session_state,
        inside_expander=inside_expander,
    )


def _filter_fix_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Picklist issues are corrected in Picklist Review, not Fix Issues."""
    return [issue for issue in issues if issue.get("issue_type") != "picklist"]


def render_fix_issues_in_copilot(
    *,
    preparation_result: dict[str, Any],
    original_df: Any,
    row_correction_plan: dict[str, Any] | None,
    picklist_validation: dict[str, Any] | None,
    mapped_df: Any,
    upload_method: str,
    template: str,
    mapping_rows: list[dict[str, Any]] | None,
    validation_bundle: dict[str, Any] | None,
    date_field_types: dict[str, str] | None,
    source_date_format: str | None,
    template_context: Any | None,
    raw_csv_content: str | None = None,
    use_mapped_columns: bool = False,
    session_key_prefix: str = "fix_issues",
) -> dict[str, Any] | None:
    """
    Render the Fix Issues in Copilot section with collapsed expandable cards.

    Returns updated session payload when a correction is saved, otherwise None.
    """
    all_issues = collect_editable_issues(
        preparation_result=preparation_result,
        row_correction_plan=row_correction_plan,
        picklist_validation=picklist_validation,
        mapped_df=mapped_df,
        upload_method=upload_method,
        date_field_types=date_field_types,
        source_date_format=source_date_format,
    )
    issues = _filter_fix_issues(all_issues)

    st.subheader(FIX_ISSUES_TITLE)

    if not issues:
        st.success(ALL_RESOLVED_MESSAGE)
        return None

    header, summary_lines = build_issue_status_summary(issues)
    st.markdown(f"**{header}**")
    for line in summary_lines:
        st.markdown(line)

    open_key = f"{session_key_prefix}_{OPEN_ISSUE_KEY}"
    active_edit_key = st.session_state.get(open_key)
    for issue in issues:
        pending = get_issue_edits(st.session_state).get(issue["edit_key"], {})
        if pending.get("proposed"):
            active_edit_key = issue["edit_key"]
            break

    for issue in issues:
        label = build_issue_expander_label(issue)
        issue_session_key = build_issue_session_key(issue)
        pending = get_issue_edits(st.session_state).get(issue["edit_key"], {})
        expanded = active_edit_key == issue["edit_key"] or bool(pending.get("proposed"))
        with st.expander(label, expanded=expanded):
            correction = render_issue_editor(
                issue,
                upload_method=upload_method,
                source_date_format=source_date_format,
                session_key_prefix=f"{session_key_prefix}_{issue_session_key}",
                inside_expander=True,
            )
            if correction is not None:
                st.session_state.pop(open_key, None)
                return revalidate_after_issue_edit(
                    preparation_result=preparation_result,
                    original_df=original_df,
                    correction=correction,
                    upload_method=upload_method,
                    template=template,
                    mapping_rows=mapping_rows,
                    validation_bundle=validation_bundle,
                    row_correction_plan=row_correction_plan,
                    date_field_types=date_field_types,
                    source_date_format=source_date_format,
                    template_context=template_context,
                    raw_csv_content=raw_csv_content,
                    use_mapped_columns=use_mapped_columns,
                )

    return None


def build_issue_editor_summary(issues: list[dict[str, Any]]) -> str:
    """Build a plain-text summary for tests and technical details."""
    filtered = _filter_fix_issues(issues)
    if not filtered:
        return "No unresolved issues require in-app editing."
    lines = []
    for issue in filtered:
        lines.append(
            f"- Row {issue.get('row')} `{issue.get('field')}`: "
            f"{issue.get('problem')} (current: `{issue.get('current_value', '')}`)"
        )
    return "\n".join(lines)
