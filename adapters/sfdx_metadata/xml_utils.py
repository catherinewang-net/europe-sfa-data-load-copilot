"""XML helpers for Salesforce metadata files."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote

logger = logging.getLogger(__name__)


def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def safe_parse_xml(path: Path) -> ET.Element | None:
    try:
        return ET.parse(path).getroot()
    except ET.ParseError as exc:
        logger.warning("Skipping unreadable metadata XML %s: %s", path, exc)
        return None


def parse_xml(path: Path) -> ET.Element:
    root = safe_parse_xml(path)
    if root is None:
        raise ET.ParseError(f"Unable to parse metadata XML: {path}")
    return root


def child_text(element: ET.Element, tag_name: str) -> str | None:
    for child in element:
        if local_name(child.tag) == tag_name:
            return (child.text or "").strip()
    return None


def find_children(element: ET.Element, tag_name: str) -> list[ET.Element]:
    return [child for child in element if local_name(child.tag) == tag_name]


def find_descendants(element: ET.Element, tag_name: str) -> list[ET.Element]:
    return [node for node in element.iter() if local_name(node.tag) == tag_name]


def decode_salesforce_value(value: str) -> str:
    return unquote(value or "")


def parse_boolean(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() == "true"
