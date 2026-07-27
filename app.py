"""Europe SFA Data Load Copilot — Streamlit orchestrator."""

from __future__ import annotations

import streamlit as st

from core.config import UPLOAD_METHODS, is_sso_required, resolve_metadata_repo_path
from core.csv_loader import load_uploaded_csv
from services.preparation_task_service import (
    is_preparation_only,
    preparation_only_message,
    resolve_load_operation,
)
from services.preparation_flow_service import evaluate_preparation_readiness
from services.preparation_orchestrator import (
    evaluate_shared_download_readiness,
    merge_picklist_change_log,
)
from services.file_preparation_service import apply_correction_changes
from services.salesforce_oauth_service import handle_oauth_callback
from ui.components import (
    render_comparison_results,
    render_file_overview,
    render_mapping_plan,
    render_preparation_results,
    render_preview,
    render_readiness,
)
from ui.data_preparation_review import render_data_preparation_review
from ui.issue_editor import render_fix_issues_in_copilot
from ui.date_format_review import render_date_format_review
from ui.field_metadata_debug import render_account_field_metadata_debug
from ui.mapping_confirmation import render_mapping_confirmation
from ui.picklist_metadata_debug import render_picklist_metadata_debug
from ui.picklist_validation import (
    apply_picklist_validation_result,
    render_picklist_validation,
)
from ui.data_preparation_warnings import render_data_preparation_warnings
from ui.upload_order_guidance import render_upload_order_guidance
from services.dit_ux_service import SESSION_PREREQ_CONFIRMED
from services.upload_order_service import build_upload_order_plan
from ui.salesforce_record_check import (
    apply_salesforce_record_check,
    render_salesforce_record_check,
)
from ui.preparation_task_selector import render_preparation_task_selector
from ui.metadata_source import render_metadata_source_panel
from ui.salesforce_connection import render_salesforce_connection_card
from ui.prepare_file import render_prepare_file
from services.startup_validation import get_deployment_startup_notices, validate_startup_metadata
from services.git_repository_service import get_repository_status
from services.metadata_session_service import (
    METADATA_VERSION_KEY,
    METADATA_VERSION_WARNING,
    SESSION_METADATA_REFRESH_PENDING,
    metadata_version_changed,
)
from ui.styles import PAGE_STYLE
from ui.validation_results import render_validation_results
from workflow.copilot import (
    apply_file_preparation,
    apply_date_format_review,
    attach_date_validation_to_preparation,
    build_correction_plan_proposal,
    build_date_field_types,
    build_dit_mapping_rows,
    build_mapped_dataframe,
    build_row_correction_plan_proposal,
    build_workbench_preparation_plan_proposal,
    get_workbench_field_catalog_options,
    get_template_dropdown_options,
    get_template_dropdown_warning,
    get_workflow_context,
    init_field_mappings,
    mappings_ready_for_data_quality,
    revalidate_after_corrections,
    run_full_validation,
    run_template_comparison,
)

st.set_page_config(page_title="Europe SFA Data Load Copilot", page_icon="📋", layout="wide")

# Salesforce OAuth callback — exchange code before rendering UI; clear URL params after.
if handle_oauth_callback(st.session_state, st.query_params):
    st.query_params.clear()
    st.rerun()

# Optional Entra app gate — separate from Salesforce OAuth (primary metadata auth).
if is_sso_required():
    if not st.user.is_logged_in:
        st.login()
    if not st.user.is_logged_in:
        st.stop()

_metadata_ok, _metadata_error = validate_startup_metadata()
if not _metadata_ok:
    st.error(f"Metadata startup validation failed: {_metadata_error}")
    st.stop()

with st.expander("Deployment status", expanded=False):
    for notice in get_deployment_startup_notices():
        st.caption(notice)

st.markdown(PAGE_STYLE, unsafe_allow_html=True)

st.title("Europe SFA Data Load Copilot")
st.caption("Prepare and validate Salesforce data before upload.")

st.divider()

render_salesforce_connection_card()
st.divider()
render_metadata_source_panel()
st.divider()

col1, col2 = st.columns(2)
with col1:
    st.markdown('<p class="step-label">Step 1 — Select Target Tool</p>', unsafe_allow_html=True)
    upload_method = st.selectbox(
        "Select Target Tool",
        options=UPLOAD_METHODS,
        index=None,
        placeholder="Choose a target tool...",
    )
with col2:
    st.markdown('<p class="step-label">Step 2 — Select Template or Business Context</p>', unsafe_allow_html=True)
    template = st.selectbox(
        "Select Business Template",
        options=get_template_dropdown_options(),
        index=None,
        placeholder="Choose a template...",
    )

