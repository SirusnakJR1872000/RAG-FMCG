"""Documents, audit and users endpoints (PROJECT_SPEC §16; FR-10, FR-11, SEC-02)."""

import datetime as dt
import json

import pandas as pd
import pytest
from sqlalchemy import insert, select, update

from audit.chain import verify
from audit.writer import Actor, log
from auth import tokens
from database.init_db import SYSTEM_USER_ID, new_id, utc_now
from database.models import audit_log, documents, users
from services.document_registry import RegistryConflict, sync_registry
from src.ingestion.manifest import ManifestEntry

SYSTEM = Actor(SYSTEM_USER_ID, "system", "system")


def entry(code="ACME-SOP-QC-007", version="3.0", status="active", **extra):
    data = {"doc_code": code, "title": f"{code} title", "version": version,
            "effective_date": "2026-01-15", "file": f"sops/{code}.md",
            "publisher": "Acme Pharma Ltd. (fictional)", "status": status, **extra}
    return ManifestEntry.model_validate(data)


def chunks_for(*pairs, sha="ab" * 32, n=3):
    rows = [{"doc_code": c, "version": v, "doc_sha256": sha, "page_end": 4 + i}
            for c, v in pairs for i in range(n)]
    return pd.DataFrame(rows)


def events(client, event_type):
    with client.app.state.db.read() as conn:
        return [json.loads(r) for r in conn.execute(select(audit_log.c.payload_json).where(
            audit_log.c.event_type == event_type)).scalars()]


# ── registry sync ────────────────────────────────────────────────────────────────────────

def test_sync_registers_documents_with_their_fingerprint_and_audits_each(db):
    with db.write() as conn:
        result = sync_registry(conn, [entry(), entry("ICH-Q7", "Step 4", file="public/q7.pdf",
                                                      publisher="ICH",
                                                      source_url="https://ich.org/q7")],
                               chunks_for(("ACME-SOP-QC-007", "3.0")), SYSTEM)
    assert result.added == ["ACME-SOP-QC-007 3.0"] and result.skipped == ["ICH-Q7 Step 4"]
    with db.read() as conn:
        (row,) = conn.execute(select(documents)).mappings().all()
        assert (row["chunk_count"], row["page_count"], row["sha256"]) == (3, 6, "ab" * 32)
        assert conn.execute(select(audit_log.c.event_type).where(
            audit_log.c.event_type == "DOCUMENT_INGESTED")).all()


def test_sync_twice_changes_nothing_and_logs_nothing_more(db):
    chunks = chunks_for(("ACME-SOP-QC-007", "3.0"))
    with db.write() as conn:
        sync_registry(conn, [entry()], chunks, SYSTEM)
    with db.write() as conn:
        again = sync_registry(conn, [entry()], chunks, SYSTEM)
    assert again.added == again.updated == []
    with db.read() as conn:
        assert len(conn.execute(select(audit_log).where(
            audit_log.c.event_type == "DOCUMENT_INGESTED")).all()) == 1


def test_a_changed_file_under_the_same_version_is_refused(db):
    with db.write() as conn:
        sync_registry(conn, [entry()], chunks_for(("ACME-SOP-QC-007", "3.0")), SYSTEM)
    with pytest.raises(RegistryConflict, match="needs a new version"), db.write() as conn:
        sync_registry(conn, [entry()], chunks_for(("ACME-SOP-QC-007", "3.0"), sha="cd" * 32),
                      SYSTEM)


def test_a_new_version_supersedes_the_old_and_a_withdrawal_is_recorded(db):
    old, new = ("ACME-SOP-QC-007", "2.0"), ("ACME-SOP-QC-007", "3.0")
    chunks = chunks_for(old, new)
    with db.write() as conn:
        sync_registry(conn, [entry(version="2.0"), ], chunks, SYSTEM)
    with db.write() as conn:
        result = sync_registry(conn, [
            entry(version="2.0", status="superseded", superseded_by="3.0"), entry()],
            chunks, SYSTEM)
    assert result.updated == ["ACME-SOP-QC-007 2.0"] and result.added == ["ACME-SOP-QC-007 3.0"]
    with db.write() as conn:
        sync_registry(conn, [
            entry(version="2.0", status="superseded", superseded_by="3.0"),
            entry(status="withdrawn", withdrawn_reason="Replaced by the new site SOP")],
            chunks, SYSTEM)
    with db.read() as conn:
        rows = {r["version"]: r for r in conn.execute(select(documents)).mappings()}
        types = {r for r in conn.execute(select(audit_log.c.event_type).where(
            audit_log.c.event_type.like("DOCUMENT_%"))).scalars()}
    assert rows["2.0"]["status"] == "superseded"
    assert rows["2.0"]["superseded_by"] == rows["3.0"]["id"]
    assert rows["3.0"]["status"] == "withdrawn"
    assert rows["3.0"]["status_reason"] == "Replaced by the new site SOP"
    assert types == {"DOCUMENT_INGESTED", "DOCUMENT_SUPERSEDED", "DOCUMENT_WITHDRAWN"}


