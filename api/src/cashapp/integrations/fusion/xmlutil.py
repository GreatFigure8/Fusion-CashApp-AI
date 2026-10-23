"""Hardened XML helpers shared by the SOAP and BI Publisher modules (defusedxml only)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterator

from defusedxml import ElementTree as DefusedET
from defusedxml.common import DefusedXmlException


class XmlParseError(ValueError):
    """The document is malformed or uses a forbidden construct (DTD, entity, external)."""


def safe_fromstring(data: bytes) -> ET.Element:
    """Parse untrusted XML. DTDs, entity declarations and external references are refused."""
    try:
        return DefusedET.fromstring(data, forbid_dtd=True)
    except (ET.ParseError, DefusedXmlException, ValueError) as exc:
        raise XmlParseError("unparseable XML") from exc


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def iter_local(root: ET.Element, name: str) -> Iterator[ET.Element]:
    for element in root.iter():
        if local_name(element.tag) == name:
            yield element


def first_local(root: ET.Element, name: str) -> ET.Element | None:
    return next(iter_local(root, name), None)


def child_text(element: ET.Element, name: str) -> str | None:
    for child in element:
        if local_name(child.tag) == name:
            text = (child.text or "").strip()
            return text or None
    return None


def full_text(element: ET.Element) -> str:
    return " ".join("".join(element.itertext()).split())
