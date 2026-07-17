"""Tests for the Cyber-Physical Security analytics + signed SIEM export.

Covers the pure analytics (sensor-confidence, cyber-physical consistency,
source-health), the append-only signed SIEM export (integrity + ordering +
tamper detection), the endpoints under the dev-bypass, and the ``security`` RBAC
gate under enforced Keycloak-style auth. Everything here stays read-only; no test
exercises (or could exercise) a control-write path.
"""

from __future__ import annotations

import datetime as dt

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app import config
from app import security as sec
from app import siem_export
from app import sources
from app.store import Store

TEST_ISSUER = "https://keycloak.test/realms/watertwin"


# --------------------------------------------------------------------------- #
# Cyber-physical consistency + sensor confidence (pure analytics)
# --------------------------------------------------------------------------- #


def test_cyber_physical_consistency_scores_and_orders():
    rows = sec.cyber_physical_consistency()
    assert rows, "expected consistency rows for the synthetic assets"

    # Ordered least-consistent first.
    scores = [r["consistency_score"] for r in rows]
    assert scores == sorted(scores)
    for r in rows:
        assert 0.0 <= r["consistency_score"] <= 1.0
        assert r["status"] in {"consistent", "deviation", "inconsistent"}

    # HP Pump A runs vibration 6.4 mm/s (> 4.5 limit) and bearing 92C (> 90C):
    # telemetry that contradicts the physical/hydraulic design expectation.
    hpp = next(r for r in rows if r["asset_id"] == "AST-HPP-01")
    assert "vibration_mm_s" in hpp["inconsistent_metrics"]
    assert "bearing_temp_c" in hpp["inconsistent_metrics"]
    assert hpp["status"] in {"deviation", "inconsistent"}


def test_consistency_checks_expected_bounds_are_physical():
    # A reading exactly at its design limit is consistent; just beyond is not.
    ok = sec._consistency_checks({"vibration_mm_s": 4.5, "vibration_limit_mm_s": 4.5})
    assert ok[0]["consistent"] is True
    assert ok[0]["residual_pct"] == 0.0

    bad = sec._consistency_checks({"vibration_mm_s": 9.0, "vibration_limit_mm_s": 4.5})
    assert bad[0]["consistent"] is False
    assert bad[0]["residual_pct"] == pytest.approx(100.0)


def test_sensor_confidence_bounded_and_ordered():
    rows = sec.sensor_confidence()
    assert rows
    confidences = [r["confidence"] for r in rows]
    assert confidences == sorted(confidences)
    for r in rows:
        assert 0.0 <= r["confidence"] <= 1.0
        assert r["band"] in {"high", "medium", "low"}

    # The standby pump has the highest cross-sensor consistency (0.99) and clean
    # telemetry, so it should score at least as high as the degrading duty pump.
    by_asset = {r["asset_id"]: r for r in rows}
    assert by_asset["AST-HPP-02"]["confidence"] >= by_asset["AST-HPP-01"]["confidence"]


# --------------------------------------------------------------------------- #
# Source health
# --------------------------------------------------------------------------- #


def test_source_health_synthetic_is_healthy():
    resolution = sources.resolve_source(config)
    health = sec.source_health(resolution, reading_count=12)
    assert health["status"] == "healthy"
    assert health["fallback"] is False
    assert health["active_source"] == "synthetic"
    assert health["reading_count"] == 12


def test_source_health_fallback_is_degraded():
    resolution = sources.SourceResolution(
        requested="opcua",
        active="synthetic",
        source=sources.SyntheticSource(),
        fallback=True,
        reason="OPC UA endpoint unreachable",
    )
    health = sec.source_health(resolution)
    assert health["status"] == "degraded"
    assert health["fallback"] is True
    assert "unreachable" in health["fallback_reason"]


def test_overall_status_alerts_on_broken_audit():
    consistency = sec.cyber_physical_consistency()
    confidence = sec.sensor_confidence(consistency)
    assert (
        sec.overall_status(
            audit_ok=False,
            source_status="healthy",
            consistency=consistency,
            confidence=confidence,
        )
        == "alert"
    )


# --------------------------------------------------------------------------- #
# SIEM export: integrity, ordering, signature, tamper detection
# --------------------------------------------------------------------------- #


@pytest.fixture()
def seeded_store() -> Store:
    store = Store(database_url=None, connect=False)
    store.audit("scenario.run", payload={"i": 1}, actor="a")
    store.audit("recommendation.decision", payload={"status": "approved"}, actor="b")
    store.audit("report.generated", payload={"job": "x"}, actor="c")
    return store


