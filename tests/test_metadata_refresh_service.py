"""Tests for metadata_refresh_service and metadata versioning."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from services.metadata_provider_factory import clear_metadata_adapter_cache, get_metadata_adapter
from adapters.sfdx_metadata.models import FieldDefinition, TemplateDefinition
from services.constants import MAPPING_STATUS_CONFIRMED, PICKLIST_STATUS_NEEDS_USER_ACTION
from services.git_repository_service import GitRepositoryStatus, SyncStatus
from services.metadata_refresh_service import (
    get_metadata_health,
    metadata_health_summary,
    refresh_metadata,
    serialize_change_summary,
)
from services.metadata_session_service import (
    METADATA_VERSION_KEY,
    apply_new_metadata_version,
    metadata_version_changed,
)
from services.metadata_snapshot_service import compare_metadata_snapshots, capture_metadata_snapshot
from services.revalidation_service import clear_stale_metadata_validation
from services.template_service import TemplateContext, _reset_template_dropdown_cache, get_template_dropdown_options
from validators.picklist_validator import validate_picklists


FIELD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Sample__c</fullName>
    <label>Sample</label>
    <type>Picklist</type>
    <valueSet>
        <valueSetDefinition>
            <sorted>false</sorted>
            {values_xml}
        </valueSetDefinition>
    </valueSet>
</CustomField>
"""

VALUE_XML = """<value>
                <fullName>{name}</fullName>
                <default>false</default>
                <label>{name}</label>
                {inactive_tag}
            </value>"""

EXTRA_FIELD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Extra__c</fullName>
    <label>Extra</label>
    <type>Picklist</type>
    <valueSet>
        <valueSetDefinition>
            <sorted>false</sorted>
            {values_xml}
        </valueSetDefinition>
    </valueSet>
</CustomField>
"""

RECORD_TYPE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<RecordType xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Customer</fullName>
    <label>Customer</label>
    <active>true</active>
    <picklistValues>
        <picklist>Sample__c</picklist>
        <values>
            <fullName>A</fullName>
            <default>false</default>
        </values>
    </picklistValues>
</RecordType>
"""

TEMPLATE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<CustomMetadata xmlns="http://soap.sforce.com/2006/04/metadata">
    <label>Customers</label>
    <protected>false</protected>
    <values>
        <field>Template_Label__c</field>
        <value xsi:type="xsd:string" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema">Customers</value>
    </values>
    <values>
        <field>Object_API_Name__c</field>
        <value xsi:type="xsd:string" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema">Account</value>
    </values>
    <values>
        <field>Is_Active__c</field>
        <value xsi:type="xsd:boolean" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema">true</value>
    </values>
    <values>
        <field>Fields__c</field>
        <value xsi:type="xsd:string" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema">{fields_json}</value>
    </values>