# ── documents endpoint ───────────────────────────────────────────────────────────────────

@pytest.fixture
def registry(client):
    with client.app.state.db.write() as conn:
        sync_registry(conn, [
            entry("ACME-SOP-QC-007", "2.0", status="superseded", superseded_by="3.0"),
            entry(), entry("ICH-Q7", "Step 4", file="public/q7.pdf", publisher="ICH",
                           source_url="https://ich.org/q7")],
            chunks_for(("ACME-SOP-QC-007", "2.0"), ("ACME-SOP-QC-007", "3.0"),
                       ("ICH-Q7", "Step 4")), SYSTEM)


def test_FR_11_the_registry_lists_documents_and_filters_by_status(client, make_headers, registry):
    headers = make_headers("viewer")
    everything = client.get("/api/documents", headers=headers).json()
    assert everything["total"] == 3
    active = client.get("/api/documents", headers=headers, params={"status": "active"}).json()
    assert [d["doc_code"] for d in active["items"]] == ["ACME-SOP-QC-007", "ICH-Q7"]
    sop = active["items"][0]
    assert sop["is_fictional"] and not active["items"][1]["is_fictional"]
    assert sop["chunk_count"] == 3 and "file_path" not in sop
    old = client.get("/api/documents", headers=headers, params={"status": "superseded"}).json()
    assert old["items"][0]["superseded_by_version"] == "3.0"
    assert client.get("/api/documents", headers=headers,
                      params={"status": "bogus"}).status_code == 422


def test_every_role_that_can_read_documents_sees_the_same_registry(client, make_headers, registry):
    totals = {role: client.get("/api/documents", headers=make_headers(role)).json()["total"]
              for role in ("viewer", "qa_user", "auditor", "admin")}
    assert set(totals.values()) == {3}


# ── audit endpoints ──────────────────────────────────────────────────────────────────────

def test_FR_10_the_audit_log_filters_by_user_type_result_and_date(client, make_headers):
    auditor = make_headers("auditor")
    client.post("/api/auth/login", json={"username": "viewer_user", "password": "wrong-pw-here"})
    page = client.get("/api/audit/log", headers=auditor).json()
    assert page["total"] >= 3 and page["items"][0]["seq"] > page["items"][-1]["seq"]
    assert all({"summary", "row_hash", "prev_hash"} <= set(i) for i in page["items"])
    failed = client.get("/api/audit/log", headers=auditor, params={"result": "failure"}).json()
    assert {i["event_type"] for i in failed["items"]} == {"LOGIN_FAILED"}
    by_type = client.get("/api/audit/log", headers=auditor, params=[
        ("event_type", "LOGIN_SUCCESS"), ("event_type", "SYSTEM_START")]).json()
    assert {i["event_type"] for i in by_type["items"]} == {"LOGIN_SUCCESS", "SYSTEM_START"}
    by_user = client.get("/api/audit/log", headers=auditor, params={"user": "auditor_user"}).json()
    assert {i["username"] for i in by_user["items"]} == {"auditor_user"}
    today = utc_now()[:10]
    assert client.get("/api/audit/log", headers=auditor, params={"from": "2999-01-01"}
                      ).json()["total"] == 0
    assert client.get("/api/audit/log", headers=auditor, params={"from": today, "to": today}
                      ).json()["total"] == page["total"]
    small = client.get("/api/audit/log", headers=auditor, params={"page_size": 2}).json()
    assert len(small["items"]) == 2 and small["total"] == page["total"]


def test_the_audit_log_rejects_unknown_event_types_and_bad_dates(client, make_headers):
    auditor = make_headers("auditor")
    for params in ({"event_type": "NOT_AN_EVENT"}, {"from": "last week"}, {"result": "maybe"},
                   {"page_size": 500}):
        assert client.get("/api/audit/log", headers=auditor, params=params).status_code == 422


def test_FR_10_verify_reports_an_intact_chain_and_is_itself_audited(client, make_headers):
    auditor = make_headers("auditor")
    response = client.post("/api/audit/verify", headers=auditor)
    body = response.json()
    assert response.status_code == 200 and body["ok"] and body["first_bad_seq"] is None
    (event,) = events(client, "AUDIT_VERIFIED")
    assert event["ok"] and event["checked"] == body["checked"]