def test_json_export_preserves_order_and_count(seeded_store: Store):
    events = seeded_store.audit_chain_asc()
    export = siem_export.build_json_export(events, seeded_store.verify_chain())

    assert export["append_only"] is True
    assert export["record_count"] == 3
    assert export["chain"]["verified"] is True

    records = export["records"]
    # Oldest-first with a stable, contiguous 1-based seq.
    assert [r["seq"] for r in records] == [1, 2, 3]
    assert [r["id"] for r in records] == [e["id"] for e in events]
    assert [r["kind"] for r in records] == [
        "scenario.run",
        "recommendation.decision",
        "report.generated",
    ]


def test_json_export_signature_verifies(seeded_store: Store):
    events = seeded_store.audit_chain_asc()
    export = siem_export.build_json_export(events, seeded_store.verify_chain())
    sig = export["signature"]
    assert sig["alg"] == "HMAC-SHA256"
    assert siem_export.verify_signature(
        export["records"], export["chain"]["head"], sig["value"]
    )


def test_export_signature_detects_record_tampering(seeded_store: Store):
    events = seeded_store.audit_chain_asc()
    export = siem_export.build_json_export(events, seeded_store.verify_chain())
    head, sig = export["chain"]["head"], export["signature"]["value"]

    tampered = [dict(r) for r in export["records"]]
    tampered[1]["actor"] = "attacker"
    assert siem_export.verify_signature(tampered, head, sig) is False


def test_export_signature_detects_reordering(seeded_store: Store):
    events = seeded_store.audit_chain_asc()
    export = siem_export.build_json_export(events, seeded_store.verify_chain())
    head, sig = export["chain"]["head"], export["signature"]["value"]

    reordered = list(reversed([dict(r) for r in export["records"]]))
    assert siem_export.verify_signature(reordered, head, sig) is False


def test_export_signature_detects_truncation(seeded_store: Store):
    events = seeded_store.audit_chain_asc()
    export = siem_export.build_json_export(events, seeded_store.verify_chain())
    head, sig = export["chain"]["head"], export["signature"]["value"]

    truncated = [dict(r) for r in export["records"][:-1]]
    assert siem_export.verify_signature(truncated, head, sig) is False


def test_cef_export_is_ordered_and_signed(seeded_store: Store):
    events = seeded_store.audit_chain_asc()
    cef = siem_export.build_cef_export(events, seeded_store.verify_chain())
    lines = cef.strip().splitlines()

    header = [ln for ln in lines if ln.startswith("#") and not ln.startswith("#signature")]
    cef_lines = [ln for ln in lines if ln.startswith("CEF:")]
    sig_lines = [ln for ln in lines if ln.startswith("#signature")]

    assert len(cef_lines) == 3
    assert len(sig_lines) == 1
    assert any("append_only=true" in ln for ln in header)

    # Oldest-first: the seq extension increases monotonically down the file.
    seqs = [int(ln.split("cn1=")[1].split(" ")[0]) for ln in cef_lines]
    assert seqs == [1, 2, 3]


def test_empty_export_is_valid_and_signed():
    store = Store(database_url=None, connect=False)
    export = siem_export.build_json_export(store.audit_chain_asc(), store.verify_chain())
    assert export["record_count"] == 0
    assert siem_export.verify_signature(
        export["records"], export["chain"]["head"], export["signature"]["value"]
    )


# --------------------------------------------------------------------------- #
# Endpoints (dev-bypass: synthetic admin)
# --------------------------------------------------------------------------- #


@pytest.fixture()
def dev_client():
    from app.main import app

    with TestClient(app) as c:
        c.post("/api/v1/reset")
        yield c
        c.post("/api/v1/reset")


def test_security_overview_endpoint_surfaces_all_views(dev_client):
    resp = dev_client.get("/api/v1/security/overview")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["status"] in {"ok", "attention", "alert"}
    assert body["sensor_confidence"]
    assert body["cyber_physical_consistency"]
    assert body["source_health"]["status"] in {"healthy", "degraded", "unknown"}

    # Audit-chain integrity is surfaced (the reset itself is a valid event).
    assert body["audit_integrity"]["ok"] is True

    # Read-only posture is intact.
    assert body["control_boundary"]["control_write_enabled"] is False


