"""Outbound-only posture: the gateway never binds an inbound listener.

Two complementary checks:

* a **static** scan of the gateway app package for any inbound-server construct
  (web framework, socket bind/listen, stdlib server); and
* a **runtime** assertion that a full collect + forward cycle never calls
  ``socket.bind`` or ``socket.listen`` (it only dials outbound).
"""

from __future__ import annotations

import os
import re
import socket
import types


from app.buffer import EncryptedBuffer
from app.collector import Collector
from app.forwarder import ForwardResult

APP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")

# Constructs that would introduce an inbound listener / server.
_FORBIDDEN_INBOUND = [
    r"\bimport\s+uvicorn\b",
    r"\bfrom\s+uvicorn\b",
    r"\bimport\s+fastapi\b",
    r"\bfrom\s+fastapi\b",
    r"\bimport\s+flask\b",
    r"\bfrom\s+flask\b",
    r"\bsocketserver\b",
    r"\bhttp\.server\b",
    r"\b\.bind\(",
    r"\b\.listen\(",
    r"\bcreate_server\b",
    r"\bstart_server\b",
    r"\brun\(\s*app",
]


def _app_files() -> list[str]:
    return [
        os.path.join(APP_DIR, f)
        for f in os.listdir(APP_DIR)
        if f.endswith(".py")
    ]


def test_gateway_app_has_no_inbound_server_construct():
    files = _app_files()
    assert files, "expected python files under app/"
    offenders: list[str] = []
    for path in files:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        for pattern in _FORBIDDEN_INBOUND:
            if re.search(pattern, text):
                offenders.append(f"{os.path.basename(path)} matches {pattern!r}")
    assert not offenders, "Inbound-server construct detected in edge-gateway app/: " + "; ".join(
        offenders
    )


class _FakeForwarder:
    def __init__(self):
        self.received: list[dict] = []

    def send(self, records, *, source=None, fallback=False, source_health=None):
        self.received.extend(records)
        return ForwardResult(ok=True, accepted=len(records))


def _config():
    return types.SimpleNamespace(
        OT_SOURCE="synthetic",
        GATEWAY_ID="edge-gw-test",
        FORWARD_BATCH_SIZE=1000,
        POLL_INTERVAL_S=0.0,
        STALENESS_LIMIT_S=1e9,
        FROZEN_LIMIT=10_000,
        DEADBAND=0.0,
    )


def test_collect_cycle_never_binds_a_socket(tmp_path, monkeypatch):
    bind_calls: list = []
    listen_calls: list = []

    orig_bind = socket.socket.bind
    orig_listen = socket.socket.listen

    def spy_bind(self, *args, **kwargs):  # pragma: no cover - should never fire
        bind_calls.append(args)
        return orig_bind(self, *args, **kwargs)

    def spy_listen(self, *args, **kwargs):  # pragma: no cover - should never fire
        listen_calls.append(args)
        return orig_listen(self, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "bind", spy_bind)
    monkeypatch.setattr(socket.socket, "listen", spy_listen)

    buffer = EncryptedBuffer(str(tmp_path / "buffer.db"), key="k")
    forwarder = _FakeForwarder()
    collector = Collector(_config(), buffer, forwarder)

    result = collector.run_once()

    assert result.ok is True
    assert forwarder.received, "a collect+forward cycle should push readings outbound"
    assert bind_calls == [], "gateway must not bind any inbound socket"
    assert listen_calls == [], "gateway must not listen on any inbound socket"
    buffer.close()
