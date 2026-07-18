"""ADR-0014 T10 — Cross-tenant access (read, list, and content) denied.

Control: every read is tenant-scoped; a caller can only ever see its own
tenant's uploads. Cross-tenant metadata, listing, and content access are all
refused before any data is returned.
"""

from __future__ import annotations

import pytest
from app.service import IngestService
from app.tenancy import CrossTenantAccessDenied


def _service_with_two_tenants():
    svc = IngestService(profile="standard")
    a = svc.upload(
        tenant_id="TEN-A",
        uploaded_by="alice",
        filename="a.csv",
        data=b"analyte,value\nturbidity,0.3\n",
        parser="csv",
    )
    b = svc.upload(
        tenant_id="TEN-B",
        uploaded_by="bob",
        filename="b.csv",
        data=b"analyte,value\nchlorine,0.9\n",
        parser="csv",
    )
    return svc, a, b


def test_cross_tenant_metadata_read_denied():
    svc, a, b = _service_with_two_tenants()
    with pytest.raises(CrossTenantAccessDenied):
        svc.get_metadata(caller_tenant="TEN-B", upload_id=a.upload_id)


def test_cross_tenant_content_read_denied():
    svc, a, b = _service_with_two_tenants()
    with pytest.raises(CrossTenantAccessDenied):
        svc.get_content(caller_tenant="TEN-B", upload_id=a.upload_id)


def test_list_never_leaks_other_tenants():
    svc, a, b = _service_with_two_tenants()
    a_list = svc.list_uploads(caller_tenant="TEN-A")
    b_list = svc.list_uploads(caller_tenant="TEN-B")
    assert {u["upload_id"] for u in a_list} == {a.upload_id}
    assert {u["upload_id"] for u in b_list} == {b.upload_id}
    # No overlap: TEN-A never sees TEN-B's upload and vice versa.
    assert not {u["tenant_id"] for u in a_list} & {"TEN-B"}


def test_same_tenant_access_still_works():
    svc, a, b = _service_with_two_tenants()
    meta = svc.get_metadata(caller_tenant="TEN-A", upload_id=a.upload_id)
    assert meta["upload_id"] == a.upload_id
    assert svc.get_content(caller_tenant="TEN-A", upload_id=a.upload_id)


def test_cross_tenant_delete_denied():
    svc, a, b = _service_with_two_tenants()
    with pytest.raises(CrossTenantAccessDenied):
        svc.delete_content(caller_tenant="TEN-B", upload_id=a.upload_id, actor="bob")
