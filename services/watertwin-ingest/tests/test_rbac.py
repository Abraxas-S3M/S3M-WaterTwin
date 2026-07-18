"""RBAC + tenant isolation for the ingest surface.

* ``viewer`` / ``security`` get 404 (not 403) on every route.
* ``operator`` may read history but not upload.
* raw content retrieval is admin-only.
* a tenant can never see another tenant's uploads.
"""

from __future__ import annotations

import pytest

from helpers import upload


def _seed_upload(client, *, tenant="TEN-A"):
    resp = upload(
        client,
        filename="seed.csv",
        content=b"a,b\n1,2\n",
        content_type="text/csv",
        headers=client.token("erin-engineer", ["engineer"], tenant),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["ingest_id"]


@pytest.mark.parametrize("role", ["viewer", "security"])
def test_no_access_roles_get_404_on_every_route(client, role):
    ingest_id = _seed_upload(client)
    headers = client.token(f"user-{role}", [role], "TEN-A")

    # GET list, GET one, GET content, DELETE, POST upload -> all 404.
    assert client.get("/api/v1/ingest/uploads", headers=headers).status_code == 404
    assert client.get(f"/api/v1/ingest/uploads/{ingest_id}", headers=headers).status_code == 404
    assert (
        client.get(f"/api/v1/ingest/uploads/{ingest_id}/content", headers=headers).status_code
        == 404
    )
    assert client.delete(f"/api/v1/ingest/uploads/{ingest_id}", headers=headers).status_code == 404
    post = upload(
        client,
        filename="x.csv",
        content=b"a,b\n1,2\n",
        content_type="text/csv",
        headers=headers,
    )
    assert post.status_code == 404


def test_operator_can_read_history_but_cannot_upload(client):
    _seed_upload(client)
    op = client.token("ola-operator", ["operator"], "TEN-A")

    # Operator may read history.
    listing = client.get("/api/v1/ingest/uploads", headers=op)
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

    # Operator may NOT upload (403, not 404: the surface exists for them).
    post = upload(
        client,
        filename="op.csv",
        content=b"a,b\n1,2\n",
        content_type="text/csv",
        headers=op,
    )
    assert post.status_code == 403


def test_content_retrieval_is_admin_only(client):
    ingest_id = _seed_upload(client)
    engineer = client.token("erin-engineer", ["engineer"], "TEN-A")
    admin = client.token("ada-admin", ["admin"], "TEN-A")

    # Engineer (non-admin) is forbidden the raw bytes.
    assert (
        client.get(f"/api/v1/ingest/uploads/{ingest_id}/content", headers=engineer).status_code
        == 403
    )
    # Admin can stream the immutable bytes back.
    resp = client.get(f"/api/v1/ingest/uploads/{ingest_id}/content", headers=admin)
    assert resp.status_code == 200
    assert resp.content == b"a,b\n1,2\n"


def test_tenant_b_cannot_list_read_or_fetch_tenant_a_upload(client):
    a_id = _seed_upload(client, tenant="TEN-A")

    b_admin = client.token("bob-admin", ["admin"], "TEN-B")
    # List is tenant-scoped: B sees none of A's uploads.
    assert client.get("/api/v1/ingest/uploads", headers=b_admin).json()["total"] == 0
    # Direct read of A's id is a 404 for B (indistinguishable from unknown).
    assert client.get(f"/api/v1/ingest/uploads/{a_id}", headers=b_admin).status_code == 404
    # Content fetch of A's id is a 404 for B even though B is an admin.
    assert (
        client.get(f"/api/v1/ingest/uploads/{a_id}/content", headers=b_admin).status_code == 404
    )
