"""Upload order and dependency graph guidance for multi-template deployments."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from adapters.sfdx_metadata.models import FieldDefinition
from services.constants import (
    PREREQ_STATUS_ALREADY_LOADED,
    PREREQ_STATUS_INCLUDED,
    PREREQ_STATUS_NOT_LOADED,
    PREREQ_STATUS_UNKNOWN,
)
from services.lookup_field_detection_service import is_lookup_field
from services.template_service import TemplateContext, get_adapter, resolve_template

_RULES_PATH = Path(__file__).resolve().parent.parent / "rules" / "dependencies.json"


def load_dependency_rules() -> list[dict[str, Any]]:
    if not _RULES_PATH.exists():
        return []
    with _RULES_PATH.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload.get("rules", [])


def build_upload_order_plan(
    templates: list[str],
    *,
    prerequisite_status: dict[str, str] | None = None,
    included_templates: set[str] | None = None,
) -> dict[str, Any]:
    """
    Build recommended upload order and prerequisite guidance for selected templates.

    `templates` may contain a single template for prerequisite-only guidance.
    """
    included_templates = included_templates or set(templates)
    prerequisite_status = prerequisite_status or {}
    resolved = [_resolve_template_entry(name) for name in templates]
    resolved = [item for item in resolved if item is not None]

    graph_edges = _build_graph_edges(resolved)
    cycles = _detect_cycles(graph_edges)
    ordered_steps, unresolved = _topological_order(resolved, graph_edges, cycles)

    steps: list[dict[str, Any]] = []
    for index, entry in enumerate(ordered_steps, start=1):
        parents = _parents_for_template(entry["template"], graph_edges)
        readiness, prereq_status = _step_readiness(
            entry["template"],
            parents,
            included_templates,
            prerequisite_status,
        )
        steps.append({
            "step": index,
            "template": entry["template"],
            "object": entry["object"],
            "reason": _step_reason(entry["template"], parents),
            "required_parent": ", ".join(parent["template"] for parent in parents) or "None",
            "dependency_field": ", ".join(
                str(edge.get("dependency_field") or "")
                for edge in _edges_for_child(entry["template"], graph_edges)
            ) or "Metadata / business rule",
            "readiness": readiness,
            "prerequisite_status": prereq_status,
            "parents": parents,
        })

    missing_parents = _missing_parents(resolved, included_templates, prerequisite_status, graph_edges)
    issues = _dependency_issues(resolved, cycles, missing_parents, unresolved)

    return {
        "templates": templates,
        "steps": steps,
        "cycles": cycles,
        "missing_parents": missing_parents,
        "issues": issues,
        "graph_edges": graph_edges,
        "message": (
            "Upload order could not be fully resolved because a circular dependency was detected."
            if cycles
            else "Recommended upload order calculated from metadata and business rules."
        ),
    }


def get_prerequisites_for_template(
    template: str,
    *,
    prerequisite_status: dict[str, str] | None = None,
    included_templates: set[str] | None = None,
) -> dict[str, Any]:
    """Return prerequisite guidance for a single uploaded file."""
    included_templates = included_templates or {template}
    plan = build_upload_order_plan(
        [template],
        prerequisite_status=prerequisite_status,
        included_templates=included_templates,
    )
    entry = _resolve_template_entry(template)
    parents = plan["missing_parents"]
    if not parents and entry:
        parents = [
            {
                "template": parent["template"],
                "object": parent["object"],
                "dependency_field": parent.get("dependency_field", ""),
                "reason": parent.get("reason", ""),
                "status": _resolve_prerequisite_status(
                    parent["template"],
                    included_templates,
                    prerequisite_status or {},
                ),
            }
            for parent in _parents_for_template(template, plan["graph_edges"])
        ]
    return {
        "current_template": template,
        "current_object": entry["object"] if entry else None,
        "prerequisites": parents or plan["missing_parents"],
        "steps": plan["steps"],
        "issues": plan["issues"],
        "message": plan["message"],
    }


def build_dependency_issues_report(plan: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for issue in plan.get("issues", []):
        rows.append({
            "Issue Type": issue.get("type"),
            "Template": issue.get("template"),
            "Object": issue.get("object"),
            "Parent Template": issue.get("parent_template"),
            "Dependency Field": issue.get("dependency_field"),
            "Reason": issue.get("reason"),
            "Recommended Action": issue.get("recommended_action"),
        })
    for missing in plan.get("missing_parents", []):
        rows.append({
            "Issue Type": "missing_parent",
            "Template": missing.get("child_template"),
            "Object": missing.get("child_object"),
            "Parent Template": missing.get("parent_template"),
            "Dependency Field": missing.get("dependency_field"),
            "Reason": missing.get("reason"),
            "Recommended Action": missing.get("recommended_action"),
        })
    return rows


def build_upload_order_report_rows(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "Step": step.get("step"),
            "Template": step.get("template"),
            "Salesforce Object": step.get("object"),
            "Reason": step.get("reason"),
            "Required Parent": step.get("required_parent"),
            "Dependency Field": step.get("dependency_field"),
            "Readiness": step.get("readiness"),
            "Prerequisite Status": step.get("prerequisite_status"),
        }
        for step in plan.get("steps", [])
    ]


def _resolve_template_entry(template: str) -> dict[str, Any] | None:
    context = resolve_template(template)
    if context is None:
        return None
    return {
        "template": template,
        "object": context.salesforce_object or template,
        "context": context,
    }


def _build_graph_edges(resolved: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    template_names = {entry["template"] for entry in resolved}
    adapter = get_adapter()

    for rule in load_dependency_rules():
        rule_type = rule.get("type")
        if rule_type == "object_load_order":
            edges.append({
                "parent_template": rule.get("parent_template"),
                "parent_object": rule.get("parent_object"),
                "child_template": rule.get("child_template"),
                "child_object": rule.get("child_object"),
                "dependency_field": rule.get("dependency_field"),
                "reason": rule.get("message") or rule.get("reason"),
                "source": rule.get("id", "object_load_order"),
            })
        elif rule_type == "cross_template_reference":
            edges.append({
                "parent_template": rule.get("parent_template"),
                "parent_object": rule.get("parent_object"),
                "child_template": rule.get("template"),
                "child_object": _object_for_template(rule.get("template"), resolved),
                "dependency_field": rule.get("field"),
                "reason": rule.get("message") or (
                    f"{rule.get('template')} references {rule.get('parent_template')}."
                ),
                "source": rule.get("id", "cross_template_reference"),
            })

    for entry in resolved:
        context: TemplateContext = entry["context"]
        object_name = context.salesforce_object
        if not object_name:
            continue
        object_fields = adapter.get_object_fields(object_name)
        for field_def in object_fields.values():
            if not is_lookup_field(field_def):
                continue
            parent_object = field_def.reference_to
            if not parent_object:
                continue
            parent_template = _template_for_object(parent_object, resolved)
            if parent_template and parent_template != entry["template"]:
                edges.append({
                    "parent_template": parent_template,
                    "parent_object": parent_object,
                    "child_template": entry["template"],
                    "child_object": object_name,
                    "dependency_field": field_def.api_name,
                    "reason": f"{entry['template']} lookup `{field_def.api_name}` references {parent_object}.",
                    "source": "metadata_lookup",
                })

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in edges:
        key = (
            str(edge.get("parent_template")),
            str(edge.get("child_template")),
            str(edge.get("dependency_field")),
        )
        if key in seen:
            continue
        seen.add(key)
        if edge.get("child_template") in template_names or edge.get("parent_template") in template_names:
            deduped.append(edge)
    return deduped


def _template_for_object(object_name: str, resolved: list[dict[str, Any]]) -> str | None:
    for entry in resolved:
        if entry["object"] == object_name:
            return entry["template"]
    for rule in load_dependency_rules():
        if rule.get("parent_object") == object_name and rule.get("parent_template"):
            return rule["parent_template"]
        if rule.get("child_object") == object_name and rule.get("child_template"):
            return rule["child_template"]
    return None


def _object_for_template(template: str | None, resolved: list[dict[str, Any]]) -> str | None:
    if not template:
        return None
    for entry in resolved:
        if entry["template"] == template:
            return entry["object"]
    context = resolve_template(template)
    return context.salesforce_object if context else template


def _parents_for_template(template: str, edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parents: list[dict[str, Any]] = []
    seen: set[str] = set()
    for edge in edges:
        if edge.get("child_template") != template:
            continue
        parent_template = edge.get("parent_template")
        if not parent_template or parent_template in seen:
            continue
        seen.add(parent_template)
        parents.append({
            "template": parent_template,
            "object": edge.get("parent_object"),
            "dependency_field": edge.get("dependency_field"),
            "reason": edge.get("reason"),
        })
    return parents


def _edges_for_child(template: str, edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [edge for edge in edges if edge.get("child_template") == template]


def _detect_cycles(edges: list[dict[str, Any]]) -> list[list[str]]:
    graph: dict[str, set[str]] = {}
    nodes: set[str] = set()
    for edge in edges:
        parent = edge.get("parent_template")
        child = edge.get("child_template")
        if not parent or not child or parent == child:
            continue
        nodes.add(parent)
        nodes.add(child)
        graph.setdefault(child, set()).add(parent)

    cycles: list[list[str]] = []
    visited: set[str] = set()
    stack: set[str] = set()
    path: list[str] = []

    def visit(node: str) -> None:
        if node in stack:
            if node in path:
                start = path.index(node)
                cycle = path[start:] + [node]
                if cycle not in cycles:
                    cycles.append(cycle)
            return
        if node in visited:
            return
        visited.add(node)
        stack.add(node)
        path.append(node)
        for parent in graph.get(node, set()):
            visit(parent)
        path.pop()
        stack.remove(node)

    for node in sorted(nodes):
        visit(node)
    return cycles


def _topological_order(
    resolved: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    cycles: list[list[str]],
) -> tuple[list[dict[str, Any]], list[str]]:
    if cycles:
        return resolved, [entry["template"] for entry in resolved]

    indegree: dict[str, int] = {entry["template"]: 0 for entry in resolved}
    adjacency: dict[str, set[str]] = {entry["template"]: set() for entry in resolved}
    for edge in edges:
        parent = edge.get("parent_template")
        child = edge.get("child_template")
        if parent not in indegree or child not in indegree or parent == child:
            continue
        if parent not in adjacency[child]:
            adjacency[child].add(parent)
            indegree[child] += 1

    queue = sorted(template for template, degree in indegree.items() if degree == 0)
    ordered_names: list[str] = []
    while queue:
        current = queue.pop(0)
        ordered_names.append(current)
        for child, parents in adjacency.items():
            if current not in parents:
                continue
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
        queue.sort()

    unresolved = [name for name, degree in indegree.items() if degree > 0]
    lookup = {entry["template"]: entry for entry in resolved}
    ordered = [lookup[name] for name in ordered_names if name in lookup]
    for name in unresolved:
        if name in lookup and lookup[name] not in ordered:
            ordered.append(lookup[name])
    return ordered, unresolved


def _missing_parents(
    resolved: list[dict[str, Any]],
    included_templates: set[str],
    prerequisite_status: dict[str, str],
    edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for entry in resolved:
        for parent in _parents_for_template(entry["template"], edges):
            status = _resolve_prerequisite_status(
                parent["template"],
                included_templates,
                prerequisite_status,
            )
            if status in {PREREQ_STATUS_ALREADY_LOADED, PREREQ_STATUS_INCLUDED}:
                continue
            missing.append({
                "child_template": entry["template"],
                "child_object": entry["object"],
                "parent_template": parent["template"],
                "parent_object": parent.get("object"),
                "dependency_field": parent.get("dependency_field"),
                "reason": parent.get("reason") or (
                    f"{entry['template']} references {parent['template']}."
                ),
                "status": status,
                "recommended_action": (
                    f"Load {parent['template']} first or mark it as Already loaded."
                ),
            })
    return missing


def _dependency_issues(
    resolved: list[dict[str, Any]],
    cycles: list[list[str]],
    missing_parents: list[dict[str, Any]],
    unresolved: list[str],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for cycle in cycles:
        issues.append({
            "type": "cycle",
            "template": " -> ".join(cycle),
            "object": None,
            "parent_template": None,
            "dependency_field": None,
            "reason": "Circular dependency detected in upload order.",
            "recommended_action": "Resolve circular references before upload.",
        })
    for template in unresolved:
        entry = next((item for item in resolved if item["template"] == template), None)
        issues.append({
            "type": "unresolved_order",
            "template": template,
            "object": entry["object"] if entry else None,
            "parent_template": None,
            "dependency_field": None,
            "reason": "Upload order could not be fully resolved.",
            "recommended_action": "Review parent dependencies and prerequisite status.",
        })
    for missing in missing_parents:
        if missing.get("status") == PREREQ_STATUS_NOT_LOADED:
            issues.append({
                "type": "missing_parent",
                "template": missing.get("child_template"),
                "object": missing.get("child_object"),
                "parent_template": missing.get("parent_template"),
                "dependency_field": missing.get("dependency_field"),
                "reason": missing.get("reason"),
                "recommended_action": missing.get("recommended_action"),
            })
    return issues


def _step_readiness(
    template: str,
    parents: list[dict[str, Any]],
    included_templates: set[str],
    prerequisite_status: dict[str, str],
) -> tuple[str, str]:
    if not parents:
        return "Ready", PREREQ_STATUS_INCLUDED
    statuses = [
        _resolve_prerequisite_status(parent["template"], included_templates, prerequisite_status)
        for parent in parents
    ]
    if all(status in {PREREQ_STATUS_ALREADY_LOADED, PREREQ_STATUS_INCLUDED} for status in statuses):
        return "Ready", PREREQ_STATUS_INCLUDED
    if any(status == PREREQ_STATUS_NOT_LOADED for status in statuses):
        return "Blocked", PREREQ_STATUS_NOT_LOADED
    if any(status == PREREQ_STATUS_UNKNOWN for status in statuses):
        return "Needs Review", PREREQ_STATUS_UNKNOWN
    return "Needs Review", statuses[0]


def _resolve_prerequisite_status(
    parent_template: str,
    included_templates: set[str],
    prerequisite_status: dict[str, str],
) -> str:
    if parent_template in prerequisite_status:
        return prerequisite_status[parent_template]
    if parent_template in included_templates:
        return PREREQ_STATUS_INCLUDED
    return PREREQ_STATUS_UNKNOWN


def _step_reason(template: str, parents: list[dict[str, Any]]) -> str:
    if not parents:
        return f"{template} has no unresolved parent dependencies in the selected batch."
    parent_names = ", ".join(parent["template"] for parent in parents)
    return f"{template} references {parent_names} and should be loaded after those templates."


def build_preparation_warnings(
    template: str,
    *,
    deployment_templates: list[str] | None = None,
    prerequisite_status: dict[str, str] | None = None,
    upload_order_plan: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build business-friendly preparation warnings from dependency rules only."""
    deployment_templates = deployment_templates or [template]
    prerequisite_status = prerequisite_status or {}
    included_templates = set(deployment_templates)

    if upload_order_plan is None:
        upload_order_plan = build_upload_order_plan(
            deployment_templates,
            prerequisite_status=prerequisite_status,
            included_templates=included_templates,
        )

    prereq_info = get_prerequisites_for_template(
        template,
        prerequisite_status=prerequisite_status,
        included_templates=included_templates,
    )

    warnings: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _append_warning(
        *,
        parent_template: str,
        reason: str,
        dependency_field: str | None = None,
        recommended_action: str | None = None,
    ) -> None:
        if not parent_template or parent_template in seen:
            return
        seen.add(parent_template)
        status = _resolve_prerequisite_status(
            parent_template,
            included_templates,
            prerequisite_status,
        )
        already_satisfied = status in {PREREQ_STATUS_ALREADY_LOADED, PREREQ_STATUS_INCLUDED}
        warnings.append({
            "id": f"prereq_{parent_template}",
            "message": f"{parent_template} should be uploaded before {template}.",
            "required_prerequisite": parent_template,
            "parent_template": parent_template,
            "current_template": template,
            "reason": reason,
            "recommended_action": recommended_action or (
                f"Upload {parent_template} first, or confirm it is already loaded in Salesforce."
            ),
            "dependency_field": dependency_field,
            "prerequisite_status": status,
            "already_satisfied": already_satisfied,
        })

    for parent in prereq_info.get("prerequisites", []):
        _append_warning(
            parent_template=str(parent.get("template") or ""),
            reason=str(
                parent.get("reason")
                or f"{template} depends on {parent.get('template')}."
            ),
            dependency_field=parent.get("dependency_field"),
        )

    for missing in upload_order_plan.get("missing_parents", []):
        if missing.get("child_template") != template:
            continue
        _append_warning(
            parent_template=str(missing.get("parent_template") or ""),
            reason=str(missing.get("reason") or ""),
            dependency_field=missing.get("dependency_field"),
            recommended_action=missing.get("recommended_action"),
        )

    return warnings


