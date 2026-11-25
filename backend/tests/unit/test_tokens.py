"""Access and refresh tokens (PROJECT_SPEC §13.1; SEC-06)."""

import base64
import datetime as dt
import json

import jwt
import pytest
from sqlalchemy import insert, select

from auth.tokens import (
    TokenError,
    create_access_token,
    decode_access_token,
    fmt_ts,
    parse_ts,
    revoke_all_sessions,
    revoke_session,
    rotate,
    start_session,
    token_jti,
)
from database.init_db import SYSTEM_USER_ID
from database.models import refresh_tokens

SECRET = "s" * 64
NOW = dt.datetime(2026, 11, 25, 10, 0, 0, tzinfo=dt.UTC)


def minutes(n):
    return dt.timedelta(minutes=n)


# ── access tokens ────────────────────────────────────────────────────────────────────────

def test_an_access_token_carries_the_spec_claims_and_expires_in_15_minutes():
    claims = decode_access_token(create_access_token("u_1", "qa_user", SECRET, 15), SECRET)
    assert set(claims) == {"sub", "role", "iat", "exp", "jti"}
    assert claims["sub"] == "u_1" and claims["role"] == "qa_user"
    assert claims["exp"] - claims["iat"] == 15 * 60


def test_each_token_has_its_own_jti():
    jtis = {decode_access_token(create_access_token("u", "viewer", SECRET, 15), SECRET)["jti"]
            for _ in range(50)}
    assert len(jtis) == 50


def test_SEC_06_an_expired_access_token_is_rejected():
    sixteen_minutes_ago = dt.datetime.now(dt.UTC) - minutes(16)
    old = create_access_token("u_1", "viewer", SECRET, 15, now=sixteen_minutes_ago)
    with pytest.raises(TokenError) as err:
        decode_access_token(old, SECRET)
    assert err.value.code == "TOKEN_EXPIRED"


def test_a_token_signed_with_another_key_is_rejected():
    forged = create_access_token("u_1", "admin", "another-secret-" + "x" * 30, 15)
    with pytest.raises(TokenError) as err:
        decode_access_token(forged, SECRET)
    assert err.value.code == "INVALID_TOKEN"


def test_a_payload_edited_after_signing_is_rejected():
    head, payload, signature = create_access_token("u_1", "viewer", SECRET, 15).split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
    claims["role"] = "admin"  # privilege escalation attempt
    edited = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    with pytest.raises(TokenError):
        decode_access_token(f"{head}.{edited}.{signature}", SECRET)


def test_alg_none_and_other_algorithms_are_rejected():
    claims = {"sub": "u_1", "role": "admin", "jti": "x", "iat": NOW, "exp": NOW + minutes(900000)}
    for token in (jwt.encode(claims, key=None, algorithm="none"),
                  jwt.encode(claims, SECRET, algorithm="HS512")):
        with pytest.raises(TokenError):
            decode_access_token(token, SECRET)


@pytest.mark.parametrize("missing", ["exp", "iat", "sub", "jti"])
def test_a_token_missing_a_required_claim_is_rejected(missing):
    claims = {"sub": "u_1", "jti": "x", "iat": NOW, "exp": NOW + minutes(10_000_000)}
    del claims[missing]
    with pytest.raises(TokenError):
        decode_access_token(jwt.encode(claims, SECRET, algorithm="HS256"), SECRET)


def test_garbage_is_rejected():
    for junk in ("", "abc", "a.b.c", "Bearer x"):
        with pytest.raises(TokenError):
            decode_access_token(junk, SECRET)


# ── timestamps ───────────────────────────────────────────────────────────────────────────

def test_timestamps_round_trip():
    assert parse_ts(fmt_ts(NOW)) == NOW and fmt_ts(NOW) == "2026-11-25T10:00:00.000000Z"


# ── refresh tokens ───────────────────────────────────────────────────────────────────────

def rows(db):
    with db.read() as conn:
        return conn.execute(select(refresh_tokens).order_by(refresh_tokens.c.issued_at)
                            ).mappings().all()


