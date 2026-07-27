"""Capture and compare Salesforce metadata snapshots for change detection."""

from __future__ import annotations

from dataclasses import dataclass

from adapters.sfdx_metadata.adapter import SfdxMetadataAdapter


@dataclass(frozen=True)
class MetadataCounts:
    objects: int
    fields: int
    picklists: int
    templates: int


def count_metadata(adapter: SfdxMetadataAdapter) -> MetadataCounts:
    loader = adapter._loader
    object_count = len(loader.object_fields)
    field_count = sum(len(fields) for fields in loader.object_fields.values())
    picklist_count = 0
    for fields in loader.object_fields.values():
        for field in fields.values():
            if (
                field.inline_picklist_values
                or field.global_value_set
                or field.standard_value_set
                or field.field_type in {"Picklist", "MultiselectPicklist"}
            ):
                picklist_count += 1
    template_count = len(adapter.list_templates())
    return MetadataCounts(
        objects=object_count,
        fields=field_count,
        picklists=picklist_count,
        templates=template_count,
    )


@dataclass(frozen=True)
class MetadataSnapshot:
    commit_hash: str | None
    counts: MetadataCounts
    fields_by_object: dict[str, frozenset[str]]
    picklist_values: dict[str, frozenset[str]]
    record_type_restrictions: dict[str, frozenset[str]]
    template_names: frozenset[str]


@dataclass(frozen=True)
class MetadataChangeSummary:
    picklist_values_added: tuple[str, ...] = ()
    picklist_values_removed: tuple[str, ...] = ()
    fields_added: tuple[str, ...] = ()
    fields_removed: tuple[str, ...] = ()
    record_type_changes: tuple[str, ...] = ()
    templates_added: tuple[str, ...] = ()
    templates_removed: tuple[str, ...] = ()
    templates_updated: tuple[str, ...] = ()

    @property
    def has_changes(self) -> bool:
        return bool(
            self.picklist_values_added
            or self.picklist_values_removed
            or self.fields_added
            or self.fields_removed
            or self.record_type_changes
            or self.templates_added
            or self.templates_removed
            or self.templates_updated
        )

    @property
    def has_detailed_changes(self) -> bool:
        return self.has_changes

    def display_lines(self) -> list[str]:
        if not self.has_detailed_changes:
            return ["Metadata version changed. Revalidation is required."]
        lines: list[str] = []
        if self.picklist_values_added:
            lines.append(
                f"Picklist values added ({len(self.picklist_values_added)}): "
                + ", ".join(self.picklist_values_added[:10])
                + ("..." if len(self.picklist_values_added) > 10 else "")
            )
        if self.picklist_values_removed:
            lines.append(
                f"Picklist values removed ({len(self.picklist_values_removed)}): "
                + ", ".join(self.picklist_values_removed[:10])
                + ("..." if len(self.picklist_values_removed) > 10 else "")
            )
        if self.fields_added:
            lines.append(
                f"Fields added ({len(self.fields_added)}): "
                + ", ".join(self.fields_added[:10])
                + ("..." if len(self.fields_added) > 10 else "")
            )
        if self.fields_removed:
            lines.append(
                f"Fields removed ({len(self.fields_removed)}): "
                + ", ".join(self.fields_removed[:10])
                + ("..." if len(self.fields_removed) > 10 else "")
            )
        if self.record_type_changes:
            lines.append(
                f"Record-type restrictions changed ({len(self.record_type_changes)}): "
                + ", ".join(self.record_type_changes[:10])
                + ("..." if len(self.record_type_changes) > 10 else "")
            )
        if self.templates_added:
            lines.append(f"Templates added: {', '.join(self.templates_added)}")
        if self.templates_removed:
            lines.append(f"Templates removed: {', '.join(self.templates_removed)}")
        if self.templates_updated:
            lines.append(f"Templates updated: {', '.join(self.templates_updated)}")
        return lines

    @classmethod
    def fallback(cls) -> MetadataChangeSummary:
        return cls()


