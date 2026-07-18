"""XXE / XSLT / entity-expansion-safe XML parsing.

All untrusted XML is parsed with :mod:`defusedxml`, which forbids DTD
processing, external entity resolution and entity-expansion ("billion laughs")
by construction. On top of that we pre-scan the raw bytes and reject any
document that declares a DOCTYPE/DTD, references an external entity, or carries
an ``xml-stylesheet`` processing instruction (XSLT injection vector). The result
is that untrusted XML can never read local files, reach the network, or expand
into a memory bomb.
"""

from __future__ import annotations

import re
from xml.etree.ElementTree import Element

import defusedxml.ElementTree as ET
from defusedxml.common import (
    DTDForbidden,
    EntitiesForbidden,
    ExternalReferenceForbidden,
)

__all__ = [
    "UnsafeXml",
    "DTDForbidden",
    "EntitiesForbidden",
    "ExternalReferenceForbidden",
    "parse_xml",
]

_DOCTYPE_RE = re.compile(rb"<!DOCTYPE", re.IGNORECASE)
_ENTITY_RE = re.compile(rb"<!ENTITY", re.IGNORECASE)
_STYLESHEET_PI_RE = re.compile(rb"<\?xml-stylesheet", re.IGNORECASE)


class UnsafeXml(Exception):
    """Raised when untrusted XML declares a disallowed construct."""


def _prescan(data: bytes) -> None:
    """Reject dangerous XML constructs before handing bytes to the parser."""
    if _DOCTYPE_RE.search(data):
        raise UnsafeXml("DOCTYPE/DTD is not permitted in uploaded XML")
    if _ENTITY_RE.search(data):
        raise UnsafeXml("entity declarations are not permitted in uploaded XML")
    if _STYLESHEET_PI_RE.search(data):
        raise UnsafeXml(
            "xml-stylesheet (XSLT) processing instructions are not permitted"
        )


def parse_xml(data: bytes) -> Element:
    """Parse untrusted XML safely, returning the root element.

    Raises :class:`UnsafeXml` (or a defusedxml ``*Forbidden`` subclass) when the
    document attempts XXE, external references, entity expansion or XSLT. The
    pre-scan is defence-in-depth: even without it, defusedxml refuses DTDs and
    entities, but the pre-scan also blocks the XSLT stylesheet PI which is not a
    DTD construct.
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    _prescan(data)
    return ET.fromstring(
        data,
        forbid_dtd=True,
        forbid_entities=True,
        forbid_external=True,
    )
