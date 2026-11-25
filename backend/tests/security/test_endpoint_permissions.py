"""Every endpoint against every role, generated from the permission matrix (SEC-02, §13.3).

If someone adds an endpoint and forgets its permission check, or changes a role in
auth/permissions.py without thinking, one of these cases fails.
"""

import pytest
from sqlalchemy import func, select

from auth.permissions import LOGIN_ROLES, ROLE_PERMISSIONS
from database.models import audit_log

# (method, path, JSON body, permissions of which the caller needs ANY ONE)
ENDPOINTS = [
    ("POST", "/api/conversations", None, {"query:run"}),
    ("POST", "/api/query", {"question": "What is an OOS result?"}, {"query:run"}),
    ("POST", "/api/query/stream", {"question": "What is an OOS result?"}, {"query:run"}),
    ("POST", "/api/feedback", {"query_event_id": "evt_x", "rating": 1}, {"query:run"}),
    ("GET", "/api/history", None, {"history:own", "audit:read"}),
    ("GET", "/api/history/evt_x", None, {"history:own", "audit:read"}),
    ("GET", "/api/documents", None, {"docs:read"}),
    ("GET", "/api/audit/log", None, {"audit:read"}),
    ("POST", "/api/audit/verify", None, {"audit:read"}),
    ("GET", "/api/audit/export", None, {"audit:export"}),
    ("GET", "/api/users", None, {"users:manage"}),
    ("POST", "/api/users", {"username": "zed", "full_name": "Z", "role": "viewer"},
     {"users:manage"}),
    ("PATCH", "/api/users/u_x", {"unlock": True}, {"users:manage"}),
    ("GET", "/api/health/details", None, {"health:details"}),
]
CASES = [(m, p, b, need, role) for m, p, b, need in ENDPOINTS for role in LOGIN_ROLES]


def ids(case):
    method, path, _, _, role = case
    return f"{role}:{method} {path}"


def denied_count(client):
    with client.app.state.db.read() as conn:
        return conn.execute(select(func.count()).select_from(audit_log).where(
            audit_log.c.event_type == "ACCESS_DENIED")).scalar_one()


@pytest.fixture
def tokens_by_role(make_headers):
    return {role: make_headers(role) for role in LOGIN_ROLES}


@pytest.mark.parametrize("case", CASES, ids=ids)
def test_SEC_02_each_role_gets_403_exactly_where_the_matrix_says(client, tokens_by_role, case):
    method, path, body, need, role = case
    allowed = bool(ROLE_PERMISSIONS[role] & need)
    before = denied_count(client)
    response = client.request(method, path, headers=tokens_by_role[role], json=body)
    if allowed:
        assert response.status_code not in (401, 403), response.text
        assert denied_count(client) == before
    else:
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"
        assert denied_count(client) == before + 1  # exactly one ACCESS_DENIED event


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=lambda e: f"{e[0]} {e[1]}")
def test_SEC_01_no_endpoint_works_without_a_token(client, endpoint):
    method, path, body, _ = endpoint
    response = client.request(method, path, json=body)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


def test_the_matrix_covers_every_protected_endpoint(client):
    """A new route that is not in ENDPOINTS (or public) fails here, so it cannot be forgotten."""
    public = {("POST", "/api/auth/login"), ("POST", "/api/auth/refresh"),
              ("POST", "/api/auth/logout"), ("GET", "/api/health"),
              # any signed-in user, even before the first password change:
              ("GET", "/api/me"), ("POST", "/api/auth/change-password")}
    listed = {(m, p.replace("evt_x", "{event_id}").replace("u_x", "{user_id}"))
              for m, p, _, _ in ENDPOINTS}
    actual = {(method.upper(), path) for path, item in client.app.openapi()["paths"].items()
              for method in item}
    assert actual - public == listed
