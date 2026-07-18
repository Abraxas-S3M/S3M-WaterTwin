"""ADR-0014 — Per-tenant rate limits and quotas (fail loudly, never silently).

Control: uploads-per-hour, total storage, concurrent parse jobs and per-file
size are all capped per tenant; exceeding any cap raises a clear
:class:`QuotaExceeded` (never a silent drop).
"""

from __future__ import annotations

import pytest
from app.quotas import QuotaExceeded, QuotaManager, TenantQuota


def test_uploads_per_hour_cap_fails_loudly():
    qm = QuotaManager(TenantQuota(max_uploads_per_hour=2))
    qm.check_upload("T", 10, now=1000.0)
    qm.record_upload("T", 10, now=1000.0)
    qm.check_upload("T", 10, now=1001.0)
    qm.record_upload("T", 10, now=1001.0)
    with pytest.raises(QuotaExceeded) as exc:
        qm.check_upload("T", 10, now=1002.0)
    assert exc.value.quota == "uploads_per_hour"


def test_rolling_window_frees_up_old_uploads():
    qm = QuotaManager(TenantQuota(max_uploads_per_hour=1))
    qm.check_upload("T", 10, now=0.0)
    qm.record_upload("T", 10, now=0.0)
    # An hour + later, the old upload has fallen out of the window.
    qm.check_upload("T", 10, now=3601.0)  # no raise


def test_storage_cap_fails_loudly():
    qm = QuotaManager(TenantQuota(max_storage_bytes=100))
    qm.check_upload("T", 60, now=0.0)
    qm.record_upload("T", 60, now=0.0)
    with pytest.raises(QuotaExceeded) as exc:
        qm.check_upload("T", 60, now=1.0)
    assert exc.value.quota == "storage_bytes"


def test_per_file_size_cap_fails_loudly():
    qm = QuotaManager(TenantQuota(max_upload_bytes=100))
    with pytest.raises(QuotaExceeded) as exc:
        qm.check_upload("T", 200, now=0.0)
    assert exc.value.quota == "upload_bytes"


def test_concurrent_parse_job_cap_fails_loudly():
    qm = QuotaManager(TenantQuota(max_concurrent_parse_jobs=1))
    qm.acquire_job_slot("T")
    with pytest.raises(QuotaExceeded) as exc:
        qm.acquire_job_slot("T")
    assert exc.value.quota == "concurrent_parse_jobs"
    qm.release_job_slot("T")
    qm.acquire_job_slot("T")  # slot freed


def test_quota_error_is_machine_readable():
    err = QuotaExceeded("storage_bytes", 100, 160, "over cap")
    payload = err.as_dict()
    assert payload["error"] == "quota_exceeded"
    assert payload["quota"] == "storage_bytes"
    assert payload["limit"] == 100
    assert payload["observed"] == 160


def test_deletion_returns_storage_budget():
    qm = QuotaManager(TenantQuota(max_storage_bytes=100))
    qm.record_upload("T", 100, now=0.0)
    assert qm.storage_used("T") == 100
    qm.release_storage("T", 100)
    assert qm.storage_used("T") == 0