def capture_metadata_snapshot(
    adapter: SfdxMetadataAdapter,
    commit_hash: str | None = None,
) -> MetadataSnapshot:
    """Build a point-in-time snapshot of loaded adapter metadata."""
    loader = adapter._loader
    fields_by_object = {
        object_name: frozenset(fields.keys())
        for object_name, fields in loader.object_fields.items()
    }

    picklist_values: dict[str, frozenset[str]] = {}
    for object_name, fields in loader.object_fields.items():
        for field_name, field_def in fields.items():
            if not (
                field_def.inline_picklist_values
                or field_def.global_value_set
                or field_def.standard_value_set
                or field_def.field_type in {"Picklist", "MultiselectPicklist"}
            ):
                continue
            active_values = adapter.get_picklist_values(object_name, field_name)
            picklist_values[f"{object_name}.{field_name}"] = frozenset(active_values)

    record_type_restrictions: dict[str, frozenset[str]] = {}
    seen_record_types: set[tuple[str, str]] = set()
    for (object_name, _normalized_name), record_type in loader.record_types.items():
        key = (object_name, record_type.name)
        if key in seen_record_types:
            continue
        seen_record_types.add(key)
        for field_name, values in record_type.picklist_values.items():
            restriction_key = f"{object_name}|{record_type.name}|{field_name}"
            record_type_restrictions[restriction_key] = frozenset(values)

    template_names = frozenset(template.name for template in adapter.list_templates())
    return MetadataSnapshot(
        commit_hash=commit_hash,
        counts=count_metadata(adapter),
        fields_by_object=fields_by_object,
        picklist_values=picklist_values,
        record_type_restrictions=record_type_restrictions,
        template_names=template_names,
    )


def compare_metadata_snapshots(
    before: MetadataSnapshot | None,
    after: MetadataSnapshot,
) -> MetadataChangeSummary | None:
    """Compare two snapshots and return a human-readable change summary."""
    if before is None:
        return None

    fields_added: list[str] = []
    fields_removed: list[str] = []
    all_objects = set(before.fields_by_object) | set(after.fields_by_object)
    for object_name in sorted(all_objects):
        before_fields = before.fields_by_object.get(object_name, frozenset())
        after_fields = after.fields_by_object.get(object_name, frozenset())
        for field_name in sorted(after_fields - before_fields):
            fields_added.append(f"{object_name}.{field_name}")
        for field_name in sorted(before_fields - after_fields):
            fields_removed.append(f"{object_name}.{field_name}")

    picklist_added: list[str] = []
    picklist_removed: list[str] = []
    all_picklists = set(before.picklist_values) | set(after.picklist_values)
    for picklist_key in sorted(all_picklists):
        before_values = before.picklist_values.get(picklist_key, frozenset())
        after_values = after.picklist_values.get(picklist_key, frozenset())
        for value in sorted(after_values - before_values):
            picklist_added.append(f"{picklist_key}: {value}")
        for value in sorted(before_values - after_values):
            picklist_removed.append(f"{picklist_key}: {value}")

    record_type_changes: list[str] = []
    all_restrictions = set(before.record_type_restrictions) | set(after.record_type_restrictions)
    for restriction_key in sorted(all_restrictions):
        before_values = before.record_type_restrictions.get(restriction_key, frozenset())
        after_values = after.record_type_restrictions.get(restriction_key, frozenset())
        if before_values != after_values:
            record_type_changes.append(restriction_key.replace("|", " / "))

    templates_added = sorted(after.template_names - before.template_names)
    templates_removed = sorted(before.template_names - after.template_names)
    templates_updated: list[str] = []
    shared_templates = before.template_names & after.template_names
    if before.counts.templates != after.counts.templates and shared_templates:
        templates_updated = sorted(shared_templates)

    summary = MetadataChangeSummary(
        picklist_values_added=tuple(picklist_added),
        picklist_values_removed=tuple(picklist_removed),
        fields_added=tuple(fields_added),
        fields_removed=tuple(fields_removed),
        record_type_changes=tuple(record_type_changes),
        templates_added=tuple(templates_added),
        templates_removed=tuple(templates_removed),
        templates_updated=tuple(templates_updated),
    )
    if not summary.has_changes and before.commit_hash != after.commit_hash:
        return MetadataChangeSummary.fallback()
    return summary