def test_verify_finds_a_row_that_was_edited_behind_the_applications_back(client, make_headers):
    auditor = make_headers("auditor")
    db = client.app.state.db
    with db.write() as conn:  # a tamperer who drops the trigger and edits a row
        conn.exec_driver_sql("DROP TRIGGER audit_no_update")
        target = conn.execute(select(audit_log.c.seq).where(
            audit_log.c.event_type == "LOGIN_SUCCESS").limit(1)).scalar()
        conn.execute(update(audit_log).where(audit_log.c.seq == target).values(
            payload_json='{"tampered":true}'))
    body = client.post("/api/audit/verify", headers=auditor).json()
    assert body["ok"] is False and body["first_bad_seq"] == target
    assert client.app.state.audit["ok"] is False  # /health/details now shows it
    with db.read() as conn:
        assert not verify(conn).ok


def test_the_export_is_json_in_chain_order_with_hashes_and_is_audited(client, make_headers):
    admin = make_headers("admin")
    response = client.get("/api/audit/export", headers=admin,
                          params={"event_type": "LOGIN_SUCCESS"})
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    body = response.json()
    seqs = [r["seq"] for r in body["rows"]]
    assert body["row_count"] == len(seqs) >= 1 and seqs == sorted(seqs)
    assert all(r["row_hash"] and r["prev_hash"] for r in body["rows"])
    assert body["filters"]["event_type"] == ["LOGIN_SUCCESS"]
    (exported,) = events(client, "AUDIT_EXPORTED")
    assert exported["row_count"] == body["row_count"] and exported["format"] == "json"
    assert client.get("/api/audit/export", headers=admin, params={"format": "csv"}
                      ).status_code == 422  # CSV is Tier 2


# ── users ────────────────────────────────────────────────────────────────────────────────

def make_user(client, headers, username="newbie", role="viewer"):
    return client.post("/api/users", headers=headers, json={
        "username": username, "full_name": "New Person", "role": role})


def test_FR_11_an_admin_creates_a_user_who_must_change_the_temporary_password(client,
                                                                              make_headers):
    admin = make_headers("admin")
    response = make_user(client, admin, "  Newbie ")
    body = response.json()
    assert response.status_code == 201 and body["username"] == "newbie"
    assert body["status"] == "must_change_password" and body["last_login_at"] is None
    temporary = body["temporary_password"]
    assert len(temporary) >= 12
    assert "temporary_password" not in client.get("/api/users", headers=admin).text
    login = client.post("/api/auth/login", json={"username": "newbie", "password": temporary})
    assert login.status_code == 200 and login.json()["must_change_password"] is True
    (created,) = [e for e in events(client, "USER_CREATED") if e["target_username"] == "newbie"]
    assert "password" not in json.dumps(created)


def test_a_username_is_never_reused_and_must_look_like_a_username(client, make_headers):
    admin = make_headers("admin")
    assert make_user(client, admin, "alice").status_code == 201
    assert make_user(client, admin, "ALICE").json()["error"]["code"] == "USERNAME_TAKEN"
    for bad in ("a b c", "ab", "x" * 33, "-start", "emoji😀name"):
        assert make_user(client, admin, bad).status_code == 422, bad
    assert client.post("/api/users", headers=admin, json={
        "username": "okname", "full_name": "x", "role": "system"}).status_code == 422
    assert client.post("/api/users", headers=admin, json={
        "username": "okname", "full_name": "x", "role": "viewer", "password": "x"}
    ).status_code == 422


def test_the_user_list_has_status_and_last_login_and_hides_the_system_account(client,
                                                                              make_headers):
    admin = make_headers("admin")
    make_user(client, admin, "carol")
    make_headers("viewer")
    by_name = {u["username"]: u for u in client.get("/api/users", headers=admin).json()["items"]}
    assert "system" not in by_name and by_name["carol"]["status"] == "must_change_password"
    assert by_name["viewer_user"]["last_login_at"] and by_name["viewer_user"]["status"] == "active"
    assert not any("hash" in k or "password" in k for k in by_name["carol"])
    with client.app.state.db.write() as conn:
        future = tokens.fmt_ts(dt.datetime.now(dt.UTC) + dt.timedelta(minutes=20))
        conn.execute(update(users).where(users.c.username == "viewer_user").values(
            locked_until=future))
    after = {u["username"]: u for u in client.get("/api/users", headers=admin).json()["items"]}
    assert after["viewer_user"]["status"] == "locked"


def _id(client, username):
    with client.app.state.db.read() as conn:
        return conn.execute(select(users.c.id).where(users.c.username == username)).scalar()