def is_preparation_warning_acknowledged(
    warning: dict[str, Any],
    *,
    prerequisite_status: dict[str, str],
    preparation_warnings_acknowledged: dict[str, bool],
) -> bool:
    """Return True when a warning is satisfied or explicitly acknowledged."""
    parent_template = warning.get("parent_template")
    if not parent_template:
        return True
    status = prerequisite_status.get(
        parent_template,
        warning.get("prerequisite_status", PREREQ_STATUS_UNKNOWN),
    )
    if status in {PREREQ_STATUS_ALREADY_LOADED, PREREQ_STATUS_INCLUDED}:
        return True
    return bool(preparation_warnings_acknowledged.get(parent_template))


def preparation_warnings_fully_acknowledged(
    warnings: list[dict[str, Any]],
    *,
    prerequisite_status: dict[str, str],
    preparation_warnings_acknowledged: dict[str, bool],
) -> bool:
    if not warnings:
        return True
    return all(
        is_preparation_warning_acknowledged(
            warning,
            prerequisite_status=prerequisite_status,
            preparation_warnings_acknowledged=preparation_warnings_acknowledged,
        )
        for warning in warnings
    )


def unacknowledged_preparation_warnings(
    warnings: list[dict[str, Any]],
    *,
    prerequisite_status: dict[str, str],
    preparation_warnings_acknowledged: dict[str, bool],
) -> list[dict[str, Any]]:
    return [
        warning for warning in warnings
        if not is_preparation_warning_acknowledged(
            warning,
            prerequisite_status=prerequisite_status,
            preparation_warnings_acknowledged=preparation_warnings_acknowledged,
        )
    ]
