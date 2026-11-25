"""Authentication through the HTTP API (PROJECT_SPEC §13, §16; SEC-01, SEC-03..SEC-06, SEC-10)."""

import datetime as dt
import json

from sqlalchemy import select

from auth import tokens
from database.models import audit_log, refresh_tokens
from tests.conftest import ORIGIN, PASSWORD, add_user, sign_in

FROM_THE_SITE = {"Origin": ORIGIN}


def events(client, event_type):
    with client.app.state.db.read() as conn:
        rows = conn.execute(select(audit_log).where(audit_log.c.event_type == event_type)
                            .order_by(audit_log.c.seq)).mappings().all()
    return [{**r, "payload": json.loads(r["payload_json"])} for r in rows]


def use_cookie(client, value):
    """Make the client send exactly this refresh cookie (an old or stolen copy), nothing else."""
    client.cookies.clear()
    client.cookies.set("refresh_token", value, domain="app.test", path="/api/auth")


def login(client, username="alice", password=PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password})


# ── login ────────────────────────────────────────────────────────────────────────────────

def test_login_returns_an_access_token_and_a_locked_down_refresh_cookie(client):
    add_user(client, "alice", "qa_user")
    response = login(client)
    body = response.json()
    assert response.status_code == 200 and body["token_type"] == "bearer"
    assert body["expires_in"] == 15 * 60 and body["must_change_password"] is False
    assert response.headers["cache-control"] == "no-store"
    cookie = response.headers["set-cookie"]  # §13.1
    for part in ("refresh_token=", "HttpOnly", "Secure", "SameSite=strict", "Path=/api/auth"):
        assert part in cookie, part
    assert body["access_token"] not in cookie  # the access token is never in a cookie
    assert "refresh_token" not in response.text  # nor is the refresh token in the body


def test_the_access_token_opens_me_and_carries_the_permissions(client):
    add_user(client, "alice", "qa_user")
    me = client.get("/api/me", headers=sign_in(client, "alice")).json()
    assert me["username"] == "alice" and me["role"] == "qa_user"
    assert me["permissions"] == ["docs:manage", "docs:read", "history:own", "query:run"]
    assert set(me) == {"id", "username", "full_name", "role", "permissions",
                       "must_change_password"}  # no hash, no failed-login count, ...
    assert me["must_change_password"] is False


def test_the_login_audit_event_names_the_user_the_ip_and_the_request(client):
    user = add_user(client, "alice")
    response = login(client)
    (event,) = events(client, "LOGIN_SUCCESS")
    assert event["user_id"] == user["id"] and event["client_ip"] == "testclient"
    assert event["request_id"] == response.headers["x-request-id"]


def test_wrong_password_unknown_user_and_deactivated_account_get_the_same_answer(client):
    add_user(client, "alice")
    add_user(client, "gone")
    with client.app.state.db.write() as conn:
        from sqlalchemy import update

        from database.models import users
        conn.execute(update(users).where(users.c.username == "gone").values(is_active=0))
    answers = [login(client, "alice", "wrong"), login(client, "nobody"), login(client, "gone")]
    bodies = [{**a.json()["error"], "request_id": "-"} for a in answers]
    assert [a.status_code for a in answers] == [401, 401, 401]
    assert bodies[0] == bodies[1] == bodies[2]
    assert bodies[0]["message"] == "Username or password is incorrect."
    assert "set-cookie" not in answers[0].headers


def test_SEC_04_the_fifth_failure_locks_the_account_and_the_right_password_no_longer_works(client):
    add_user(client, "alice")
    codes = [login(client, "alice", "wrong").json()["error"]["code"] for _ in range(5)]
    assert codes == ["INVALID_CREDENTIALS"] * 4 + ["ACCOUNT_LOCKED"]
    locked = login(client)  # the correct password
    assert locked.status_code == 423 and locked.headers["retry-after"] == "1800"
    assert "30 minutes" in locked.json()["error"]["message"]
    assert len(events(client, "ACCOUNT_LOCKED")) == 1 and len(events(client, "LOGIN_FAILED")) == 6


