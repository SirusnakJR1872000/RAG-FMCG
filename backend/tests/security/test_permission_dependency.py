"""`require()` enforces the matrix on the server and audits refusals.

PROJECT_SPEC §13.3; SEC-02, AUD-05. One probe route per permission, then every role is tried
against every permission. When the real endpoints exist,
tests/security/test_endpoint_permissions.py repeats this for them.
"""

import json

import pytest
from fastapi import Depends
from sqlalchemy import select

from auth.dependencies import require, require_any
from auth.permissions import LOGIN_ROLES, PERMISSIONS, has_permission
from database.models import audit_log


@pytest.fixture
def probes(client):
    for permission in PERMISSIONS:
        client.app.add_api_route(f"/api/_probe/{permission}", lambda: {"ok": True},
                                 dependencies=[Depends(require(permission))])
    client.app.add_api_route("/api/_probe/history-or-audit", lambda: {"ok": True},
                             dependencies=[Depends(require_any("history:own", "audit:read"))])
    client.app.add_api_route("/api/_probe/docs-manage-or-users", lambda: {"ok": True},
                             dependencies=[Depends(require_any("docs:manage", "users:manage"))])
    return client


def denials(client):
    with client.app.state.db.read() as conn:
        rows = conn.execute(select(audit_log).where(audit_log.c.event_type == "ACCESS_DENIED")
                            .order_by(audit_log.c.seq)).mappings().all()
    return [(r["username"], r["role"], json.loads(r["payload_json"])) for r in rows]


@pytest.mark.parametrize("permission", PERMISSIONS)
@pytest.mark.parametrize("role", LOGIN_ROLES)
def test_SEC_02_each_role_gets_200_or_403_exactly_as_the_matrix_says(probes, make_headers,
                                                                     role, permission):
    response = probes.get(f"/api/_probe/{permission}", headers=make_headers(role))
    expected = 200 if has_permission(role, permission) else 403
    assert response.status_code == expected, (role, permission)
    if expected == 403:
        assert response.json()["error"]["code"] == "FORBIDDEN"
        assert permission not in response.text  # no hint about what would be needed


def test_AUD_05_every_refusal_is_recorded_with_who_what_and_which_permission(probes,
                                                                             make_headers):
    probes.get("/api/_probe/users:manage", headers=make_headers("viewer"))
    probes.get("/api/_probe/audit:read", headers=make_headers("qa_user"))
    probes.get("/api/_probe/query:run", headers=make_headers("viewer"))  # allowed: no event
    assert denials(probes) == [
        ("viewer_user", "viewer",
         {"endpoint": "GET /api/_probe/users:manage", "permission": "users:manage"}),
        ("qa_user_user", "qa_user",
         {"endpoint": "GET /api/_probe/audit:read", "permission": "audit:read"}),
    ]


def test_a_request_without_a_token_is_401_and_is_not_an_access_denied_event(probes):
    assert probes.get("/api/_probe/query:run").status_code == 401
    assert denials(probes) == []


@pytest.mark.parametrize(("role", "status"), [
    ("viewer", 200), ("qa_user", 200), ("auditor", 200), ("admin", 200)])
def test_require_any_lets_through_a_role_that_has_either_permission(probes, make_headers,
                                                                    role, status):
    response = probes.get("/api/_probe/history-or-audit", headers=make_headers(role))
    assert response.status_code == status  # viewers via history:own, the auditor via audit:read


@pytest.mark.parametrize(("role", "status"), [
    ("viewer", 403), ("qa_user", 200), ("auditor", 403), ("admin", 200)])
def test_require_any_refuses_and_audits_a_role_that_has_neither(probes, make_headers, role, status):
    response = probes.get("/api/_probe/docs-manage-or-users", headers=make_headers(role))
    assert response.status_code == status
    if status == 403:
        (_, _, payload) = denials(probes)[-1]
        assert payload["permission"] == "docs:manage or users:manage"