def new_session(db, now=NOW):
    with db.write() as conn:
        return start_session(conn, SYSTEM_USER_ID, absolute_hours=8, now=now)


def do_rotate(db, token, now, idle=30):
    with db.write() as conn:
        return rotate(conn, token, idle, now)


def test_the_database_stores_a_hash_of_the_refresh_token_not_the_token(db):
    session = new_session(db)
    (row,) = rows(db)
    assert session.token not in json.dumps(dict(row)) and row["jti"] == token_jti(session.token)
    assert len(session.token) >= 43  # 256 bits, url-safe base64
    assert session.expires_at == NOW + dt.timedelta(hours=8)


def test_rotation_revokes_the_old_token_and_issues_a_new_one_in_the_same_family(db):
    first = new_session(db)
    result = do_rotate(db, first.token, NOW + minutes(5))
    assert result.status == "ok" and result.session.token != first.token
    old, new = rows(db)
    assert (old["revoked"], new["revoked"]) == (1, 0) and old["family_id"] == new["family_id"]
    assert result.session.expires_at == first.expires_at  # the 8 h limit does not move


def test_SEC_06_the_absolute_limit_is_8_hours_from_the_first_login(db):
    token = new_session(db).token
    for step in range(1, 20):  # keep refreshing every 29 minutes (never idle)...
        result = do_rotate(db, token, NOW + minutes(29 * step))
        if result.status != "ok":
            break
        token = result.session.token
    assert result.status == "expired" and step == 17  # ...it still ends at 8 h (17 × 29 = 493 min)


def test_SEC_06_30_minutes_of_idleness_ends_the_session(db):
    token = new_session(db).token
    assert do_rotate(db, token, NOW + minutes(29)).status == "ok"
    idle_token = new_session(db, NOW).token
    assert do_rotate(db, idle_token, NOW + minutes(30)).status == "idle"
    assert do_rotate(db, idle_token, NOW + minutes(31)).status == "reuse"  # and it is dead


def test_using_a_rotated_token_again_revokes_the_whole_family(db):
    first = new_session(db)
    second = do_rotate(db, first.token, NOW + minutes(1)).session
    third = do_rotate(db, second.token, NOW + minutes(2)).session
    replay = do_rotate(db, first.token, NOW + minutes(3))  # the thief uses the old token
    assert replay.status == "reuse" and replay.user_id == SYSTEM_USER_ID and replay.family_id
    assert all(r["revoked"] for r in rows(db))  # the thief AND the victim are signed out
    assert do_rotate(db, third.token, NOW + minutes(4)).status == "reuse"


def test_an_unknown_token_is_invalid_and_changes_nothing(db):
    new_session(db)
    assert do_rotate(db, "not-a-token", NOW).status == "invalid"
    assert [r["revoked"] for r in rows(db)] == [0]


def test_other_families_are_untouched_by_a_reuse(db):
    mine, other = new_session(db), new_session(db)
    do_rotate(db, mine.token, NOW + minutes(1))
    do_rotate(db, mine.token, NOW + minutes(2))  # reuse of mine
    assert do_rotate(db, other.token, NOW + minutes(3)).status == "ok"


def test_logout_revokes_the_family_and_reports_the_user(db):
    session = new_session(db)
    with db.write() as conn:
        assert revoke_session(conn, session.token) == SYSTEM_USER_ID
        assert revoke_session(conn, "unknown") is None
    assert do_rotate(db, session.token, NOW + minutes(1)).status == "reuse"


def test_revoking_all_sessions_of_a_user_ends_every_family(db):
    a, b = new_session(db), new_session(db)
    with db.write() as conn:
        revoke_all_sessions(conn, SYSTEM_USER_ID)
    assert do_rotate(db, a.token, NOW + minutes(1)).status == "reuse"
    assert do_rotate(db, b.token, NOW + minutes(1)).status == "reuse"


def test_a_refresh_token_of_a_missing_user_cannot_be_created(db):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError), db.write() as conn:
        conn.execute(insert(refresh_tokens).values(
            jti="j", user_id="u_nobody", family_id="f", issued_at="x", expires_at="y",
            last_used_at="z", revoked=0))