def test_SEC_10_login_attempts_are_rate_limited_per_ip(settings, make_client):
    client = make_client(settings.model_copy(update={"rate_limit_login": "3/minute"}))
    statuses = [login(client, "nobody").status_code for _ in range(5)]
    assert statuses == [401, 401, 401, 429, 429]
    limited = login(client, "nobody")
    assert limited.json()["error"]["code"] == "RATE_LIMITED" and limited.headers["retry-after"]


# ── tokens presented to protected endpoints ──────────────────────────────────────────────

def test_SEC_01_no_token_a_bad_token_or_a_forged_token_is_refused(client):
    user = add_user(client, "alice", "admin")
    secret = client.app.state.settings.jwt_secret_key
    now = dt.datetime.now(dt.UTC)
    cases = {
        "none": ({}, "NOT_AUTHENTICATED"),
        "garbage": ({"Authorization": "Bearer nonsense"}, "INVALID_TOKEN"),
        "wrong scheme": ({"Authorization": "Basic YTpi"}, "NOT_AUTHENTICATED"),
        "other key": ({"Authorization": "Bearer " + tokens.create_access_token(
            user["id"], "admin", "z" * 64, 15)}, "INVALID_TOKEN"),
        "expired": ({"Authorization": "Bearer " + tokens.create_access_token(
            user["id"], "admin", secret, 15, now - dt.timedelta(minutes=16))}, "TOKEN_EXPIRED"),
        "unknown user": ({"Authorization": "Bearer " + tokens.create_access_token(
            "u_nobody", "admin", secret, 15)}, "INVALID_TOKEN"),
    }
    for name, (headers, code) in cases.items():
        response = client.get("/api/me", headers=headers)
        assert (response.status_code, response.json()["error"]["code"]) == (401, code), name


def test_a_forged_role_in_the_token_does_not_grant_anything(client):
    """The role comes from the database on every request, not from the token."""
    user = add_user(client, "alice", "viewer")
    secret = client.app.state.settings.jwt_secret_key
    forged = tokens.create_access_token(user["id"], "admin", secret, 15)
    me = client.get("/api/me", headers={"Authorization": f"Bearer {forged}"}).json()
    assert me["role"] == "viewer"
    assert client.get("/api/health/details", headers={"Authorization": f"Bearer {forged}"}
                      ).status_code == 403


def test_deactivating_a_user_takes_effect_at_once_not_when_the_token_expires(client):
    add_user(client, "alice")
    headers = sign_in(client, "alice")
    assert client.get("/api/me", headers=headers).status_code == 200
    with client.app.state.db.write() as conn:
        from sqlalchemy import update

        from database.models import users
        conn.execute(update(users).where(users.c.username == "alice").values(is_active=0))
    assert client.get("/api/me", headers=headers).status_code == 401


# ── forced password change ───────────────────────────────────────────────────────────────

def test_a_temporary_password_blocks_everything_except_me_and_change_password(client):
    add_user(client, "newbie", "admin", must_change=True)
    response = login(client, "newbie")
    assert response.json()["must_change_password"] is True
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    blocked = client.get("/api/health/details", headers=headers)
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"
    me = client.get("/api/me", headers=headers).json()
    assert me["must_change_password"] is True  # the UI reads this to show the change form


def test_changing_the_password_unlocks_the_account_and_signs_out_other_devices(client):
    add_user(client, "newbie", "admin", must_change=True)
    first = login(client, "newbie")
    old_cookie = client.cookies.get("refresh_token", domain="app.test", path="/api/auth")
    headers = {"Authorization": f"Bearer {first.json()['access_token']}"}
    done = client.post("/api/auth/change-password", headers=headers, json={
        "current_password": PASSWORD, "new_password": "a-completely-new-secret-77"})
    assert done.status_code == 200 and done.json()["must_change_password"] is False
    assert "refresh_token=" in done.headers["set-cookie"]
    new_headers = {"Authorization": f"Bearer {done.json()['access_token']}"}
    assert client.get("/api/health/details", headers=new_headers).status_code == 200
    use_cookie(client, old_cookie)  # the other device
    assert client.post("/api/auth/refresh", headers=FROM_THE_SITE).status_code == 401
    assert login(client, "newbie", PASSWORD).status_code == 401  # the old password is gone
    assert login(client, "newbie", "a-completely-new-secret-77").status_code == 200
    (event,) = events(client, "PASSWORD_CHANGED")
    assert event["payload"] == {"kind": "forced"}


