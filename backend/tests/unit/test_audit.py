"""The audit trail: writing, hash chain, verification, filters (PROJECT_SPEC §14; AUD-01..05)."""

import json
import sqlite3
import threading

import pytest
from sqlalchemy import select

from audit.chain import GENESIS_HASH, canonical, dump_json, row_hash, verify
from audit.export import LogFilter, export_events, list_events, summary
from audit.writer import EVENT_TYPES, FAILURE_EVENTS, Actor, log
from database.models import audit_log


def emit(db, actor, n=1, event_type="QUERY", **payload):
    with db.write() as conn:
        return [log(conn, event_type, actor, {"original_question": f"question {i}", **payload})
                for i in range(n)]


def tamper(db, sql, *args):
    """What an attacker with file access can do: bypass the triggers by editing the file."""
    raw = sqlite3.connect(db.path, isolation_level=None)
    raw.execute("DROP TRIGGER audit_no_update")
    raw.execute("DROP TRIGGER audit_no_delete")
    raw.execute(sql, args)
    raw.close()


def verify_now(db, from_seq=1):
    with db.read() as conn:
        return verify(conn, from_seq)


# ── writing ──────────────────────────────────────────────────────────────────────────────

def test_the_chain_starts_at_genesis_and_every_row_links_to_the_previous(db, actor):
    entries = emit(db, actor, 3)
    with db.read() as conn:
        rows = conn.execute(select(audit_log).order_by(audit_log.c.seq)).mappings().all()
    assert [r["seq"] for r in rows] == [1, 2, 3]
    assert rows[0]["prev_hash"] == GENESIS_HASH
    assert rows[1]["prev_hash"] == rows[0]["row_hash"]
    assert rows[2]["prev_hash"] == rows[1]["row_hash"]
    assert [e.seq for e in entries] == [1, 2, 3] and entries[2].row_hash == rows[2]["row_hash"]


def test_AUD_01_an_event_records_who_when_from_where_and_in_which_request(db, actor):
    emit(db, actor)
    with db.read() as conn:
        row = conn.execute(select(audit_log)).mappings().one()
    assert (row["username"], row["role"], row["client_ip"], row["request_id"]) == (
        "tester", "admin", "10.0.0.5", "req_abc123")
    assert row["event_id"].startswith("evt_") and row["timestamp_utc"].endswith("Z")
    assert json.loads(row["payload_json"]) == {"original_question": "question 0"}


def test_an_unknown_event_type_is_refused(db, actor):
    with pytest.raises(ValueError, match="unknown audit event type"), db.write() as conn:
        log(conn, "QUERRY", actor)


def test_logging_outside_a_write_transaction_is_refused(db, actor):
    with db.read() as conn, pytest.raises(RuntimeError, match="db.write"):
        log(conn, "QUERY", actor)


def test_every_catalogue_event_can_be_written(db, actor):
    with db.write() as conn:
        for event_type in sorted(EVENT_TYPES):
            log(conn, event_type, actor)
    assert verify_now(db).checked == len(EVENT_TYPES)
    assert FAILURE_EVENTS < EVENT_TYPES


def test_unknown_username_login_attempts_have_no_user_id(db):
    with db.write() as conn:
        log(conn, "LOGIN_FAILED", Actor(None, "nobody"), {"reason": "unknown_user"})
    assert verify_now(db).ok


def test_a_rolled_back_event_leaves_no_hole_in_the_chain(db, actor):
    emit(db, actor)
    with pytest.raises(RuntimeError), db.write() as conn:
        log(conn, "QUERY", actor)
        raise RuntimeError("the request failed after the audit write")
    emit(db, actor)
    with db.read() as conn:
        assert [r[0] for r in conn.execute(select(audit_log.c.seq).order_by("seq"))] == [1, 2]
    assert verify_now(db).ok


