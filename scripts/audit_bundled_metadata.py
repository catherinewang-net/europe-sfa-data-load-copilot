#!/usr/bin/env python3
"""Security audit for bundled EUSFA metadata snapshots before container build."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BUNDLE_DIR = PROJECT_ROOT / "bundled_metadata"

FORBIDDEN_FILENAMES = {
    ".env",
    ".env.local",
    "credentials.json",
    "secrets.toml",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}

FORBIDDEN_DIR_NAMES = {".git", ".svn", ".hg", "__pycache__", "venv", ".venv"}

FORBIDDEN_BUNDLE_DIRS = {"classes", "lwc", "staticresources", "triggers", "aura", "components"}

CONTENT_SCAN_EXTENSIONS = {".xml", ".json", ".yaml", ".yml", ".txt", ".md", ".csv"}

CONTENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Git credential URL", re.compile(r"https?://[^/\s]+@[^/\s]+")),
]


def audit_bundled_metadata(bundle_dir: Path) -> list[str]:
    findings: list[str] = []

    if not bundle_dir.exists():
        return [f"Bundle directory does not exist: {bundle_dir}"]

    manifest = bundle_dir / "SNAPSHOT_MANIFEST.json"
    if not manifest.is_file():
        findings.append(f"Missing SNAPSHOT_MANIFEST.json in {bundle_dir}")

    sfdx_project = bundle_dir / "sfdx-project.json"
    metadata_default = bundle_dir / "force-app" / "main" / "default"
    if not sfdx_project.is_file():
        findings.append(f"Missing sfdx-project.json in {bundle_dir}")
    if not metadata_default.is_dir():
        findings.append(f"Missing force-app/main/default in {bundle_dir}")

    for path in bundle_dir.rglob("*"):
        rel = path.relative_to(bundle_dir)
        parts = rel.parts

        if any(part in FORBIDDEN_DIR_NAMES for part in parts):
            findings.append(f"Forbidden directory in bundle: {rel.as_posix()}")
            continue

        if path.is_file() and path.name in FORBIDDEN_FILENAMES:
            findings.append(f"Forbidden file in bundle: {rel.as_posix()}")
            continue

        if path.is_file() and path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
            findings.append(f"Key/certificate file in bundle: {rel.as_posix()}")
            continue

        if any(part in FORBIDDEN_BUNDLE_DIRS for part in parts):
            findings.append(f"Non-metadata directory in bundle: {rel.as_posix()}")
            continue

        if path.is_file() and path.suffix.lower() not in CONTENT_SCAN_EXTENSIONS:
            continue

        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for label, pattern in CONTENT_PATTERNS:
            if pattern.search(text):
                findings.append(f"{label} pattern in {rel.as_posix()}")
                break

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit bundled metadata for secrets and forbidden files.")
    parser.add_argument(
        "--bundle-dir",
        type=Path,
        default=DEFAULT_BUNDLE_DIR,
        help="Path to bundled_metadata directory",
    )
    args = parser.parse_args()

    findings = audit_bundled_metadata(args.bundle_dir.resolve())
    if findings:
        print("Bundled metadata audit FAILED:")
        for item in findings:
            print(f"  - {item}")
        return 1

    print(f"Bundled metadata audit passed: {args.bundle_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