def test_change_password_reports_each_broken_rule_without_echoing_the_password(client):
    add_user(client, "alice")
    headers = sign_in(client, "alice")

    def attempt(**fields):
        return client.post("/api/auth/change-password", headers=headers,
                           json={"current_password": PASSWORD, **fields})

    short = attempt(new_password="tiny")
    assert short.status_code == 422 and short.json()["error"]["code"] == "PASSWORD_POLICY"
    assert short.json()["error"]["details"] == [{"rule": "TOO_SHORT"}]
    assert [d["rule"] for d in attempt(new_password="Password1234").json()["error"]["details"]] \
        == ["COMMON"]
    assert [d["rule"] for d in attempt(new_password=PASSWORD).json()["error"]["details"]] \
        == ["REUSED"]
    assert "tiny" not in short.text
    wrong = client.post("/api/auth/change-password", headers=headers, json={
        "current_password": "not-it", "new_password": "a-completely-new-secret-77"})
    assert wrong.status_code == 400 and wrong.json()["error"]["code"] == "WRONG_CURRENT_PASSWORD"


# ── refresh and logout ───────────────────────────────────────────────────────────────────

def test_refresh_rotates_the_cookie_and_returns_a_new_access_token(client):
    add_user(client, "alice")
    login(client)
    before = client.cookies.get("refresh_token", domain="app.test", path="/api/auth")
    response = client.post("/api/auth/refresh", headers=FROM_THE_SITE)
    assert response.status_code == 200 and response.json()["access_token"]
    after = client.cookies.get("refresh_token", domain="app.test", path="/api/auth")
    assert before and after and before != after
    token = response.json()["access_token"]
    assert client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_the_csrf_check_refuses_cookie_requests_from_another_site_or_without_an_origin(client):
    add_user(client, "alice")
    login(client)
    for headers in ({}, {"Origin": "https://evil.example"}, {"Origin": ORIGIN + ".evil"}):
        for path in ("/api/auth/refresh", "/api/auth/logout"):
            response = client.post(path, headers=headers)
            assert (response.status_code, response.json()["error"]["code"]) \
                == (403, "ORIGIN_NOT_ALLOWED"), (path, headers)
    assert client.post("/api/auth/refresh", headers=FROM_THE_SITE).status_code == 200  # still valid


def test_a_stolen_old_refresh_token_signs_everyone_out_and_is_audited(client):
    user = add_user(client, "alice")
    login(client)
    stolen = client.cookies.get("refresh_token", domain="app.test", path="/api/auth")
    assert client.post("/api/auth/refresh", headers=FROM_THE_SITE).status_code == 200  # victim
    use_cookie(client, stolen)
    thief = client.post("/api/auth/refresh", headers=FROM_THE_SITE)  # the thief replays it
    assert thief.status_code == 401 and thief.json()["error"]["code"] == "SESSION_INVALID"
    assert "Max-Age=0" in thief.headers["set-cookie"]  # and the dead cookie is cleared
    (event,) = events(client, "REFRESH_REUSE_DETECTED")
    assert event["user_id"] == user["id"] and event["payload"]["family_id"]
    with client.app.state.db.read() as conn:  # the victim's newest token died with the family
        assert all(r[0] for r in conn.execute(select(refresh_tokens.c.revoked)))


def test_refresh_without_a_cookie_is_a_plain_401(client):
    response = client.post("/api/auth/refresh", headers=FROM_THE_SITE)
    assert response.status_code == 401 and response.json()["error"]["code"] == "SESSION_INVALID"


def test_logout_ends_the_session_clears_the_cookie_and_is_audited(client):
    add_user(client, "alice")
    login(client)
    cookie = client.cookies.get("refresh_token", domain="app.test", path="/api/auth")
    response = client.post("/api/auth/logout", headers=FROM_THE_SITE)
    assert response.status_code == 204 and "Max-Age=0" in response.headers["set-cookie"]
    use_cookie(client, cookie)  # a copy of the old cookie
    assert client.post("/api/auth/refresh", headers=FROM_THE_SITE).status_code == 401
    assert len(events(client, "LOGOUT")) == 1


def test_logout_without_a_session_is_harmless(client):
    assert client.post("/api/auth/logout", headers=FROM_THE_SITE).status_code == 204
    assert events(client, "LOGOUT") == []