dropdown_warning = get_template_dropdown_warning()
if dropdown_warning:
    st.warning(dropdown_warning)

context = get_workflow_context(upload_method, template)

if template and not context["metadata_available"]:
    st.warning(context["metadata_message"] or (
        "Template metadata is not available in the local Salesforce project."
    ))

preparation_task = None
load_operation = None
preparation_only = False
if upload_method and template:
    st.markdown('<p class="step-label">Step 3 — Select Task</p>', unsafe_allow_html=True)
    preparation_task = render_preparation_task_selector()
    load_operation = resolve_load_operation(preparation_task)
    preparation_only = is_preparation_only(preparation_task)
    if preparation_only:
        st.info(preparation_only_message(upload_method))

    if upload_method == "Workbench" and context["supports_workbench_prep"] and context["template_mapping"]:
        render_mapping_plan(context["template_mapping"], template)

context = get_workflow_context(upload_method, template, load_operation, preparation_task)

step_label = "Step 4 — Upload CSV" if upload_method and template else "Step 3 — Upload CSV"
st.markdown(f'<p class="step-label">{step_label}</p>', unsafe_allow_html=True)
uploaded_file = st.file_uploader("Upload CSV", type=["csv"])

if uploaded_file is not None:
    current_metadata_status = get_repository_status(resolve_metadata_repo_path())
    locked_metadata_version = st.session_state.get(METADATA_VERSION_KEY)
    if metadata_version_changed(
        locked_metadata_version,
        current_metadata_status.commit_hash,
    ) or st.session_state.get(SESSION_METADATA_REFRESH_PENDING):
        st.warning(METADATA_VERSION_WARNING)

    if upload_method and template and not preparation_task:
        st.warning("Select a preparation task in Step 3 before continuing.")
        st.stop()
    try:
        df, raw_headers = load_uploaded_csv(uploaded_file)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
    except Exception as exc:
        st.error(f"Unable to read CSV file: {exc}")
        st.stop()

    render_file_overview(uploaded_file.name, len(df), len(df.columns))
    render_preview(df)

    session_key = f"mapping_{uploaded_file.name}_{template}_{upload_method}_{preparation_task}"
    if st.session_state.get("mapping_session_key") != session_key:
        st.session_state["mapping_session_key"] = session_key
        st.session_state[METADATA_VERSION_KEY] = current_metadata_status.commit_hash
        st.session_state.pop(SESSION_METADATA_REFRESH_PENDING, None)
        st.session_state["original_df"] = df.copy()
        st.session_state.pop("mapping_rows", None)
        st.session_state.pop("type_confirmed", None)
        st.session_state.pop("formatting_review", None)
        st.session_state.pop("preparation_result", None)
        st.session_state.pop("validation_bundle", None)
        st.session_state.pop("last_comparison", None)
        st.session_state.pop("correction_plan", None)
        st.session_state.pop("row_correction_plan", None)
        st.session_state.pop("workbench_preparation_plan", None)
        st.session_state.pop("workbench_mappings", None)
        st.session_state.pop("mapped_df", None)
        st.session_state.pop("proposed_df", None)
        st.session_state.pop("header_review_complete", None)
        st.session_state.pop("header_enabled_change_ids", None)
        st.session_state.pop("mapping_preparation_started", None)
        st.session_state.pop("picklist_correction_plan", None)
        st.session_state.pop("source_date_format", None)
        st.session_state.pop("date_conversion_plan", None)
        st.session_state.pop("date_conversions_approved", None)
        st.session_state.pop("issue_edits", None)

    original_df = st.session_state.get("original_df", df.copy())
    working_df = original_df
    working_headers = raw_headers
    preparation_result = st.session_state.get("preparation_result")
    if preparation_result and preparation_result.get("corrected_df") is not None:
        working_df = preparation_result["corrected_df"]
        working_headers = list(working_df.columns)

    if upload_method == "Data Import Tool":
        if "last_comparison" not in st.session_state:
            try:
                comparison = run_template_comparison(
                    raw_headers,
                    upload_method,
                    template,
                    load_operation,
                )
                correction_plan = build_correction_plan_proposal(
                    original_df,
                    raw_headers,
                    upload_method,
                    template,
                    load_operation,
                    comparison,
                )
                st.session_state["last_comparison"] = comparison
                st.session_state["correction_plan"] = correction_plan
            except FileNotFoundError:
                st.error("Reference template not found.")
            except ValueError as exc:
                st.error(str(exc))

        correction_plan = st.session_state.get("correction_plan")
        if st.session_state.get("last_comparison") and correction_plan:
            render_comparison_results(st.session_state["last_comparison"], correction_plan)

            if not st.session_state.get("header_review_complete"):
                st.divider()
                prepare_approval = render_prepare_file(correction_plan)
                if prepare_approval is not None:
                    if prepare_approval.get("declined"):
                        mapped_df = original_df.copy()
                        enabled_ids: set[str] = set()
                        correction_plan["corrections_declined"] = True
                    else:
                        enabled_ids = prepare_approval["enabled_change_ids"]
                        mapped_df = apply_correction_changes(
                            original_df,
                            correction_plan,
                            enabled_ids,
                        )
                    st.session_state["mapped_df"] = mapped_df
                    st.session_state["proposed_df"] = mapped_df.copy()
                    st.session_state["header_enabled_change_ids"] = enabled_ids
                    st.session_state["header_review_complete"] = True
                    correction_plan["header_corrections_applied"] = True
                    st.session_state["correction_plan"] = correction_plan
                    st.session_state.pop("row_correction_plan", None)
                    st.session_state.pop("preparation_result", None)
                    st.session_state.pop("validation_bundle", None)
                    st.success("Header review complete. Continue to row-level data validation.")
                    st.rerun()
            else:
                mapped_df = st.session_state.get("mapped_df", original_df)
                mapped_headers = list(mapped_df.columns)
                dit_mapping_rows = build_dit_mapping_rows(mapped_headers, template)
                template_context = context["template_context"]

                date_field_types = build_date_field_types(mapped_df, template, mapping_rows=dit_mapping_rows)
                cleanup_section_open = False
                if date_field_types and not st.session_state.get("date_conversions_approved"):
                    st.subheader("Data Cleanup")
                    cleanup_section_open = True
                    date_approval = render_date_format_review(
                        mapped_df,
                        date_field_types,
                        upload_method,
                        session_key_prefix="dit_date_format",
                    )
                    if date_approval is not None:
                        converted_df, date_change_log = apply_date_format_review(mapped_df, date_approval)
                        st.session_state["mapped_df"] = converted_df
                        st.session_state["proposed_df"] = converted_df.copy()
                        st.session_state["source_date_format"] = date_approval.get("source_format")
                        st.session_state["date_conversion_plan"] = date_approval.get("plan")
                        if date_approval.get("approved"):
                            st.session_state["date_conversions_approved"] = True
                            st.session_state.pop("row_correction_plan", None)
                            mapped_df = converted_df
                            mapped_headers = list(converted_df.columns)
                            if date_change_log:
                                st.success(f"Applied {len(date_change_log)} date conversion(s).")
                            st.rerun()
                        if date_approval.get("declined"):
                            st.session_state["date_conversions_approved"] = True
                            st.rerun()

                if "row_correction_plan" not in st.session_state:
                    try:
                        raw_content = uploaded_file.getvalue().decode("utf-8-sig")
                        st.session_state["row_correction_plan"] = build_row_correction_plan_proposal(
                            mapped_df,
                            upload_method,
                            template,
                            mapping_rows=dit_mapping_rows,
                            raw_csv_content=raw_content,
                            source_date_format=st.session_state.get("source_date_format"),
                        )
                    except ValueError as exc:
                        st.error(str(exc))

                row_plan = st.session_state.get("row_correction_plan") or {}
                validation_bundle = run_full_validation(
                    mapped_df,
                    mapped_headers,
                    upload_method,
                    template,
                    mapping_rows=dit_mapping_rows,
                    load_operation=load_operation,
                    preparation_task=preparation_task,
                    use_mapped_columns=False,
                )
                st.session_state["validation_bundle"] = validation_bundle

                if not cleanup_section_open:
                    st.subheader("Data Cleanup")
                if not row_plan.get("corrections_applied") and not row_plan.get("corrections_declined"):
                    data_approval = render_data_preparation_review(
                        row_plan,
                        picklist_validation=validation_bundle.get("picklist_validation"),
                        show_section_header=False,
                    )
                    if data_approval is not None:
                        header_ids = st.session_state.get("header_enabled_change_ids", set())
                        if data_approval.get("declined"):
                            row_plan["corrections_declined"] = True
                            result = apply_file_preparation(
                                original_df,
                                raw_headers,
                                upload_method,
                                template,
                                load_operation,
                                correction_plan,
                                header_ids,
                            )
                        else:
                            result = apply_file_preparation(
                                original_df,
                                raw_headers,
                                upload_method,
                                template,
                                load_operation,
                                correction_plan,
                                header_ids,
                                row_correction_plan=row_plan,
                                enabled_row_issue_ids=data_approval["enabled_issue_ids"],
                            )
                            picklist_plan = st.session_state.get("picklist_correction_plan") or {}
                            result = merge_picklist_change_log(result, picklist_plan)
                            row_plan["corrections_applied"] = True
                            row_plan["enabled_issue_ids"] = sorted(data_approval["enabled_issue_ids"])

                        st.session_state["preparation_result"] = result
                        st.session_state["proposed_df"] = result.get("proposed_df")
                        st.session_state["row_correction_plan"] = row_plan

                        revalidation = revalidate_after_corrections(
                            original_df,
                            raw_headers,
                            result["corrected_df"],
                            upload_method,
                            template,
                            load_operation,
                            dit_mapping_rows,
                            result,
                            correction_plan,
                            row_correction_plan=row_plan,
                            raw_csv_content=uploaded_file.getvalue().decode("utf-8-sig"),
                            source_date_format=st.session_state.get("source_date_format"),
                            use_mapped_columns=False,
                        )
                        st.session_state["validation_bundle"] = revalidation["validation_bundle"]
                        st.success("Approved data changes applied to a working copy of your file.")
                        st.rerun()
                elif row_plan:
                    render_data_preparation_review(
                        row_plan,
                        picklist_validation=validation_bundle.get("picklist_validation"),
                        show_section_header=False,
                    )

                preparation_result = st.session_state.get("preparation_result")
                if preparation_result and preparation_result.get("corrected_df") is not None:
                    date_field_types = build_date_field_types(mapped_df, template, mapping_rows=dit_mapping_rows)
                    preparation_result = attach_date_validation_to_preparation(
                        preparation_result,
                        preparation_result["corrected_df"],
                        date_field_types,
                        upload_method,
                        st.session_state.get("source_date_format"),
                    ) or preparation_result
                    st.session_state["preparation_result"] = preparation_result
                    row_plan = st.session_state.get("row_correction_plan") or {}
                    issue_update = render_fix_issues_in_copilot(
                        preparation_result=preparation_result,
                        original_df=original_df,
                        row_correction_plan=row_plan,
                        picklist_validation=validation_bundle.get("picklist_validation"),
                        mapped_df=preparation_result["corrected_df"],
                        upload_method=upload_method,
                        template=template,
                        mapping_rows=dit_mapping_rows,
                        validation_bundle=validation_bundle,
                        date_field_types=date_field_types,
                        source_date_format=st.session_state.get("source_date_format"),
                        template_context=context.get("template_context"),
                        raw_csv_content=uploaded_file.getvalue().decode("utf-8-sig"),
                        use_mapped_columns=False,
                        session_key_prefix="dit_fix_issues",
                    )
                    if issue_update is not None:
                        st.session_state["preparation_result"] = issue_update["preparation_result"]
                        st.session_state["validation_bundle"] = issue_update["validation_bundle"]
                        st.session_state["row_correction_plan"] = issue_update["row_correction_plan"]
                        st.session_state["mapped_df"] = issue_update["preparation_result"]["corrected_df"]
                        st.session_state["proposed_df"] = issue_update["preparation_result"]["corrected_df"].copy()
                        st.success("Correction saved to the working copy.")
                        st.rerun()

                picklist_approval = render_picklist_validation(
                    validation_bundle.get("picklist_validation", {}),
                    mapped_df,
                    dit_mapping_rows,
                    template_context,
                )
                if picklist_approval is not None:
                    corrected_df, picklist_revalidation, picklist_plan = apply_picklist_validation_result(
                        mapped_df,
                        validation_bundle.get("picklist_validation", {}),
                        picklist_approval,
                        dit_mapping_rows,
                        template_context,
                    )
                    st.session_state["mapped_df"] = corrected_df
                    st.session_state["proposed_df"] = corrected_df.copy()
                    st.session_state["picklist_correction_plan"] = picklist_plan
                    validation_bundle["picklist_validation"] = picklist_revalidation
                    st.session_state["validation_bundle"] = validation_bundle
                    mapped_df = corrected_df
                    mapped_headers = list(corrected_df.columns)
                    st.session_state.pop("row_correction_plan", None)
                    st.session_state.pop("preparation_result", None)
                    st.success("Approved picklist replacements applied to the working copy.")
                    st.rerun()

                prerequisite_status = st.session_state.get("upload_prerequisites", {})
                deployment_templates = st.session_state.get("deployment_templates") or [template]
                if len(deployment_templates) <= 1:
                    prerequisite_status = render_data_preparation_warnings(
                        template,
                        deployment_templates=deployment_templates,
                        prerequisite_status=prerequisite_status,
                    )
                else:
                    prerequisite_status = render_upload_order_guidance(
                        template,
                        deployment_templates=deployment_templates,
                        prerequisite_status=prerequisite_status,
                    )
                st.session_state["upload_prerequisites"] = prerequisite_status
                validation_bundle["upload_order_plan"] = build_upload_order_plan(
                    deployment_templates,
                    prerequisite_status=prerequisite_status,
                    included_templates=set(deployment_templates),
                )
                st.session_state["validation_bundle"] = validation_bundle

                preparation_result = st.session_state.get("preparation_result")
                if preparation_result and preparation_result.get("corrected_df") is not None:
                    date_field_types = build_date_field_types(mapped_df, template, mapping_rows=dit_mapping_rows)
                    preparation_result = attach_date_validation_to_preparation(
                        preparation_result,
                        preparation_result["corrected_df"],
                        date_field_types,
                        upload_method,
                        st.session_state.get("source_date_format"),
                    ) or preparation_result
                    st.session_state["preparation_result"] = preparation_result
                    row_plan = st.session_state.get("row_correction_plan") or {}
                    validation_bundle = st.session_state.get("validation_bundle") or run_full_validation(
                        mapped_df,
                        mapped_headers,
                        upload_method,
                        template,
                        mapping_rows=dit_mapping_rows,
                        load_operation=load_operation,
                        preparation_result=preparation_result,
                        correction_plan=correction_plan,
                        preparation_task=preparation_task,
                        use_mapped_columns=False,
                    )
                    can_download, download_msg = evaluate_shared_download_readiness(
                        upload_method=upload_method,
                        template=template,
                        mapping_rows=dit_mapping_rows,
                        type_confirmed=True,
                        load_operation=load_operation,
                        preparation_result=preparation_result,
                        validation_result=validation_bundle,
                        row_correction_plan=row_plan,
                        preparation_only=preparation_only,
                    )
                    render_preparation_results(
                        preparation_result,
                        template,
                        uploaded_file.name,
                        upload_method,
                        can_download,
                        download_msg,
                        validation_result=validation_bundle,
                        comparison_result=st.session_state.get("last_comparison"),
                        preparation_only=preparation_only,
                    )

                render_validation_results(validation_bundle)

            st.divider()
            st.subheader("Upload Readiness")
            readiness = evaluate_preparation_readiness(
                header_review_complete=st.session_state.get("header_review_complete", False),
                preparation_result=st.session_state.get("preparation_result"),
                row_correction_plan=st.session_state.get("row_correction_plan"),
                workbench_plan=None,
                validation_result=st.session_state.get("validation_bundle"),
                preparation_task=preparation_task,
                upload_method=upload_method,
                template=template,
                deployment_templates=st.session_state.get("deployment_templates") or [template],
                upload_prerequisites=st.session_state.get("upload_prerequisites"),
                preparation_warnings_acknowledged=st.session_state.get("preparation_warnings_acknowledged"),
                prerequisites_confirmed=st.session_state.get(SESSION_PREREQ_CONFIRMED, False),
            )
            render_readiness(readiness)

    elif upload_method == "Workbench" and preparation_task and context["supports_workbench_prep"]:
        if "mapping_rows" not in st.session_state:
            try:
                st.session_state["mapping_rows"] = init_field_mappings(
                    raw_headers,
                    template,
                    load_operation,
                    saved_mappings=st.session_state.get("workbench_mappings"),
                )
            except ValueError as exc:
                st.error(str(exc))
                st.stop()

        field_catalog, _, _ = get_workbench_field_catalog_options(template, load_operation)
        skipped_headers = list(getattr(df, "attrs", {}).get("skipped_headers") or [])
        render_account_field_metadata_debug(template, load_operation, skipped_headers)

        st.divider()
        template_context = context.get("template_context")
        required_type = (
            template_context.required_type_value
            if template_context and template_context.is_account_template
            else None
        )

        if not st.session_state.get("header_review_complete"):
            mapping_rows, type_confirmed, continue_clicked = render_mapping_confirmation(
                st.session_state["mapping_rows"],
                field_catalog,
                required_type,
                type_metadata_valid=template_context.account_type_valid if template_context else True,
                type_metadata_error=template_context.account_type_error if template_context else None,
                template_name=template,
                uploaded_headers=raw_headers,
                load_operation=load_operation,
                template_context=template_context,
                is_account_template=context["is_account_template"],
            )
            st.session_state["mapping_rows"] = mapping_rows
            st.session_state["type_confirmed"] = type_confirmed

            if continue_clicked:
                try:
                    mapped_df = build_mapped_dataframe(original_df, mapping_rows)
                    st.session_state["mapped_df"] = mapped_df
                    st.session_state["proposed_df"] = mapped_df.copy()
                    st.session_state["header_review_complete"] = True
                    st.session_state.pop("row_correction_plan", None)
                    st.session_state.pop("workbench_preparation_plan", None)
                    st.session_state.pop("preparation_result", None)
                    st.session_state.pop("validation_bundle", None)
                    st.success("Header review complete. Continue to row-level data validation.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        else:
            mapping_rows = st.session_state["mapping_rows"]
            type_confirmed = st.session_state.get("type_confirmed", False)
            mapped_df = st.session_state.get("mapped_df")
            mapped_headers = list(mapped_df.columns) if mapped_df is not None else raw_headers
            working_df = mapped_df if mapped_df is not None else original_df

            render_picklist_metadata_debug(
                template_context.salesforce_object if template_context else None,
                template_context.record_type_name if template_context else None,
            )

            validation_bundle = run_full_validation(
                working_df,
                mapped_headers,
                upload_method,
                template,
                mapping_rows=mapping_rows,
                load_operation=load_operation,
                type_confirmed=type_confirmed if context["is_account_template"] else True,
                preparation_result=st.session_state.get("preparation_result"),
                use_mapped_columns=True,
                preparation_task=preparation_task,
            )
            st.session_state["validation_bundle"] = validation_bundle

            ready_for_data_quality, data_quality_block_msg = mappings_ready_for_data_quality(
                mapping_rows,
                type_confirmed if context["is_account_template"] else True,
                context["is_account_template"],
                template_context,
            )

            if not ready_for_data_quality:
                st.info(data_quality_block_msg)
            else:
                date_field_types = build_date_field_types(working_df, template, mapping_rows=mapping_rows)
                if date_field_types and not st.session_state.get("date_conversions_approved"):
                    st.divider()
                    date_approval = render_date_format_review(
                        working_df,
                        date_field_types,
                        upload_method,
                        session_key_prefix="wb_date_format",
                    )
                    if date_approval is not None:
                        converted_df, date_change_log = apply_date_format_review(working_df, date_approval)
                        st.session_state["mapped_df"] = converted_df
                        st.session_state["proposed_df"] = converted_df.copy()
                        st.session_state["source_date_format"] = date_approval.get("source_format")
                        st.session_state["date_conversion_plan"] = date_approval.get("plan")
                        if date_approval.get("approved"):
                            st.session_state["date_conversions_approved"] = True
                            st.session_state.pop("row_correction_plan", None)
                            st.session_state.pop("workbench_preparation_plan", None)
                            working_df = converted_df
                            mapped_df = converted_df
                            mapped_headers = list(converted_df.columns)
                            if date_change_log:
                                st.success(f"Applied {len(date_change_log)} date conversion(s).")
                            st.rerun()
                        if date_approval.get("declined"):
                            st.session_state["date_conversions_approved"] = True
                            st.rerun()

            if ready_for_data_quality and "row_correction_plan" not in st.session_state:
                try:
                    raw_content = uploaded_file.getvalue().decode("utf-8-sig")
                    st.session_state["row_correction_plan"] = build_row_correction_plan_proposal(
                        working_df,
                        upload_method,
                        template,
                        mapping_rows=mapping_rows,
                        raw_csv_content=raw_content,
                        source_date_format=st.session_state.get("source_date_format"),
                    )
                except ValueError as exc:
                    st.error(str(exc))

            row_plan = st.session_state.get("row_correction_plan") or {}
            workbench_plan = st.session_state.get("workbench_preparation_plan")

            if ready_for_data_quality and row_plan and not workbench_plan:
                st.session_state["workbench_preparation_plan"] = build_workbench_preparation_plan_proposal(
                    working_df,
                    mapping_rows,
                    template,
                    load_operation,
                    type_confirmed if context["is_account_template"] else True,
                    row_correction_plan=row_plan,
                    mapping_applied=True,
                )
                workbench_plan = st.session_state["workbench_preparation_plan"]

            prep_complete = bool(st.session_state.get("preparation_result"))
            if not prep_complete and ready_for_data_quality and row_plan:
                data_approval = render_data_preparation_review(
                    row_plan,
                    workbench_plan=workbench_plan,
                    mapping_rows=mapping_rows,
                    picklist_validation=validation_bundle.get("picklist_validation"),
                )
                if data_approval is not None:
                    if data_approval.get("declined"):
                        row_plan["corrections_declined"] = True
                        if workbench_plan:
                            workbench_plan["corrections_declined"] = True
                        result = apply_file_preparation(
                            original_df,
                            raw_headers,
                            upload_method,
                            template,
                            load_operation,
                            {},
                            set(),
                            mapping_rows=mapping_rows,
                            type_confirmed=type_confirmed if context["is_account_template"] else True,
                            mapped_df=mapped_df,
                        )
                    else:
                        if not workbench_plan:
                            workbench_plan = build_workbench_preparation_plan_proposal(
                                working_df,
                                mapping_rows,
                                template,
                                load_operation,
                                type_confirmed if context["is_account_template"] else True,
                                row_correction_plan=row_plan,
                                mapping_applied=True,
                            )
                        try:
                            result = apply_file_preparation(
                                original_df,
                                raw_headers,
                                upload_method,
                                template,
                                load_operation,
                                {},
                                data_approval["enabled_change_ids"],
                                mapping_rows=mapping_rows,
                                type_confirmed=type_confirmed if context["is_account_template"] else True,
                                row_correction_plan=row_plan,
                                enabled_row_issue_ids=data_approval["enabled_issue_ids"],
                                preparation_plan=workbench_plan,
                                mapped_df=mapped_df,
                            )
                            row_plan["corrections_applied"] = True
                            row_plan["enabled_issue_ids"] = sorted(data_approval["enabled_issue_ids"])
                            if workbench_plan:
                                workbench_plan["corrections_applied"] = True
                                workbench_plan["enabled_change_ids"] = sorted(
                                    data_approval["enabled_change_ids"]
                                )
                        except ValueError as exc:
                            st.error(str(exc))
                            result = None

                        if result is not None:
                            picklist_plan = st.session_state.get("picklist_correction_plan") or {}
                            result = merge_picklist_change_log(result, picklist_plan)
                            st.session_state["preparation_result"] = result
                            st.session_state["proposed_df"] = result.get("proposed_df")
                            st.session_state["row_correction_plan"] = row_plan
                            st.session_state["workbench_preparation_plan"] = workbench_plan

                            raw_content = uploaded_file.getvalue().decode("utf-8-sig")
                            revalidation = revalidate_after_corrections(
                                original_df,
                                mapped_headers,
                                result["corrected_df"],
                                upload_method,
                                template,
                                load_operation,
                                mapping_rows,
                                result,
                                None,
                                row_correction_plan=row_plan,
                                raw_csv_content=raw_content,
                                use_mapped_columns=True,
                                source_date_format=st.session_state.get("source_date_format"),
                            )
                            st.session_state["validation_bundle"] = revalidation["validation_bundle"]
                            st.success("Approved data changes applied to a working copy of your file.")
                            st.rerun()

            preparation_result = st.session_state.get("preparation_result")
            if preparation_result and preparation_result.get("corrected_df") is not None:
                result = preparation_result
                row_plan = st.session_state.get("row_correction_plan")
                date_field_types = build_date_field_types(working_df, template, mapping_rows=mapping_rows)
                result = attach_date_validation_to_preparation(
                    result,
                    result["corrected_df"],
                    date_field_types,
                    upload_method,
                    st.session_state.get("source_date_format"),
                ) or result
                st.session_state["preparation_result"] = result
                issue_update = render_fix_issues_in_copilot(
                    preparation_result=result,
                    original_df=original_df,
                    row_correction_plan=row_plan,
                    picklist_validation=validation_bundle.get("picklist_validation"),
                    mapped_df=result["corrected_df"],
                    upload_method=upload_method,
                    template=template,
                    mapping_rows=mapping_rows,
                    validation_bundle=validation_bundle,
                    date_field_types=date_field_types,
                    source_date_format=st.session_state.get("source_date_format"),
                    template_context=template_context,
                    raw_csv_content=uploaded_file.getvalue().decode("utf-8-sig"),
                    use_mapped_columns=True,
                    session_key_prefix="wb_fix_issues",
                )
                if issue_update is not None:
                    st.session_state["preparation_result"] = issue_update["preparation_result"]
                    st.session_state["validation_bundle"] = issue_update["validation_bundle"]
                    st.session_state["row_correction_plan"] = issue_update["row_correction_plan"]
                    st.session_state["mapped_df"] = issue_update["preparation_result"]["corrected_df"]
                    st.session_state["proposed_df"] = issue_update["preparation_result"]["corrected_df"].copy()
                    st.success("Correction saved to the working copy.")
                    st.rerun()

            picklist_approval = render_picklist_validation(
                validation_bundle.get("picklist_validation", {}),
                working_df,
                mapping_rows,
                template_context,
            )
            if picklist_approval is not None:
                corrected_df, picklist_revalidation, picklist_plan = apply_picklist_validation_result(
                    working_df,
                    validation_bundle.get("picklist_validation", {}),
                    picklist_approval,
                    mapping_rows,
                    template_context,
                )
                st.session_state["mapped_df"] = corrected_df
                st.session_state["proposed_df"] = corrected_df.copy()
                st.session_state["picklist_correction_plan"] = picklist_plan
                validation_bundle["picklist_validation"] = picklist_revalidation
                st.session_state["validation_bundle"] = validation_bundle
                working_df = corrected_df
                mapped_df = corrected_df
                mapped_headers = list(corrected_df.columns)
                st.success("Approved picklist replacements applied to the mapped working copy.")
                st.rerun()

            prerequisite_status = st.session_state.get("upload_prerequisites", {})
            deployment_templates = st.session_state.get("deployment_templates") or [template]
            if len(deployment_templates) <= 1:
                prerequisite_status = render_data_preparation_warnings(
                    template,
                    deployment_templates=deployment_templates,
                    prerequisite_status=prerequisite_status,
                )
            else:
                prerequisite_status = render_upload_order_guidance(
                    template,
                    deployment_templates=deployment_templates,
                    prerequisite_status=prerequisite_status,
                )
            st.session_state["upload_prerequisites"] = prerequisite_status
            validation_bundle["upload_order_plan"] = build_upload_order_plan(
                deployment_templates,
                prerequisite_status=prerequisite_status,
                included_templates=set(deployment_templates),
            )
            st.session_state["validation_bundle"] = validation_bundle

            record_check_approval = render_salesforce_record_check(
                working_df,
                mapping_rows,
                template_context,
                load_operation,
                validation_bundle.get("record_existence_validation"),
                use_mapped_columns=True,
            )
            if record_check_approval is not None and record_check_approval.get("rerun"):
                record_result = apply_salesforce_record_check(
                    working_df,
                    mapping_rows,
                    template_context,
                    load_operation,
                    record_check_approval,
                    use_mapped_columns=True,
                )
                validation_bundle["record_existence_validation"] = record_result
                st.session_state["validation_bundle"] = validation_bundle
                st.success("Salesforce record check complete.")
                st.rerun()

            if st.session_state.get("preparation_result"):
                result = st.session_state["preparation_result"]
                row_plan = st.session_state.get("row_correction_plan")
                date_field_types = build_date_field_types(working_df, template, mapping_rows=mapping_rows)
                result = attach_date_validation_to_preparation(
                    result,
                    result["corrected_df"],
                    date_field_types,
                    upload_method,
                    st.session_state.get("source_date_format"),
                ) or result
                st.session_state["preparation_result"] = result
                validation_bundle = st.session_state.get("validation_bundle") or run_full_validation(
                    working_df,
                    mapped_headers,
                    upload_method,
                    template,
                    mapping_rows=mapping_rows,
                    load_operation=load_operation,
                    type_confirmed=type_confirmed if context["is_account_template"] else True,
                    preparation_result=result,
                    use_mapped_columns=True,
                    preparation_task=preparation_task,
                )
                can_download, download_msg = evaluate_shared_download_readiness(
                    upload_method=upload_method,
                    template=template,
                    mapping_rows=mapping_rows,
                    type_confirmed=type_confirmed if context["is_account_template"] else True,
                    load_operation=load_operation,
                    preparation_result=result,
                    validation_result=validation_bundle,
                    row_correction_plan=row_plan,
                    preparation_only=preparation_only,
                )
                render_preparation_results(
                    result,
                    template,
                    uploaded_file.name,
                    upload_method,
                    can_download,
                    download_msg,
                    validation_result=validation_bundle,
                    preparation_only=preparation_only,
                )

            render_validation_results(validation_bundle)

            st.divider()
            st.subheader("Upload Readiness")
            readiness = evaluate_preparation_readiness(
                header_review_complete=True,
                preparation_result=st.session_state.get("preparation_result"),
                row_correction_plan=st.session_state.get("row_correction_plan"),
                workbench_plan=st.session_state.get("workbench_preparation_plan"),
                validation_result=st.session_state.get("validation_bundle"),
                preparation_task=preparation_task,
                upload_method=upload_method,
                template=template,
                deployment_templates=st.session_state.get("deployment_templates") or [template],
                upload_prerequisites=st.session_state.get("upload_prerequisites"),
                preparation_warnings_acknowledged=st.session_state.get("preparation_warnings_acknowledged"),
                prerequisites_confirmed=st.session_state.get(SESSION_PREREQ_CONFIRMED, False),
            )
            render_readiness(readiness)