def test_concurrent_writers_never_fork_the_chain(db, actor):
    def writer():
        for _ in range(10):
            emit(db, actor)

    threads = [threading.Thread(target=writer) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with db.read() as conn:
        seqs = [r[0] for r in conn.execute(select(audit_log.c.seq).order_by("seq"))]
    assert seqs == list(range(1, 41))
    assert verify_now(db) == verify_now(db) and verify_now(db).ok


# ── hashing ──────────────────────────────────────────────────────────────────────────────

ENTRY = {"seq": 1, "event_id": "evt_1", "timestamp_utc": "2026-11-25T10:00:00.000000Z",
         "event_type": "QUERY", "user_id": "u_1", "username": "gpatil", "role": "qa_user",
         "client_ip": "10.0.0.1", "request_id": "req_1", "payload": {"b": 1, "a": "é"}}


def test_the_canonical_form_is_exactly_the_spec_14_3_definition():
    expected = ('{"client_ip":"10.0.0.1","event_id":"evt_1","event_type":"QUERY","payload":'
                '{"a":"é","b":1},"request_id":"req_1","role":"qa_user","seq":1,'
                '"timestamp_utc":"2026-11-25T10:00:00.000000Z","user_id":"u_1",'
                '"username":"gpatil"}')
    assert canonical(ENTRY) == expected.encode("utf-8")  # sorted keys, no spaces, UTF-8 not é


def test_the_hash_depends_on_the_previous_hash_and_on_every_field():
    base = row_hash(GENESIS_HASH, ENTRY)
    assert len(base) == 64 and base == row_hash(GENESIS_HASH, dict(reversed(ENTRY.items())))
    assert row_hash("1" * 64, ENTRY) != base
    for field, value in [("username", "other"), ("seq", 2), ("client_ip", "10.9.9.9"),
                         ("payload", {"a": "é", "b": 2}), ("role", "admin")]:
        assert row_hash(GENESIS_HASH, {**ENTRY, field: value}) != base, field


def test_payload_is_stored_in_the_same_form_that_is_hashed():
    assert dump_json({"b": 1, "a": "é"}) == '{"a":"é","b":1}'


# ── verification ─────────────────────────────────────────────────────────────────────────

def test_an_empty_and_an_untouched_chain_verify(db, actor):
    assert verify_now(db).as_dict() == {"ok": True, "checked": 0, "first_bad_seq": None,
                                        "reason": None}
    emit(db, actor, 5)
    assert (verify_now(db).ok, verify_now(db).checked) == (True, 5)


def test_a_range_can_be_verified_from_the_middle(db, actor):
    emit(db, actor, 5)
    assert (verify_now(db, from_seq=3).ok, verify_now(db, from_seq=3).checked) == (True, 3)
    assert not verify_now(db, from_seq=99).ok  # the row before the range is missing


def test_AUD_03_editing_a_row_is_detected_at_that_seq(db, actor):
    emit(db, actor, 5)
    tamper(db, "UPDATE audit_log SET payload_json = ? WHERE seq = 3",
           '{"original_question":"a different question"}')
    result = verify_now(db)
    assert (result.ok, result.first_bad_seq, result.checked) == (False, 3, 2)
    assert "does not match its hash" in result.reason


FORGERIES = {  # fixed statements: one per field an attacker might want to change
    "username": "UPDATE audit_log SET username = 'forged' WHERE seq = 2",
    "role": "UPDATE audit_log SET role = 'forged' WHERE seq = 2",
    "client_ip": "UPDATE audit_log SET client_ip = 'forged' WHERE seq = 2",
    "event_type": "UPDATE audit_log SET event_type = 'forged' WHERE seq = 2",
    "timestamp_utc": "UPDATE audit_log SET timestamp_utc = 'forged' WHERE seq = 2",
}


@pytest.mark.parametrize("column", sorted(FORGERIES))
def test_editing_any_attributable_field_is_detected(db, actor, column):
    emit(db, actor, 3)
    tamper(db, FORGERIES[column])
    assert verify_now(db).first_bad_seq == 2


def test_deleting_a_row_in_the_middle_is_detected_as_a_gap(db, actor):
    emit(db, actor, 5)
    tamper(db, "DELETE FROM audit_log WHERE seq = 3")
    result = verify_now(db)
    assert (result.first_bad_seq, "gap" in result.reason) == (3, True)


def test_deleting_the_first_row_is_detected(db, actor):
    emit(db, actor, 3)
    tamper(db, "DELETE FROM audit_log WHERE seq = 1")
    assert verify_now(db).first_bad_seq == 1


def test_a_broken_link_is_detected_even_if_the_row_hash_is_recomputed(db, actor):
    emit(db, actor, 4)
    tamper(db, "UPDATE audit_log SET prev_hash = ? WHERE seq = 3", "f" * 64)
    result = verify_now(db)
    assert (result.first_bad_seq, "prev_hash" in result.reason) == (3, True)


def test_a_payload_that_is_not_json_is_reported(db, actor):
    emit(db, actor, 2)
    tamper(db, "UPDATE audit_log SET payload_json = 'not json' WHERE seq = 2")
    assert "not valid JSON" in verify_now(db).reason


def test_a_whole_chain_rewrite_is_the_documented_limit(db, actor):
    """§14.5: dropping the last rows leaves a valid chain — only external anchors catch it."""
    emit(db, actor, 5)
    tamper(db, "DELETE FROM audit_log WHERE seq > 3")
    assert verify_now(db).ok  # a shorter chain is still a consistent chain


# ── reading and export ───────────────────────────────────────────────────────────────────

def seed(db):
    with db.write() as conn:
        for username, event_type, payload in [
                ("anna", "LOGIN_SUCCESS", {}), ("anna", "QUERY", {"original_question": "Q?"}),
                ("bob", "LOGIN_FAILED", {"reason": "wrong_password"}),
                ("bob", "ACCESS_DENIED", {"endpoint": "/api/users", "permission": "users:manage"}),
                ("anna", "QUERY", {"original_question": "Second?"})]:
            log(conn, event_type, Actor(None, username, "viewer"), payload)


NO_FILTER = LogFilter()


def events(db, f=NO_FILTER, page=1, size=50):
    with db.read() as conn:
        return list_events(conn, f, page, size)


def test_the_log_is_listed_newest_first_with_a_total(db):
    seed(db)
    rows, total = events(db)
    assert total == 5 and [r["seq"] for r in rows] == [5, 4, 3, 2, 1]
    assert {"summary", "payload", "row_hash", "prev_hash", "client_ip"} <= set(rows[0])


def test_paging(db):
    seed(db)
    page2, total = events(db, page=2, size=2)
    assert total == 5 and [r["seq"] for r in page2] == [3, 2]
    assert events(db, page=3, size=2)[0][0]["seq"] == 1


@pytest.mark.parametrize(("flt", "seqs"), [
    (LogFilter(username="bob"), [4, 3]),
    (LogFilter(event_types=("QUERY", "LOGIN_SUCCESS")), [5, 2, 1]),
    (LogFilter(result="failure"), [4, 3]),
    (LogFilter(result="success"), [5, 2, 1]),
    (LogFilter(username="anna", event_types=("QUERY",)), [5, 2]),
])
def test_filters(db, flt, seqs):
    seed(db)
    assert [r["seq"] for r in events(db, flt)[0]] == seqs


def test_time_range_and_event_id_filters(db):
    seed(db)
    rows, _ = events(db)
    middle = rows[2]  # seq 3
    only_after = events(db, LogFilter(from_ts=middle["timestamp_utc"]))[0]
    assert [r["seq"] for r in only_after] == [5, 4, 3]
    only_before = events(db, LogFilter(to_ts=middle["timestamp_utc"]))[0]
    assert [r["seq"] for r in only_before] == [3, 2, 1]
    assert [r["seq"] for r in events(db, LogFilter(event_id=middle["event_id"]))[0]] == [3]


def test_export_is_in_chain_order_and_respects_the_filter(db):
    seed(db)
    with db.read() as conn:
        everything = export_events(conn, LogFilter())
        queries = export_events(conn, LogFilter(event_types=("QUERY",)))
    assert [r["seq"] for r in everything] == [1, 2, 3, 4, 5]
    assert [r["seq"] for r in queries] == [2, 5]
    assert everything[0]["prev_hash"] == GENESIS_HASH


@pytest.mark.parametrize(("event_type", "payload", "expected"), [
    ("QUERY", {"original_question": "When must a CAPA be raised?"},
     "Asked: When must a CAPA be raised?"),
    ("QUERY", {"original_question": "x" * 200}, "Asked: " + "x" * 80),
    ("QUERY_FAILED", {"error_code": "LLM_TIMEOUT"}, "Query failed: LLM_TIMEOUT"),
    ("LOGIN_FAILED", {"reason": "wrong_password"}, "Login failed: wrong password"),
    ("ACCESS_DENIED", {"endpoint": "/api/users", "permission": "users:manage"},
     "Access denied: /api/users needs users:manage"),
    ("PASSWORD_CHANGED", {"kind": "forced"}, "Password changed (forced)"),
    ("PASSWORD_CHANGED", {}, "Password changed (voluntary)"),
    ("FEEDBACK", {"rating": 1}, "Rated an answer 👍"),
    ("FEEDBACK", {"rating": -1}, "Rated an answer 👎"),
    ("USER_CREATED", {"target_username": "bob", "role": "viewer"}, "User created: bob (viewer)"),
    ("USER_ROLE_CHANGED", {"before": "viewer", "after": "qa_user"},
     "Role changed: viewer → qa_user"),
    ("USER_DEACTIVATED", {"target_username": "bob"}, "Deactivated: bob"),
    ("USER_UNLOCKED", {"target_username": "bob"}, "Unlocked: bob"),
    ("DOCUMENT_INGESTED", {"doc_code": "ICH-Q7", "version": "1"}, "Document ingested: ICH-Q7 1"),
    ("INDEX_ACTIVATED", {"build_id": "b1"}, "Index activated: b1"),
    ("AUDIT_VERIFIED", {"ok": True, "checked": 12}, "Integrity check: chain intact (12 records)"),
    ("AUDIT_VERIFIED", {"ok": False, "first_bad_seq": 8}, "Integrity check FAILED at record #8"),
    ("AUDIT_EXPORTED", {"row_count": 40}, "Exported 40 records"),
    ("SYSTEM_START", {}, "System start"),
    ("LOGIN_SUCCESS", {}, "Login success"),
])
def test_summaries_are_readable_one_liners(event_type, payload, expected):
    assert summary(event_type, payload) == expected
