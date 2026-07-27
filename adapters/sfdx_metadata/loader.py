"""One-time loader for Salesforce DX metadata from the EUSFA SF repository."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from adapters.sfdx_metadata.models import (
    FieldDefinition,
    PicklistValue,
    RecordTypeDefinition,
    TemplateDefinition,
)
from adapters.sfdx_metadata.standard_field_supplements import (
    infer_writeability,
    supplement_object_fields,
)
from adapters.sfdx_metadata.xml_utils import (
    child_text,
    decode_salesforce_value,
    find_children,
    find_descendants,
    local_name,
    parse_boolean,
    safe_parse_xml,
)

logger = logging.getLogger(__name__)


class SfdxMetadataLoader:
    """Loads and indexes Salesforce metadata from a local SFDX project."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve()
        self.metadata_root = self.repo_root / "force-app" / "main" / "default"
        if not self.metadata_root.is_dir():
            raise FileNotFoundError(
                f"Salesforce metadata directory not found: {self.metadata_root}"
            )

        self.global_value_sets: dict[str, tuple[PicklistValue, ...]] = {}
        self.standard_value_sets: dict[str, tuple[PicklistValue, ...]] = {}
        self.object_fields: dict[str, dict[str, FieldDefinition]] = {}
        self.templates: dict[str, TemplateDefinition] = {}
        self.templates_by_object: dict[str, list[TemplateDefinition]] = {}
        self.record_types: dict[tuple[str, str], RecordTypeDefinition] = {}
        self.skipped_files: list[str] = []

        self._load_all()

    def _load_all(self) -> None:
        self._load_global_value_sets()
        self._load_standard_value_sets()
        self._load_object_fields()
        self._load_record_types()
        self._load_template_configs()

    def _load_global_value_sets(self) -> None:
        directory = self.metadata_root / "globalValueSets"
        if not directory.is_dir():
            return

        for path in directory.glob("*.globalValueSet-meta.xml"):
            root = safe_parse_xml(path)
            if root is None:
                self.skipped_files.append(str(path))
                continue
            name = path.name.replace(".globalValueSet-meta.xml", "")
            values: list[PicklistValue] = []
            for custom_value in find_descendants(root, "customValue"):
                api_name = decode_salesforce_value(child_text(custom_value, "fullName") or "")
                label = decode_salesforce_value(child_text(custom_value, "label") or api_name)
                is_active = parse_boolean(child_text(custom_value, "isActive"), default=True)
                if api_name:
                    values.append(PicklistValue(api_name=api_name, label=label, is_active=is_active))
            self.global_value_sets[name] = tuple(values)

    def _load_standard_value_sets(self) -> None:
        directory = self.metadata_root / "standardValueSets"
        if not directory.is_dir():
            return

        for path in directory.glob("*.standardValueSet-meta.xml"):
            root = safe_parse_xml(path)
            if root is None:
                self.skipped_files.append(str(path))
                continue
            name = path.name.replace(".standardValueSet-meta.xml", "")
            values: list[PicklistValue] = []
            for standard_value in find_descendants(root, "standardValue"):
                api_name = decode_salesforce_value(child_text(standard_value, "fullName") or "")
                label = decode_salesforce_value(child_text(standard_value, "label") or api_name)
                is_active = parse_boolean(child_text(standard_value, "isActive"), default=True)
                if api_name:
                    values.append(PicklistValue(api_name=api_name, label=label, is_active=is_active))
            self.standard_value_sets[name] = tuple(values)

    def _load_object_fields(self) -> None:
        objects_dir = self.metadata_root / "objects"
        if not objects_dir.is_dir():
            return

        for object_dir in objects_dir.iterdir():
            if not object_dir.is_dir():
                continue
            fields_dir = object_dir / "fields"
            if not fields_dir.is_dir():
                continue

            object_name = object_dir.name
            field_map: dict[str, FieldDefinition] = {}

            for field_path in fields_dir.glob("*.field-meta.xml"):
                root = safe_parse_xml(field_path)
                if root is None:
                    self.skipped_files.append(str(field_path))
                    continue
                api_name = child_text(root, "fullName") or field_path.stem.replace(".field", "")
                label = child_text(root, "label") or api_name
                field_type = child_text(root, "type") or "Unknown"
                required = parse_boolean(child_text(root, "required"))
                external_id = parse_boolean(child_text(root, "externalId"))
                unique = parse_boolean(child_text(root, "unique"))
                id_lookup = parse_boolean(child_text(root, "idLookup"))
                reference_to = child_text(root, "referenceTo")
                if field_type.lower() == "hierarchy" and not reference_to and object_name:
                    reference_to = object_name

                global_value_set = None
                standard_value_set = None
                inline_values: list[str] = []

                value_set = next(
                    (node for node in root if local_name(node.tag) == "valueSet"),
                    None,
                )
                if value_set is not None:
                    global_value_set = child_text(value_set, "valueSetName")
                    value_set_definition = next(
                        (node for node in value_set if local_name(node.tag) == "valueSetDefinition"),
                        None,
                    )
                    if value_set_definition is not None:
                        for value_node in find_children(value_set_definition, "value"):
                            full_name = decode_salesforce_value(child_text(value_node, "fullName") or "")
                            is_active = parse_boolean(child_text(value_node, "isActive"), default=True)
                            if full_name and is_active:
                                inline_values.append(full_name)

                if field_type.lower() == "picklist" and not global_value_set and not inline_values:
                    inferred = self._infer_standard_value_set(object_name, api_name)
                    if inferred:
                        standard_value_set = inferred

                field_map[api_name] = FieldDefinition(
                    api_name=api_name,
                    label=label,
                    field_type=field_type,
                    required=required,
                    global_value_set=global_value_set,
                    standard_value_set=standard_value_set,
                    inline_picklist_values=tuple(inline_values),
                    reference_to=reference_to,
                    writeability=infer_writeability(api_name, field_type),
                    external_id=external_id,
                    unique=unique,
                    id_lookup=id_lookup,
                )

            if field_map:
                self.object_fields[object_name] = supplement_object_fields(object_name, field_map)

    def _infer_standard_value_set(self, object_name: str, field_name: str) -> str | None:
        candidates = [
            f"{object_name}{field_name}",
            field_name,
        ]
        for candidate in candidates:
            if candidate in self.standard_value_sets:
                return candidate
        return None

    def _load_record_types(self) -> None:
        objects_dir = self.metadata_root / "objects"
        if not objects_dir.is_dir():
            return

        for object_dir in objects_dir.iterdir():
            if not object_dir.is_dir():
                continue
            record_types_dir = object_dir / "recordTypes"
            if not record_types_dir.is_dir():
                continue

            object_name = object_dir.name
            for record_type_path in record_types_dir.glob("*.recordType-meta.xml"):
                root = safe_parse_xml(record_type_path)
                if root is None:
                    self.skipped_files.append(str(record_type_path))
                    continue
                name = child_text(root, "fullName") or record_type_path.stem.replace(".recordType", "")
                label = child_text(root, "label") or name
                picklist_values: dict[str, list[str]] = {}

                for picklist_block in find_children(root, "picklistValues"):
                    picklist_name = child_text(picklist_block, "picklist")
                    if not picklist_name:
                        continue
                    values: list[str] = []
                    for value_node in find_children(picklist_block, "values"):
                        full_name = decode_salesforce_value(child_text(value_node, "fullName") or "")
                        if full_name:
                            values.append(full_name)
                    picklist_values[picklist_name] = values

                record_type = RecordTypeDefinition(
                    object_api_name=object_name,
                    name=name,
                    label=label,
                    picklist_values={
                        field_name: tuple(field_values)
                        for field_name, field_values in picklist_values.items()
                    },
                )
                self.record_types[(object_name, name.lower())] = record_type
                self.record_types[(object_name, label.lower())] = record_type

    def _load_template_configs(self) -> None:
        directory = self.metadata_root / "customMetadata"
        if not directory.is_dir():
            return

        for path in directory.glob("Template_Config.*.md-meta.xml"):
            root = safe_parse_xml(path)
            if root is None:
                self.skipped_files.append(str(path))
                continue
            developer_name = (
                path.name.removeprefix("Template_Config.").removesuffix(".md-meta.xml")
            )
            values_by_field: dict[str, str] = {}

            for values_node in find_children(root, "values"):
                field_name = child_text(values_node, "field")
                field_value = child_text(values_node, "value")
                if field_name and field_value is not None:
                    values_by_field[field_name] = field_value

            template_name = values_by_field.get("Template_Label__c", developer_name)
            object_api_name = values_by_field.get("Object_API_Name__c", "")
            is_active = parse_boolean(values_by_field.get("Is_Active__c"), default=True)
            api_to_csv = self._parse_fields_json(values_by_field.get("Fields__c", ""))
            csv_to_api = {
                csv_label: api_name
                for api_name, csv_label in api_to_csv.items()
                if csv_label
            }
            required_csv_labels = tuple(
                label for label in api_to_csv.values() if label.startswith("*")
            )

            template = TemplateDefinition(
                name=template_name,
                developer_name=developer_name,
                object_api_name=object_api_name,
                is_active=is_active,
                api_to_csv_label=api_to_csv,
                csv_label_to_api=csv_to_api,
                required_csv_labels=required_csv_labels,
            )

            self.templates[template_name.lower()] = template
            self.templates[developer_name.lower()] = template
            self.templates_by_object.setdefault(object_api_name, []).append(template)

    @staticmethod
    def _parse_fields_json(raw_json: str) -> dict[str, str]:
        if not raw_json.strip():
            return {}
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError:
            cleaned = re.sub(r",\s*}", "}", raw_json)
            cleaned = re.sub(r",\s*]", "]", cleaned)
            parsed = json.loads(cleaned)
        if not isinstance(parsed, dict):
            return {}
        return {
            str(api_name).strip(): str(csv_label).strip()
            for api_name, csv_label in parsed.items()
            if str(api_name).strip() and str(csv_label).strip()
        }
