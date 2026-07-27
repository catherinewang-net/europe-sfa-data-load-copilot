"""Tests for metadata provider factory and deployment modes."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.metadata_provider_factory import (
    clear_metadata_adapter_cache,
    create_metadata_provider,
    get_metadata_adapter,
    get_metadata_repo_path,
)


FIELD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Sample__c</fullName>
    <label>Sample</label>
    <type>Text</type>
    <length>80</length>
</CustomField>
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


def _write_minimal_sfdx_repo(root: Path) -> None:
    (root / "sfdx-project.json").write_text(
        '{"packageDirectories":[{"path":"force-app","default":true}]}',
        encoding="utf-8",
    )
    metadata = root / "force-app" / "main" / "default"
    field_dir = metadata / "objects" / "Account" / "fields"
    field_dir.mkdir(parents=True)
    (field_dir / "Sample__c.field-meta.xml").write_text(FIELD_XML, encoding="utf-8")
    template_dir = metadata / "customMetadata"
    template_dir.mkdir(parents=True)
    (template_dir / "Template_Config.Customers.md-meta.xml").write_text(
        TEMPLATE_XML.format(fields_json='{"Sample__c": "*Sample"}'),
        encoding="utf-8",
    )


class MetadataProviderFactoryTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_metadata_adapter_cache()
        self._temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self._temp_dir.name)
        _write_minimal_sfdx_repo(self.repo)

    def tearDown(self) -> None:
        clear_metadata_adapter_cache()
        self._temp_dir.cleanup()

    def test_local_mode_uses_explicit_repo_path(self) -> None:
        with patch.dict(os.environ, {"METADATA_MODE": "local", "EUSFA_SFDX_REPO_PATH": str(self.repo)}, clear=False):
            provider = create_metadata_provider()
            self.assertEqual(provider.repo_root.resolve(), self.repo.resolve())
            fields = provider.get_object_fields("Account")
            self.assertIn("Sample__c", fields)

    def test_bundled_mode_uses_bundled_metadata_path(self) -> None:
        bundled_root = self.repo / "bundled"
        bundled_root.mkdir()
        _write_minimal_sfdx_repo(bundled_root)
        (bundled_root / "SNAPSHOT_MANIFEST.json").write_text(
            json.dumps({"commit_hash": "abc123"}),
            encoding="utf-8",
        )
        env = {
            "METADATA_MODE": "bundled",
            "BUNDLED_METADATA_PATH": str(bundled_root),
            "DEPLOYMENT_MODE": "demo",
        }
        with patch.dict(os.environ, env, clear=False):
            path = get_metadata_repo_path()
            self.assertEqual(path, bundled_root.resolve())
            provider = create_metadata_provider()
            self.assertEqual(len(provider.list_templates()), 1)

    def test_get_metadata_adapter_delegates_to_factory_path(self) -> None:
        with patch.dict(os.environ, {"METADATA_MODE": "local", "EUSFA_SFDX_REPO_PATH": str(self.repo)}, clear=False):
            with patch("services.metadata_provider_factory.get_metadata_repo_path", return_value=self.repo.resolve()):
                adapter = get_metadata_adapter()
                self.assertEqual(adapter.repo_root.resolve(), self.repo.resolve())

    def test_unsupported_metadata_mode_raises(self) -> None:
        with patch.dict(os.environ, {"METADATA_MODE": "live"}, clear=False):
            with self.assertRaises(ValueError):
                create_metadata_provider(self.repo)


class BundledMetadataAuditTests(unittest.TestCase):
    def test_audit_passes_clean_snapshot(self) -> None:
        from scripts.audit_bundled_metadata import audit_bundled_metadata

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_minimal_sfdx_repo(root)
            (root / "SNAPSHOT_MANIFEST.json").write_text("{}", encoding="utf-8")
            findings = audit_bundled_metadata(root)
            self.assertEqual(findings, [])

    def test_audit_fails_on_env_file(self) -> None:
        from scripts.audit_bundled_metadata import audit_bundled_metadata

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_minimal_sfdx_repo(root)
            (root / "SNAPSHOT_MANIFEST.json").write_text("{}", encoding="utf-8")
            (root / ".env").write_text("SF_ACCESS_TOKEN=secret", encoding="utf-8")
            findings = audit_bundled_metadata(root)
            self.assertTrue(any(".env" in item for item in findings))


if __name__ == "__main__":
    unittest.main()