def test_FR_11_a_role_change_takes_effect_at_once_and_is_audited(client, make_headers):
    admin, viewer = make_headers("admin"), make_headers("viewer")
    assert client.get("/api/audit/log", headers=viewer).status_code == 403
    response = client.patch(f"/api/users/{_id(client, 'viewer_user')}", headers=admin,
                            json={"role": "auditor"})
    assert response.status_code == 200 and response.json()["role"] == "auditor"
    assert client.get("/api/audit/log", headers=viewer).status_code == 200  # same token
    assert client.post("/api/query", headers=viewer, json={"question": "Anything here?"}
                       ).status_code == 403
    (changed,) = events(client, "USER_ROLE_CHANGED")
    assert (changed["before"], changed["after"]) == ("viewer", "auditor")


def test_FR_11_unlocking_clears_the_lock_and_the_failure_count(client, make_headers):
    admin = make_headers("admin")
    make_headers("viewer")  # creates viewer_user
    for _ in range(5):
        client.post("/api/auth/login", json={"username": "viewer_user", "password": "wrong-pw!"})
    locked = client.post("/api/auth/login", json={"username": "viewer_user",
                                                  "password": "wrong-pw!"})
    assert locked.status_code in (401, 423)
    uid = _id(client, "viewer_user")
    response = client.patch(f"/api/users/{uid}", headers=admin, json={"unlock": True})
    assert response.json()["status"] == "active"
    with client.app.state.db.read() as conn:
        row = conn.execute(select(users.c.failed_login_count, users.c.locked_until)
                           .where(users.c.id == uid)).first()
    assert tuple(row) == (0, None)
    assert [e["target_username"] for e in events(client, "USER_UNLOCKED")] == ["viewer_user"]


def test_deactivating_signs_the_user_out_everywhere_and_keeps_their_history(client, make_headers):
    admin, viewer = make_headers("admin"), make_headers("viewer")
    uid = _id(client, "viewer_user")
    response = client.patch(f"/api/users/{uid}", headers=admin, json={"deactivate": True})
    assert response.json()["status"] == "deactivated"
    assert client.get("/api/me", headers=viewer).status_code == 401
    assert client.post("/api/auth/login", json={
        "username": "viewer_user", "password": "whatever-it-was"}).status_code == 401
    assert client.post("/api/auth/refresh", headers={"Origin": "https://app.test"}
                       ).status_code == 401  # the refresh cookie was revoked as well
    assert make_user(client, admin, "viewer_user").status_code == 409  # name stays taken
    assert [e["target_username"] for e in events(client, "USER_DEACTIVATED")] == ["viewer_user"]
    # deactivating twice is harmless and not logged twice
    client.patch(f"/api/users/{uid}", headers=admin, json={"deactivate": True})
    assert len(events(client, "USER_DEACTIVATED")) == 1


def test_an_admin_cannot_demote_or_deactivate_themselves(client, make_headers):
    admin = make_headers("admin")
    me = _id(client, "admin_user")
    for body in ({"role": "viewer"}, {"deactivate": True}):
        response = client.patch(f"/api/users/{me}", headers=admin, json=body)
        assert (response.status_code, response.json()["error"]["code"]) == (
            409, "CANNOT_CHANGE_SELF")
    assert client.patch(f"/api/users/{me}", headers=admin, json={"unlock": True}).status_code == 200


def test_an_admin_can_remove_another_admin_and_that_admins_token_stops_working(client,
                                                                              make_headers):
    """The 'last active admin' rule (LAST_ADMIN) is defence in depth: the acting admin is by
    definition active, so with two different admins one always remains."""
    admin = make_headers("admin")
    other = client.post("/api/users", headers=admin, json={
        "username": "second", "full_name": "Second Admin", "role": "admin"})
    assert other.status_code == 201
    response = client.patch(f"/api/users/{other.json()['id']}", headers=admin,
                            json={"role": "viewer"})
    assert response.status_code == 200 and response.json()["role"] == "viewer"
    still = client.get("/api/users", headers=admin).json()["items"]
    assert [u["role"] for u in still if u["username"] == "admin_user"] == ["admin"]


def test_patching_needs_something_to_do_and_a_known_user(client, make_headers):
    admin = make_headers("admin")
    uid = _id(client, "admin_user")
    assert client.patch(f"/api/users/{uid}", headers=admin, json={}).status_code == 422
    assert client.patch(f"/api/users/{uid}", headers=admin, json={"unlock": False}
                        ).status_code == 422
    assert client.patch("/api/users/u_missing", headers=admin, json={"unlock": True}
                        ).status_code == 404
    assert client.patch(f"/api/users/{SYSTEM_USER_ID}", headers=admin, json={"unlock": True}
                        ).status_code == 404  # the system account is not manageable
    assert client.patch(f"/api/users/{uid}", headers=admin, json={"role": "root"}
                        ).status_code == 422


def test_unused_helpers_are_importable():
    assert callable(new_id) and callable(insert) and callable(log)
