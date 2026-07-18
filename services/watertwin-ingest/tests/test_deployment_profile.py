"""One-way / data-diode profile: ingest routes 503, /health still 200."""

from __future__ import annotations

from helpers import upload


def _engineer(client):
    return client.token("erin-engineer", ["engineer"], "TEN-A")


def test_one_way_diode_returns_503_on_every_ingest_route(client, monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "one_way_diode")

    # Every ingest route is disabled with a clear 503 reason.
    for resp in (
        client.get("/api/v1/ingest/uploads", headers=_engineer(client)),
        client.get("/api/v1/ingest/uploads/does-not-matter", headers=_engineer(client)),
        client.get("/api/v1/ingest/uploads/x/content", headers=_engineer(client)),
        client.delete("/api/v1/ingest/uploads/x", headers=_engineer(client)),
        upload(
            client,
            filename="x.csv",
            content=b"a,b\n1,2\n",
            content_type="text/csv",
            headers=_engineer(client),
        ),
    ):
        assert resp.status_code == 503, resp.text
        assert "one_way_diode" in resp.json()["detail"]


def test_health_still_200_under_one_way_diode(client, monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "one_way_diode")
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert body["deployment_profile"] == "one_way_diode"
    assert body["inbound_file_transfer_enabled"] is False
    # Readiness stays up too (the service runs; it just refuses inbound files).
    assert client.get("/ready").status_code == 200


def test_unknown_profile_fails_closed_to_disabled(client, monkeypatch):
    # A typo must fail closed (inbound disabled), never accidentally open.
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "stanadrd")
    assert client.get("/api/v1/ingest/uploads", headers=_engineer(client)).status_code == 503


def test_standard_profile_serves_ingest(client, monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "standard")
    assert client.get("/api/v1/ingest/uploads", headers=_engineer(client)).status_code == 200
