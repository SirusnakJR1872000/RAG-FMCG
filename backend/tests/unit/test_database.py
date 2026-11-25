"""Schema, transactions and the rules the database enforces itself (PROJECT_SPEC §12)."""

import sqlite3

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.exc import IntegrityError

from audit.writer import log
from database.init_db import NO_LOGIN_HASH, SYSTEM_USER_ID, init_db, new_id, utc_now
from database.models import audit_log, documents, feedback, users


def add_user(conn, username="gpatil", role="viewer", **extra):
    values = {"id": new_id("u"), "username": username, "full_name": "G Patil",
              "password_hash": "x", "role": role, "password_changed_at": utc_now(),
              "created_at": utc_now(), **extra}
    conn.execute(insert(users).values(**values))
    return values["id"]


def test_wal_mode_and_foreign_keys_are_on(db):
    with db.read() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_init_db_creates_the_system_account_once(db):
    init_db(db)  # idempotent
    with db.read() as conn:
        rows = conn.execute(select(users).where(users.c.id == SYSTEM_USER_ID)).mappings().all()
    assert len(rows) == 1
    system = rows[0]
    assert (system["username"], system["role"], system["can_login"]) == ("system", "system", 0)
    assert system["password_hash"] == NO_LOGIN_HASH  # can never match any password


def test_write_commits_and_a_failed_write_rolls_back(db):
    with db.write() as conn:
        add_user(conn, "committed")
    with pytest.raises(RuntimeError), db.write() as conn:
        add_user(conn, "rolled_back")
        raise RuntimeError("boom")
    with db.read() as conn:
        names = {r[0] for r in conn.execute(select(users.c.username))}
    assert "committed" in names and "rolled_back" not in names


def test_a_write_transaction_takes_the_write_lock_immediately(db):
    """BEGIN IMMEDIATE (§14.3): another writer is refused while this one is open."""
    with db.write():
        other = sqlite3.connect(db.path, timeout=0.2, isolation_level=None)
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            other.execute("BEGIN IMMEDIATE")
        other.close()
    other = sqlite3.connect(db.path, timeout=0.2, isolation_level=None)
    other.execute("BEGIN IMMEDIATE")  # free again after commit
    other.execute("ROLLBACK")
    other.close()


def test_the_write_flag_does_not_leak_into_later_read_connections(db):
    with db.write() as conn:
        assert conn.info["write"] is True
    with db.read() as conn:
        assert not conn.info.get("write")


def test_usernames_are_unique_and_roles_are_checked(db):
    with db.write() as conn:
        add_user(conn, "dup")
    with pytest.raises(IntegrityError), db.write() as conn:
        add_user(conn, "dup")
    with pytest.raises(IntegrityError), db.write() as conn:
        add_user(conn, "bad_role", role="superuser")


def test_only_one_active_version_per_document_code(db):
    def doc(conn, version, status):
        conn.execute(insert(documents).values(
            id=new_id("d"), doc_code="ICH-Q7", title="t", version=version, file_path="f",
            sha256="ab" * 32, chunk_count=3, status=status, ingested_at=utc_now(),
            ingested_by=SYSTEM_USER_ID))

    with db.write() as conn:
        doc(conn, "1", "superseded")
        doc(conn, "2", "superseded")  # many superseded versions are fine
        doc(conn, "3", "active")
    with pytest.raises(IntegrityError), db.write() as conn:
        doc(conn, "4", "active")  # a second active one is not


def test_foreign_keys_are_enforced(db):
    with pytest.raises(IntegrityError), db.write() as conn:
        conn.execute(insert(feedback).values(
            id="f1", query_event_id="evt_missing", user_id="u_missing", rating=1,
            created_at=utc_now()))


def test_feedback_rating_and_comment_length_are_checked(db, actor):
    with db.write() as conn:
        uid = add_user(conn)
        event = log(conn, "QUERY", actor)

    def put(rating, comment=None):
        with db.write() as conn:
            conn.execute(insert(feedback).values(
                id=new_id("f"), query_event_id=event.event_id, user_id=uid, rating=rating,
                comment=comment, created_at=utc_now()))

    with pytest.raises(IntegrityError):
        put(0)
    with pytest.raises(IntegrityError):
        put(1, "x" * 1001)
    put(-1, "x" * 1000)  # exactly at the limit is allowed


@pytest.mark.parametrize("statement", [
    "UPDATE audit_log SET username = 'someone else'",
    "DELETE FROM audit_log",
])
def test_AUD_02_audit_rows_cannot_be_updated_or_deleted(db, actor, statement):
    with db.write() as conn:
        log(conn, "QUERY", actor)
    with pytest.raises(Exception, match="append-only"), db.write() as conn:
        conn.execute(text(statement))
    with db.read() as conn:
        assert conn.execute(select(audit_log.c.username)).scalar() == "tester"


def test_ids_have_a_prefix_and_are_unique():
    ids = {new_id("u") for _ in range(1000)}
    assert len(ids) == 1000 and all(i.startswith("u_") for i in ids)
    assert utc_now().endswith("Z") and "." in utc_now()
