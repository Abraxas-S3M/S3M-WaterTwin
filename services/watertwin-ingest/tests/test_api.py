"""End-to-end API tests for the ingest flow (upload -> classify -> parse -> proposal)."""

from __future__ import annotations

import os
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import store as store_module
from app.main import app
from app.parsers.base import ParseResult, ParseStatus

from .conftest import DEMO_INP

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
_NETWORK_TYPES = {"junction", "reservoir", "tank", "pipe", "pump", "valve"}


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload
        self.status_code = 200

    def json(self) -> Any:
        return self._payload


class _FakeSession:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def get(self, _path: str) -> _FakeResponse:
        return _FakeResponse(self._payload)


class _FakeCanonicalClient:
    """Stands in for the watertwin-api canonical config fetch."""

    def __init__(self, records: list) -> None:
        self._records = records

    def fetch_records(self) -> list:
        return self._records


@pytest.fixture
def client(tmp_path):
    # A fresh, isolated upload store per test (its own scratch dir + executor) so
    # tests never share the background thread pool or on-disk state.
    from app import config
    from app.store import UploadStore

    store = UploadStore(
        scratch_dir=str(tmp_path / "scratch"),
        timeout_s=config.PARSE_TIMEOUT_S,
        memory_mb=config.MEMORY_CAP_MB,
        max_fsize_bytes=config.MAX_SCRATCH_BYTES,
    )
    app.state.upload_store = store
    app.state.canonical_client = None
    with TestClient(app) as test_client:
        yield test_client
    app.state.canonical_client = None


def _upload(client: TestClient, path: str, name: str = "network.inp"):
    with open(path, "rb") as handle:
        return client.post("/api/v1/ingest/uploads", files={"file": (name, handle.read())})


def _wait_terminal(client: TestClient, upload_id: str, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    terminal = {"parsed", "partial", "parse_failed"}
    while time.monotonic() < deadline:
        resp = client.get(f"/api/v1/ingest/uploads/{upload_id}/result")
        body = resp.json()
        if body["status"] in terminal:
            return body
        time.sleep(0.05)
    raise AssertionError("parse did not reach a terminal state in time")


def test_health_lists_supported_formats(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert "epanet" in body["supported_formats"]
    assert body["control_boundary"]["control_write_enabled"] is False


def test_full_flow_upload_classify_parse_result_proposal(client):
    parsed = ParseResult.model_validate(_seed_parse_result())
    # Seed the canonical config from the same demo network -> a clean round-trip.
    from app.reconciler import CanonicalConfigClient
    session = _FakeSession(_features_from_result(parsed))
    app.state.canonical_client = CanonicalConfigClient(session=session)

    created = _upload(client, DEMO_INP, "ro-handoff.inp").json()
    upload_id = created["upload_id"]
    assert created["status"] == "received"
    assert created["sniffed_format"] == "epanet"

    classified = client.post(
        f"/api/v1/ingest/uploads/{upload_id}/classify",
        json={"file_format": "epanet"},
    ).json()
    assert classified["classified"] is True
    assert classified["confirmed_format"] == "epanet"

    assert client.post(f"/api/v1/ingest/uploads/{upload_id}/parse").status_code == 202
    result_body = _wait_terminal(client, upload_id)
    assert result_body["status"] == "parsed"
    counts = _counts(result_body["result"])
    assert counts["junction"] == 6 and counts["pipe"] == 5

    proposal = client.get(f"/api/v1/ingest/uploads/{upload_id}/proposal").json()["proposal"]
    assert proposal["entity_counts"] == {
        "junction": 6, "reservoir": 1, "tank": 1, "pipe": 5, "pump": 2, "valve": 1,
    }
    assert proposal["provenance"] == "customer_supplied"
    assert proposal["control_boundary"]["operator_approval_required"] is True


def test_parse_requires_human_confirmed_classification(client):
    upload_id = _upload(client, DEMO_INP).json()["upload_id"]
    # Parsing before a human confirms the classification is refused.
    resp = client.post(f"/api/v1/ingest/uploads/{upload_id}/parse")
    assert resp.status_code == 409
    assert "classification must be confirmed" in resp.json()["detail"]


def test_classify_rejects_unsupported_format(client):
    upload_id = _upload(client, DEMO_INP).json()["upload_id"]
    resp = client.post(
        f"/api/v1/ingest/uploads/{upload_id}/classify",
        json={"file_format": "autocad-dwg"},
    )
    assert resp.status_code == 422


def test_xxe_upload_is_rejected(client):
    resp = _upload(client, os.path.join(FIXTURES, "xxe.inp"), "evil.inp")
    assert resp.status_code == 400
    assert "external-entity" in resp.json()["detail"]


def test_timed_out_worker_marks_parse_failed_and_api_stays_responsive(client, monkeypatch):
    def _fake_timed_out(*_args, **_kwargs):
        return ParseResult(
            status=ParseStatus.parse_failed,
            parser="sandbox-worker",
            error="parse exceeded the 0.5s wall-clock timeout",
        )

    monkeypatch.setattr(store_module, "run_parse_job", _fake_timed_out)

    upload_id = _upload(client, DEMO_INP).json()["upload_id"]
    client.post(f"/api/v1/ingest/uploads/{upload_id}/classify", json={"file_format": "epanet"})
    client.post(f"/api/v1/ingest/uploads/{upload_id}/parse")
    body = _wait_terminal(client, upload_id)
    assert body["status"] == "parse_failed"

    # The API process is unaffected by the worker failure.
    assert client.get("/health").json()["status"] == "ok"
    # A failed parse cannot produce a proposal.
    proposal_resp = client.get(f"/api/v1/ingest/uploads/{upload_id}/proposal")
    assert proposal_resp.status_code == 409


def test_unknown_upload_returns_404(client):
    assert client.get("/api/v1/ingest/uploads/does-not-exist/result").status_code == 404


# --- helpers ---------------------------------------------------------------


def _seed_parse_result() -> dict:
    from app.parsers import get_parser
    from app.parsers.base import ParseScope

    return get_parser("epanet").parse(DEMO_INP, ParseScope(file_format="epanet")).model_dump(
        mode="json"
    )


def _features_from_result(result: ParseResult) -> dict:
    features = []
    for entity in result.entities:
        if entity.entity_type not in _NETWORK_TYPES:
            continue
        props = {
            "element_id": entity.entity_id,
            "element_type": entity.entity_type,
            **entity.fields,
        }
        features.append({"type": "Feature", "id": entity.entity_id, "properties": props})
    return {"type": "FeatureCollection", "features": features}


def _counts(result_payload: dict) -> dict:
    counts: dict[str, int] = {}
    for entity in result_payload["entities"]:
        counts[entity["entity_type"]] = counts.get(entity["entity_type"], 0) + 1
    return counts