</CustomMetadata>
"""


def _git_available() -> bool:
    return shutil.which("git") is not None


def _picklist_values_xml(*values: tuple[str, bool]) -> str:
    parts = []
    for name, active in values:
        inactive_tag = "" if active else "<isActive>false</isActive>"
        parts.append(VALUE_XML.format(name=name, inactive_tag=inactive_tag))
    return "\n".join(parts)


def _write_minimal_sfdx_repo(
    root: Path,
    *,
    picklist_values: tuple[tuple[str, bool], ...] = (("A", True), ("B", True)),
    include_record_type: bool = True,
) -> None:
    (root / "sfdx-project.json").write_text(
        '{"packageDirectories":[{"path":"force-app","default":true}]}',
        encoding="utf-8",
    )
    metadata = root / "force-app" / "main" / "default"
    field_dir = metadata / "objects" / "Account" / "fields"
    field_dir.mkdir(parents=True)
    (field_dir / "Sample__c.field-meta.xml").write_text(
        FIELD_XML.format(values_xml=_picklist_values_xml(*picklist_values)),
        encoding="utf-8",
    )

    if include_record_type:
        record_type_dir = metadata / "objects" / "Account" / "recordTypes"
        record_type_dir.mkdir(parents=True)
        (record_type_dir / "Customer.recordType-meta.xml").write_text(
            RECORD_TYPE_XML,
            encoding="utf-8",
        )

    template_dir = metadata / "customMetadata"
    template_dir.mkdir(parents=True)
    fields_json = json.dumps({"Sample__c": "*Sample"})
    (template_dir / "Template_Config.Customers.md-meta.xml").write_text(
        TEMPLATE_XML.format(fields_json=fields_json),
        encoding="utf-8",
    )


def _make_fake_git_repo(path: Path) -> None:
    (path / ".git").mkdir(exist_ok=True)


def _init_git_repo(path: Path) -> None:
    if not _git_available():
        _make_fake_git_repo(path)
        return
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "metadata fixture"],
        cwd=path,
        check=True,
        capture_output=True,
    )


def _mock_git_status(repo: Path) -> GitRepositoryStatus:
    return GitRepositoryStatus(
        repo_path=repo.resolve(),
        available=True,
        branch="main",
        commit_hash="abc123def456",
        commit_hash_short="abc123d",
        last_commit_date="2026-01-01T12:00:00+00:00",
        working_tree_clean=True,
        tracking_remote=True,
        ahead_count=0,
        behind_count=0,
        sync_status=SyncStatus.UP_TO_DATE,
    )


class MetadataRefreshServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self.repo = Path(tempfile.mkdtemp())
        clear_metadata_adapter_cache()
        _reset_template_dropdown_cache()
        self.git_patcher = patch(
            "services.metadata_refresh_service.get_repository_status",
            side_effect=lambda repo_path, fetch=False: _mock_git_status(repo_path),
        )
        self.git_patcher.start()

    def _reload_repo(self) -> None:
        clear_metadata_adapter_cache()
        _reset_template_dropdown_cache()

    def tearDown(self) -> None:
        self.git_patcher.stop()
        clear_metadata_adapter_cache()
        _reset_template_dropdown_cache()

    def test_refresh_clears_adapter_cache_and_reloads(self) -> None:
        _write_minimal_sfdx_repo(self.repo)
        _init_git_repo(self.repo)

        first = get_metadata_adapter(self.repo)
        result = refresh_metadata(self.repo)
        second = get_metadata_adapter(self.repo)

        self.assertTrue(result.success)
        self.assertIsNot(first, second)

    def test_refresh_returns_metadata_counts_and_previous_counts(self) -> None:
        _write_minimal_sfdx_repo(self.repo)
        _init_git_repo(self.repo)

        get_metadata_adapter(self.repo)
        result = refresh_metadata(self.repo)
        self.assertTrue(result.success)
        self.assertIsNotNone(result.previous_counts)
        self.assertGreaterEqual(result.counts.objects, 1)
        self.assertGreaterEqual(result.counts.fields, 1)
        self.assertGreaterEqual(result.counts.picklists, 1)
        self.assertGreaterEqual(result.counts.templates, 1)

    def test_added_picklist_value_appears_after_refresh(self) -> None:
        _write_minimal_sfdx_repo(self.repo, picklist_values=(("A", True),))
        _init_git_repo(self.repo)
        get_metadata_adapter(self.repo)

        field_path = (
            self.repo / "force-app" / "main" / "default" / "objects" / "Account" / "fields" / "Sample__c.field-meta.xml"
        )
        field_path.write_text(
            FIELD_XML.format(values_xml=_picklist_values_xml(("A", True), ("C", True))),
            encoding="utf-8",
        )

        refresh_metadata(self.repo)
        adapter = get_metadata_adapter(self.repo)
        self.assertIn("C", adapter.get_picklist_values("Account", "Sample__c"))

    def test_removed_picklist_value_fails_after_refresh(self) -> None:
        _write_minimal_sfdx_repo(self.repo, picklist_values=(("A", True), ("B", True)))
        _init_git_repo(self.repo)
        get_metadata_adapter(self.repo)

        field_path = (
            self.repo / "force-app" / "main" / "default" / "objects" / "Account" / "fields" / "Sample__c.field-meta.xml"
        )
        field_path.write_text(
            FIELD_XML.format(values_xml=_picklist_values_xml(("A", True),)),
            encoding="utf-8",
        )
        self._reload_repo()
        refresh_metadata(self.repo)

        adapter = get_metadata_adapter(self.repo)
        context = TemplateContext(
            template_name="Customers",
            metadata_available=True,
            template_definition=adapter.get_template("Customers"),
            salesforce_object="Account",
            fallback_config={"salesforce_object": "Account", "required_type": "Customer"},
            metadata_message=None,
            record_type_name="Customer",
            required_type_value="Customer",
            account_type_valid=True,
            account_type_error=None,
            is_account_template=True,
        )
        rows = [{
            "dit_column": "*Sample",
            "confirmed_api_field": "Sample__c",
            "status": MAPPING_STATUS_CONFIRMED,
        }]
        df = pd.DataFrame({"*Sample": ["B"]})
        with patch("services.template_service.get_adapter", return_value=adapter), patch(
            "validators.picklist_validator.get_adapter",
            return_value=adapter,
        ):
            result = validate_picklists(df, rows, context)
        self.assertTrue(result["has_blocking_issues"])
        self.assertEqual(result["issues"][0]["status"], PICKLIST_STATUS_NEEDS_USER_ACTION)

    def test_inactive_picklist_value_is_excluded_after_refresh(self) -> None:
        _write_minimal_sfdx_repo(self.repo, picklist_values=(("A", True), ("OLD", False)))
        _init_git_repo(self.repo)
        self._reload_repo()
        refresh_metadata(self.repo)
        adapter = get_metadata_adapter(self.repo)
        values = adapter.get_picklist_values("Account", "Sample__c")
        self.assertIn("A", values)
        self.assertNotIn("OLD", values)

    def test_record_type_restrictions_reload_after_refresh(self) -> None:
        _write_minimal_sfdx_repo(self.repo)
        _init_git_repo(self.repo)
        get_metadata_adapter(self.repo)

        record_type_path = (
            self.repo / "force-app" / "main" / "default" / "objects" / "Account" / "recordTypes" / "Customer.recordType-meta.xml"
        )
        record_type_path.write_text(
            RECORD_TYPE_XML.replace("<fullName>A</fullName>", "<fullName>B</fullName>"),
            encoding="utf-8",
        )
        refresh_metadata(self.repo)
        adapter = get_metadata_adapter(self.repo)
        allowed = adapter.get_allowed_values_for_record_type("Account", "Customer", "Sample__c")
        self.assertEqual(allowed, ["B"])

    def test_metadata_version_changed_detects_commit_differences(self) -> None:
        self.assertTrue(metadata_version_changed("abc", "def"))
        self.assertFalse(metadata_version_changed("abc", "abc"))
        self.assertFalse(metadata_version_changed(None, "abc"))

    def test_revalidation_clears_stale_picklist_results(self) -> None:
        session_state = {
            "validation_bundle": {"picklist_validation": {"issues": [{"status": "INVALID"}]}},
            "mapping_rows": [{"confirmed_api_field": "Sample__c"}],
            "header_review_complete": True,
        }
        clear_stale_metadata_validation(session_state)
        self.assertNotIn("validation_bundle", session_state)
        self.assertNotIn("mapping_rows", session_state)
        self.assertNotIn("header_review_complete", session_state)

    def test_apply_new_metadata_version_updates_session_lock(self) -> None:
        session_state = {
            METADATA_VERSION_KEY: "old-hash",
            "validation_bundle": {"picklist_validation": {}},
            "metadata_refresh_pending": True,
        }
        apply_new_metadata_version(session_state, "new-hash")
        self.assertEqual(session_state[METADATA_VERSION_KEY], "new-hash")
        self.assertNotIn("validation_bundle", session_state)
        self.assertNotIn("metadata_refresh_pending", session_state)

    def test_refresh_reports_skipped_files(self) -> None:
        _write_minimal_sfdx_repo(self.repo)
        _init_git_repo(self.repo)
        bad_path = (
            self.repo / "force-app" / "main" / "default" / "customMetadata" / "Template_Config.Bad.md-meta.xml"
        )
        bad_path.write_text("not xml", encoding="utf-8")

        result = refresh_metadata(self.repo)
        self.assertTrue(result.success)
        self.assertTrue(any("Bad.md-meta.xml" in path for path in result.skipped_files))
        self.assertEqual(result.adapter_status, "Loaded with warnings")

    def test_refresh_resets_template_dropdown_cache(self) -> None:
        _write_minimal_sfdx_repo(self.repo)
        _init_git_repo(self.repo)

        with patch(
            "services.template_service.get_metadata_adapter",
            return_value=MagicMock(list_templates=lambda: []),
        ):
            _reset_template_dropdown_cache()
            first = get_template_dropdown_options()

        refresh_metadata(self.repo)
        options = get_template_dropdown_options()
        self.assertNotEqual(first, options)
        self.assertIn("Customers", options)

    def test_refresh_does_not_mutate_salesforce_repository(self) -> None:
        _write_minimal_sfdx_repo(self.repo)
        _init_git_repo(self.repo)
        field_path = (
            self.repo / "force-app" / "main" / "default" / "objects" / "Account" / "fields" / "Sample__c.field-meta.xml"
        )
        before = field_path.read_text(encoding="utf-8")
        refresh_metadata(self.repo)
        after = field_path.read_text(encoding="utf-8")
        self.assertEqual(before, after)

    def test_change_summary_detects_picklist_and_field_changes(self) -> None:
        _write_minimal_sfdx_repo(self.repo, picklist_values=(("A", True),))
        _init_git_repo(self.repo)
        before_adapter = get_metadata_adapter(self.repo)
        before = capture_metadata_snapshot(before_adapter.adapter, "commit-a")

        field_path = (
            self.repo / "force-app" / "main" / "default" / "objects" / "Account" / "fields" / "Sample__c.field-meta.xml"
        )
        field_path.write_text(
            FIELD_XML.format(values_xml=_picklist_values_xml(("A", True), ("NEW", True))),
            encoding="utf-8",
        )
        extra_field = (
            self.repo / "force-app" / "main" / "default" / "objects" / "Account" / "fields" / "Extra__c.field-meta.xml"
        )
        extra_field.write_text(
            EXTRA_FIELD_XML.format(values_xml=_picklist_values_xml(("X", True))),
            encoding="utf-8",
        )

        self._reload_repo()
        after_adapter = get_metadata_adapter(self.repo)
        after = capture_metadata_snapshot(after_adapter.adapter, "commit-b")
        summary = compare_metadata_snapshots(before, after)
        assert summary is not None
        self.assertTrue(summary.has_changes)
        self.assertTrue(any("NEW" in item for item in summary.picklist_values_added))
        self.assertIn("Account.Extra__c", summary.fields_added)

    def test_health_check_without_refresh(self) -> None:
        _write_minimal_sfdx_repo(self.repo)
        _init_git_repo(self.repo)
        refresh_metadata(self.repo)

        health = get_metadata_health(self.repo)
        self.assertTrue(health.adapter_available)
        self.assertEqual(health.adapter_status, "Healthy")
        self.assertGreaterEqual(health.counts.templates, 1)

    def test_refresh_missing_metadata_directory_fails(self) -> None:
        _init_git_repo(self.repo)
        result = refresh_metadata(self.repo)
        self.assertFalse(result.success)
        self.assertEqual(result.adapter_status, "Error")
        self.assertIsNotNone(result.error)

    def test_metadata_health_summary_shape(self) -> None:
        _write_minimal_sfdx_repo(self.repo)
        _init_git_repo(self.repo)
        health = get_metadata_health(self.repo)
        summary = metadata_health_summary(health)
        self.assertIn("adapter_status", summary)
        self.assertIn("counts", summary)
        self.assertIn("objects", summary["counts"])
        self.assertIn("git_status", summary)
        self.assertNotIn("repo_path", summary)

    def test_refresh_with_mock_adapter_counts(self) -> None:
        _write_minimal_sfdx_repo(self.repo)
        mock_sfdx = MagicMock()
        mock_loader = MagicMock()
        mock_loader.object_fields = {
            "Account": {
                "Type": FieldDefinition(
                    "Type",
                    "Type",
                    "Picklist",
                    False,
                    standard_value_set="AccountType",
                )
            }
        }
        mock_loader.record_types = {}
        mock_sfdx._loader = mock_loader
        mock_sfdx.list_templates.return_value = [
            TemplateDefinition(
                name="Customers",
                developer_name="Customers",
                object_api_name="Account",
                is_active=True,
                api_to_csv_label={},
                csv_label_to_api={},
                required_csv_labels=(),
            )
        ]
        mock_sfdx.skipped_files = []
        mock_sfdx.get_picklist_values.return_value = ["Customer"]
        mock_copilot = MagicMock()
        mock_copilot.adapter = mock_sfdx
        mock_copilot.skipped_files = []

        with patch(
            "services.metadata_refresh_service.get_metadata_adapter",
            return_value=mock_copilot,
        ):
            result = refresh_metadata(self.repo)
        self.assertTrue(result.success)
        self.assertEqual(result.counts.objects, 1)
        self.assertEqual(result.counts.fields, 1)
        self.assertEqual(result.counts.picklists, 1)
        self.assertEqual(result.counts.templates, 1)

    def test_serialize_change_summary_fallback_message(self) -> None:
        from services.metadata_snapshot_service import MetadataChangeSummary

        payload = serialize_change_summary(MetadataChangeSummary.fallback())
        assert payload is not None
        self.assertIn("Metadata version changed", payload["display_lines"][0])


if __name__ == "__main__":
    unittest.main()
