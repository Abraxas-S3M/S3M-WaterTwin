"""ADR-0014 — Retention behaviour and data residency.

Retention: configurable per tenant; deletion removes file *content* but the
tamper-evident *audit entries* survive. Residency: per-tenant storage region is
enforced for regulated jurisdictions (incl. Saudi critical infrastructure).
"""

from __future__ import annotations

import pytest
from app.residency import ResidencyPolicy, ResidencyRegistry, ResidencyViolation
from app.retention import RetentionPolicy, RetentionRegistry
from app.service import IngestService

# --- Retention -------------------------------------------------------------- #


def test_retention_period_is_configurable_per_tenant():
    reg = RetentionRegistry(default_days=90)
    reg.set_policy(RetentionPolicy(tenant_id="TEN-A", content_retention_days=7))
    assert reg.policy_for("TEN-A").content_retention_days == 7
    assert reg.policy_for("TEN-OTHER").content_retention_days == 90


def test_content_expiry_uses_the_tenant_period():
    policy = RetentionPolicy(tenant_id="TEN-A", content_retention_days=30)
    day = 86400.0
    assert policy.content_expired(uploaded_at=0.0, now=29 * day) is False
    assert policy.content_expired(uploaded_at=0.0, now=31 * day) is True


def test_retention_sweep_deletes_content_but_keeps_audit():
    retention = RetentionRegistry(default_days=1)
    svc = IngestService(profile="standard", retention=retention)
    record = svc.upload(
        tenant_id="TEN-A",
        uploaded_by="alice",
        filename="lab.csv",
        data=b"analyte,value\nturbidity,0.3\n",
        parser="csv",
        now=0.0,
    )
    deleted = svc.sweep_retention(now=10 * 86400.0)
    assert record.upload_id in deleted
    # Content is gone...
    from app.tenancy import UploadNotFound

    with pytest.raises(UploadNotFound):
        svc.get_content(caller_tenant="TEN-A", upload_id=record.upload_id)
    # ...but the audit chain (received/parsed/deleted) survives and verifies.
    assert svc.verify_audit()["ok"] is True
    kinds = {
        e["kind"]
        for e in svc.audit_trail(caller_tenant="TEN-A", upload_id=record.upload_id)
    }
    assert {"upload.received", "upload.parsed", "upload.deleted"} <= kinds


def test_explicit_deletion_documents_what_survives():
    svc = IngestService(profile="standard")
    record = svc.upload(
        tenant_id="TEN-A",
        uploaded_by="alice",
        filename="lab.csv",
        data=b"analyte,value\n",
        parser="csv",
    )
    meta = svc.delete_content(
        caller_tenant="TEN-A", upload_id=record.upload_id, actor="alice"
    )
    # What does NOT survive: content. What survives: metadata + audit hash.
    assert meta["content_deleted"] is True
    assert meta["content_sha256"]  # hash retained for non-repudiation


# --- Residency -------------------------------------------------------------- #


def test_default_residency_region_is_enforced():
    reg = ResidencyRegistry(default_region="SA")
    # Saudi tenant: storing outside SA is a violation.
    with pytest.raises(ResidencyViolation):
        reg.assert_storage_allowed("TEN-SA", "EU")
    reg.assert_storage_allowed("TEN-SA", "SA")  # no raise


def test_per_tenant_residency_override():
    reg = ResidencyRegistry(default_region="SA")
    reg.set_policy(ResidencyPolicy(tenant_id="TEN-EU", region="EU"))
    reg.assert_storage_allowed("TEN-EU", "EU")
    with pytest.raises(ResidencyViolation):
        reg.assert_storage_allowed("TEN-EU", "US")


def test_upload_refuses_out_of_region_storage():
    reg = ResidencyRegistry(default_region="SA")
    svc = IngestService(profile="standard", residency=reg)
    with pytest.raises(ResidencyViolation):
        svc.upload(
            tenant_id="TEN-SA",
            uploaded_by="alice",
            filename="lab.csv",
            data=b"analyte,value\n",
            parser="csv",
            storage_region="US",
        )
