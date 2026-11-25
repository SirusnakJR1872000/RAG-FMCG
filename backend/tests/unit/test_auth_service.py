"""Login, lockout, sessions and password changes against a real database (SEC-03..SEC-06)."""

import datetime as dt

import pytest
from argon2 import PasswordHasher
from sqlalchemy import select, update

from audit.chain import verify
from audit.writer import Actor
from auth import passwords, service
from auth.service import RequestInfo
from config import Settings
from database.models import audit_log, password_history, users

SETTINGS = Settings(_env_file=None, jwt_secret_key="x" * 64)
NOW = dt.datetime(2026, 11, 25, 10, 0, 0, tzinfo=dt.UTC)
INFO = RequestInfo("10.0.0.7", "req_t1")
PASSWORD = "violet-lantern-orbit-42"


@pytest.fixture(autouse=True)
def fast_hasher():
    passwords.configure_hasher(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
    yield
    passwords.configure_hasher(PasswordHasher())


def minutes(n):
    return dt.timedelta(minutes=n)


@pytest.fixture
def admin(db):
    """The administrator who creates accounts (a real row: audit events must point at one)."""
    with db.write() as conn:
        row = service.create_user(conn, username="root", full_name="Root", role="admin",
                                  password=PASSWORD, created_by=None,
                                  actor=Actor(None, "bootstrap"), now=NOW)
    return Actor(row["id"], "root", "admin")


@pytest.fixture
def user(db, admin):
    """gpatil, a qa_user whose temporary password has already been replaced."""
    with db.write() as conn:
        created = service.create_user(conn, username="GPatil", full_name="G Patil", role="qa_user",
                                      password=PASSWORD, created_by=None, actor=admin, now=NOW)
        conn.execute(update(users).where(users.c.id == created["id"]).values(
            must_change_password=0))
    return created


def attempt(db, username="gpatil", password=PASSWORD, now=NOW):
    with db.write() as conn:
        return service.login(conn, SETTINGS, username, password, INFO, now)


def events(db, event_type=None):
    with db.read() as conn:
        query = select(audit_log).order_by(audit_log.c.seq)
        if event_type:
            query = query.where(audit_log.c.event_type == event_type)
        return conn.execute(query).mappings().all()


def fresh(db, user_id):
    with db.read() as conn:
        return service.get_user(conn, user_id)


# ── user creation ────────────────────────────────────────────────────────────────────────

def test_a_new_user_has_a_hashed_temporary_password_that_must_be_changed(db, admin):
    with db.write() as conn:
        created = service.create_user(conn, username=" New.User ", full_name=" A B ",
                                      role="viewer", password="temp-password", created_by=None,
                                      actor=admin, now=NOW)
    assert created["username"] == "new.user" and created["full_name"] == "A B"
    assert created["password_hash"].startswith("$argon2id$")
    assert created["must_change_password"] == 1
    with db.read() as conn:
        owners = {r[0] for r in conn.execute(select(password_history.c.user_id))}
    assert created["id"] in owners
    event = events(db, "USER_CREATED")[-1]
    assert event["username"] == "root" and '"target_username":"new.user"' in event["payload_json"]


def test_usernames_are_never_reused_even_after_deactivation(db, user, admin):
    from sqlalchemy.exc import IntegrityError

    with db.write() as conn:
        conn.execute(update(users).where(users.c.id == user["id"]).values(is_active=0))
    with pytest.raises(IntegrityError), db.write() as conn:
        service.create_user(conn, username="gpatil", full_name="Other", role="viewer",
                            password="x", created_by=None, actor=admin)


def test_the_system_role_cannot_be_given_to_a_person(db, admin):
    with pytest.raises(ValueError), db.write() as conn:
        service.create_user(conn, username="x", full_name="x", role="system", password="x",
                            created_by=None, actor=admin)


def test_temporary_passwords_are_long_and_different_every_time():
    pws = {service.generate_temporary_password() for _ in range(20)}
    assert len(pws) == 20 and all(len(p) >= 16 for p in pws)


# ── login ────────────────────────────────────────────────────────────────────────────────

def test_a_correct_login_opens_a_session_and_is_audited_with_the_user(db, user):
    result = attempt(db, "  GPATIL  ")  # case and spaces do not matter
    assert result.status == "ok" and result.user["id"] == user["id"]
    assert not result.must_change_password and result.session.token
    assert result.session.expires_at == NOW + dt.timedelta(hours=8)
    (event,) = events(db, "LOGIN_SUCCESS")
    assert (event["user_id"], event["username"], event["role"], event["client_ip"],
            event["request_id"]) == (user["id"], "gpatil", "qa_user", "10.0.0.7", "req_t1")


def test_a_wrong_password_and_an_unknown_user_look_the_same_to_the_caller(db, user):
    wrong, unknown = attempt(db, password="nope"), attempt(db, username="ghost")
    assert (wrong.status, unknown.status) == ("invalid", "invalid")
    assert wrong.session is None and unknown.session is None
    rows = events(db, "LOGIN_FAILED")
    assert [r["user_id"] for r in rows] == [user["id"], None]  # unknown: no user id (§12)
    assert '"reason":"wrong_password"' in rows[0]["payload_json"]
    assert '"reason":"unknown_user"' in rows[1]["payload_json"]


def test_an_unknown_user_still_costs_one_password_verification(db, monkeypatch):
    """§13.2: no timing difference between unknown user and wrong password."""
    calls = []
    monkeypatch.setattr(passwords, "dummy_verify", lambda pw: calls.append(pw))
    attempt(db, username="ghost", password="whatever")
    assert calls == ["whatever"]


def test_SEC_04_five_failures_lock_the_account_for_30_minutes(db, user):
    statuses = [attempt(db, password="bad", now=NOW + minutes(i)).status for i in range(5)]
    assert statuses == ["invalid"] * 4 + ["locked"]  # the 5th attempt locks it
    assert len(events(db, "ACCOUNT_LOCKED")) == 1
    # the right password does not help while it is locked, and is not even checked
    assert attempt(db, now=NOW + minutes(10)).status == "locked"
    assert attempt(db, now=NOW + minutes(33)).status == "locked"  # 30 min run from the 5th (+4)
    assert attempt(db, now=NOW + minutes(35)).status == "ok"
    row = fresh(db, user["id"])
    assert (row["failed_login_count"], row["locked_until"]) == (0, None)


def test_a_success_before_the_limit_resets_the_counter(db, user):
    for i in range(4):
        attempt(db, password="bad", now=NOW + minutes(i))
    assert attempt(db, now=NOW + minutes(5)).status == "ok"
    assert fresh(db, user["id"])["failed_login_count"] == 0
    assert [attempt(db, password="bad", now=NOW + minutes(10 + i)).status for i in range(4)] \
        == ["invalid"] * 4  # not locked: it started again from zero


def test_after_a_lock_expires_the_count_starts_again(db, user):
    for i in range(5):
        attempt(db, password="bad", now=NOW + minutes(i))
    assert attempt(db, password="bad", now=NOW + minutes(40)).status == "invalid"  # not locked
    assert fresh(db, user["id"])["failed_login_count"] == 1


def test_a_deactivated_account_looks_like_a_wrong_password(db, user):
    with db.write() as conn:
        conn.execute(update(users).where(users.c.id == user["id"]).values(is_active=0))
    result = attempt(db)  # even with the right password
    assert result.status == "invalid" and result.session is None
    assert '"reason":"inactive"' in events(db, "LOGIN_FAILED")[-1]["payload_json"]


def test_the_system_account_can_never_log_in(db):
    assert attempt(db, username="system", password="!").status == "invalid"


def test_the_first_login_with_a_temporary_password_demands_a_change(db, admin):
    with db.write() as conn:
        service.create_user(conn, username="newbie", full_name="N", role="viewer",
                            password="temp-password-1", created_by=None, actor=admin, now=NOW)
    assert attempt(db, "newbie", "temp-password-1").must_change_password is True


def test_SEC_05_an_expired_password_demands_a_change(db, user):
    assert attempt(db, now=NOW + dt.timedelta(days=89)).must_change_password is False
    assert attempt(db, now=NOW + dt.timedelta(days=90)).must_change_password is True


def test_a_hash_with_old_parameters_is_upgraded_at_login(db, user):
    old = PasswordHasher(time_cost=1, memory_cost=512, parallelism=1).hash(PASSWORD)
    with db.write() as conn:
        conn.execute(update(users).where(users.c.id == user["id"]).values(password_hash=old))
    assert attempt(db).status == "ok"
    assert fresh(db, user["id"])["password_hash"] != old
    assert attempt(db).status == "ok"  # and the new hash works


# ── refresh and logout ───────────────────────────────────────────────────────────────────

def test_refresh_rotates_the_token_and_reuse_is_audited(db, user):
    first = attempt(db).session

    def refresh(token, now):
        with db.write() as conn:
            return service.refresh(conn, SETTINGS, token, INFO, now)

    second = refresh(first.token, NOW + minutes(5))
    assert second.status == "ok" and second.user["id"] == user["id"]
    assert refresh(first.token, NOW + minutes(6)).status == "reuse"  # the old token again
    (event,) = events(db, "REFRESH_REUSE_DETECTED")
    assert (event["user_id"], event["username"]) == (user["id"], "gpatil")
    assert refresh(second.session.token, NOW + minutes(7)).status == "reuse"  # family is dead


def test_refresh_refuses_a_user_who_was_deactivated_meanwhile(db, user):
    token = attempt(db).session.token
    with db.write() as conn:
        conn.execute(update(users).where(users.c.id == user["id"]).values(is_active=0))
        assert service.refresh(conn, SETTINGS, token, INFO, NOW + minutes(1)).status == "invalid"
        assert service.refresh(conn, SETTINGS, token, INFO, NOW + minutes(2)).status == "reuse"


def test_refresh_with_an_unknown_token_is_invalid(db):
    with db.write() as conn:
        assert service.refresh(conn, SETTINGS, "junk", INFO, NOW).status == "invalid"


def test_logout_ends_the_session_and_is_audited(db, user):
    token = attempt(db).session.token
    with db.write() as conn:
        assert service.logout(conn, token, INFO) is True
        assert service.logout(conn, "unknown-token", INFO) is False  # no event for a stranger
        assert service.refresh(conn, SETTINGS, token, INFO, NOW + minutes(1)).status == "reuse"
    assert len(events(db, "LOGOUT")) == 1


# ── changing the password ────────────────────────────────────────────────────────────────

def change(db, user_id, current=PASSWORD, new="orbit-lantern-violet-77", now=NOW):
    with db.write() as conn:
        return service.change_password(conn, SETTINGS, service.get_user(conn, user_id), current,
                                       new, INFO, now)


def test_a_password_change_replaces_the_hash_and_signs_out_every_device(db, user):
    old_session = attempt(db).session
    result = change(db, user["id"], now=NOW + minutes(1))
    assert result.status == "ok" and result.session.token != old_session.token
    row = fresh(db, user["id"])
    assert passwords.verify_password(row["password_hash"], "orbit-lantern-violet-77")
    assert row["must_change_password"] == 0
    assert row["password_changed_at"].startswith("2026-11-25T10:01")

    def refresh(token, minutes_later):
        with db.write() as conn:
            return service.refresh(conn, SETTINGS, token, INFO, NOW + minutes(minutes_later)).status

    assert refresh(old_session.token, 2) == "reuse"  # the other device is signed out
    assert refresh(result.session.token, 3) == "ok"  # this one continues
    assert attempt(db, password=PASSWORD, now=NOW + minutes(4)).status == "invalid"
    assert attempt(db, password="orbit-lantern-violet-77", now=NOW + minutes(4)).status == "ok"


def test_the_audit_event_says_forced_or_voluntary_and_never_the_password(db, user):
    change(db, user["id"])
    with db.write() as conn:
        conn.execute(update(users).where(users.c.id == user["id"]).values(must_change_password=1))
    change(db, user["id"], current="orbit-lantern-violet-77", new="a-completely-new-one-99")
    payloads = [r["payload_json"] for r in events(db, "PASSWORD_CHANGED")]
    assert payloads == ['{"kind":"voluntary"}', '{"kind":"forced"}']
    assert all("orbit" not in p and "argon" not in p for p in payloads)


def test_SEC_05_the_policy_is_enforced_and_every_broken_rule_is_returned(db, user):
    assert change(db, user["id"], new="short").violations == ["TOO_SHORT"]
    assert change(db, user["id"], new="Password1234").violations == ["COMMON"]
    assert change(db, user["id"], new=PASSWORD).violations == ["REUSED"]  # same as the current one
    assert fresh(db, user["id"])["must_change_password"] == 0  # nothing changed


def test_SEC_05_the_last_five_passwords_cannot_come_back_but_the_sixth_back_can(db, user):
    sequence = [PASSWORD, *(f"violet-lantern-orbit-{n}" for n in range(51, 57))]
    for current, new in zip(sequence, sequence[1:], strict=False):
        assert change(db, user["id"], current, new).status == "ok"
    # history now holds 7 passwords; the last 5 are blocked, the oldest two are not
    assert change(db, user["id"], sequence[-1], sequence[-2]).violations == ["REUSED"]
    assert change(db, user["id"], sequence[-1], sequence[2]).violations == ["REUSED"]
    assert change(db, user["id"], sequence[-1], sequence[1]).status == "ok"


def test_a_wrong_current_password_counts_towards_the_lockout(db, user):
    statuses = [change(db, user["id"], current="bad").status for _ in range(5)]
    assert statuses == ["wrong_current"] * 4 + ["locked"]
    assert len(events(db, "ACCOUNT_LOCKED")) == 1
    assert '"reason":"wrong_current_password"' in events(db, "LOGIN_FAILED")[0]["payload_json"]


def test_the_chain_is_intact_after_all_of_this(db, user):
    attempt(db, password="bad")
    attempt(db)
    change(db, user["id"])
    with db.read() as conn:
        assert verify(conn).ok