def test_security_overview_surfaces_broken_audit(dev_client):
    from app.main import store as app_store

    # Tamper the in-memory chain directly and confirm the view reports the break.
    assert app_store._audit_mem, "expected the reset audit event"
    app_store._audit_mem[0]["payload"]["tampered"] = True

    body = dev_client.get("/api/v1/security/overview").json()
    assert body["audit_integrity"]["ok"] is False
    assert body["status"] == "alert"


def test_siem_export_json_endpoint(dev_client):
    resp = dev_client.get("/api/v1/security/siem-export")
    assert resp.status_code == 200, resp.text
    export = resp.json()
    assert export["export_format"] == "json"
    assert export["append_only"] is True
    assert siem_export.verify_signature(
        export["records"], export["chain"]["head"], export["signature"]["value"]
    )
    seqs = [r["seq"] for r in export["records"]]
    assert seqs == sorted(seqs)


def test_siem_export_cef_endpoint(dev_client):
    resp = dev_client.get("/api/v1/security/siem-export?format=cef")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/plain")
    text = resp.text
    assert "CEF:0|S3M|WaterTwin" in text
    assert "#signature" in text


def test_siem_export_rejects_unknown_format(dev_client):
    resp = dev_client.get("/api/v1/security/siem-export?format=xml")
    assert resp.status_code == 422


def test_siem_export_is_audited(dev_client):
    before = dev_client.get("/api/v1/security/siem-export").json()["record_count"]
    # The export appends its own audit event, so the next export sees one more.
    after = dev_client.get("/api/v1/security/siem-export").json()["record_count"]
    assert after == before + 1


# --------------------------------------------------------------------------- #
# RBAC: the ``security`` role gate (enforced Keycloak-style auth)
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def rsa_keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def _make_token(private_pem: str, *, username: str, roles: list[str]) -> str:
    now = dt.datetime.now(tz=dt.timezone.utc)
    claims = {
        "sub": f"user-{username}",
        "preferred_username": username,
        "iss": TEST_ISSUER,
        "iat": now,
        "exp": now + dt.timedelta(minutes=15),
        "realm_access": {"roles": roles},
    }
    return jwt.encode(claims, private_pem, algorithm="RS256")


@pytest.fixture()
def auth_client(monkeypatch, rsa_keypair):
    private_pem, public_pem = rsa_keypair
    monkeypatch.setenv("WATERTWIN_AUTH_DISABLED", "false")
    monkeypatch.setenv("WATERTWIN_OIDC_PUBLIC_KEY", public_pem)
    monkeypatch.setenv("WATERTWIN_OIDC_ISSUER", TEST_ISSUER)
    monkeypatch.delenv("WATERTWIN_OIDC_AUDIENCE", raising=False)

    from app.main import app, reco_store, store

    reco_store.clear()
    store.reset()

    def token(username: str, roles: list[str]) -> dict:
        return {
            "Authorization": f"Bearer {_make_token(private_pem, username=username, roles=roles)}"
        }

    with TestClient(app) as c:
        c.token = token  # type: ignore[attr-defined]
        yield c


def test_security_role_may_read_overview_and_export(auth_client):
    hdr = auth_client.token("sam-security", ["security"])
    assert auth_client.get("/api/v1/security/overview", headers=hdr).status_code == 200
    assert auth_client.get("/api/v1/security/siem-export", headers=hdr).status_code == 200


def test_viewer_cannot_read_security_403(auth_client):
    hdr = auth_client.token("val-viewer", ["viewer"])
    assert auth_client.get("/api/v1/security/overview", headers=hdr).status_code == 403
    assert auth_client.get("/api/v1/security/siem-export", headers=hdr).status_code == 403


def test_auditor_cannot_read_security_403(auth_client):
    # The audit trail (auditor) and the security views (security) are distinct
    # capabilities; an auditor is not automatically a security analyst.
    hdr = auth_client.token("aud-auditor", ["auditor"])
    assert auth_client.get("/api/v1/security/overview", headers=hdr).status_code == 403


def test_admin_is_superset_for_security(auth_client):
    hdr = auth_client.token("ada-admin", ["admin"])
    assert auth_client.get("/api/v1/security/overview", headers=hdr).status_code == 200
    assert auth_client.get("/api/v1/security/siem-export", headers=hdr).status_code == 200


def test_unauthenticated_security_request_is_401(auth_client):
    resp = auth_client.get("/api/v1/security/overview")
    assert resp.status_code == 401
