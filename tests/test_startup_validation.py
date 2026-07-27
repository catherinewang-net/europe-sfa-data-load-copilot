"""Tests for startup validation (hosted / bundled mode)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.startup_validation import (
    get_deployment_startup_notices,
    validate_startup_metadata,
)


def _write_minimal_bundled(root: Path) -> None:
    (root / "sfdx-project.json").write_text('{"packageDirectories":[]}', encoding="utf-8")
    metadata = root / "force-app" / "main" / "default"
    (metadata / "objects").mkdir(parents=True)
    (root / "SNAPSHOT_MANIFEST.json").write_text(json.dumps({"commit_hash": "abc"}), encoding="utf-8")


class StartupValidationTests(unittest.TestCase):
    def test_bundled_mode_validates_manifest_and_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_minimal_bundled(root)
            env = {
                "METADATA_MODE": "bundled",
                "BUNDLED_METADATA_PATH": str(root),
                "DEPLOYMENT_MODE": "demo",
            }
            with patch.dict(os.environ, env, clear=False):
                ok, error = validate_startup_metadata()
            self.assertTrue(ok, error)
            self.assertIsNone(error)

    def test_bundled_mode_fails_without_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sfdx-project.json").write_text("{}", encoding="utf-8")
            (root / "force-app" / "main" / "default").mkdir(parents=True)
            env = {
                "METADATA_MODE": "bundled",
                "BUNDLED_METADATA_PATH": str(root),
            }
            with patch.dict(os.environ, env, clear=False):
                ok, error = validate_startup_metadata()
            self.assertFalse(ok)
            self.assertIn("SNAPSHOT_MANIFEST", error or "")

    @patch.dict(os.environ, {"METADATA_MODE": "bundled", "SSO_DISABLED": "true"}, clear=False)
    def test_deployment_notices_snapshot_mode_without_oauth(self) -> None:
        notices = get_deployment_startup_notices()
        joined = " ".join(notices)
        self.assertIn("bundled snapshot", joined.lower())
        self.assertIn("not configured", joined.lower())

    @patch.dict(
        os.environ,
        {
            "METADATA_MODE": "bundled",
            "SALESFORCE_CLIENT_ID": "client",
            "SALESFORCE_REDIRECT_URI": "https://app.streamlit.app/",
        },
        clear=False,
    )
    def test_deployment_notices_oauth_configured(self) -> None:
        notices = get_deployment_startup_notices()
        self.assertTrue(any("Live Salesforce connection is available" in n for n in notices))


if __name__ == "__main__":
    unittest.main()
