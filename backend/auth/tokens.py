"""Access tokens (JWT) and refresh tokens (PROJECT_SPEC §13.1).

Access token: JWT HS256 with sub, role, iat, exp, jti; 15 minutes; kept in browser memory;
not revocable (its short life is the control).

Refresh token: an opaque random 256-bit value in an HttpOnly cookie. The database stores only
its SHA-256 (the `jti`), never the token, like a password. Each use *rotates* it: the old one
is revoked and a new one issued in the same family. If an already-revoked token is shown
again, someone has a copy: the whole family is revoked (token-theft signal).
"""

import datetime as dt
import hashlib
import secrets
import uuid
from dataclasses import dataclass

import jwt
from sqlalchemy import Connection, insert, select, update

from database.init_db import utc_now
from database.models import refresh_tokens

ALGORITHM = "HS256"
REQUIRED_CLAIMS = ["exp", "iat", "sub", "jti"]


class TokenError(Exception):
    """The access token cannot be used. `code` is the API error code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def parse_ts(value: str) -> dt.datetime:
    return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=dt.UTC)


def fmt_ts(moment: dt.datetime) -> str:
    return moment.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# ── access tokens ────────────────────────────────────────────────────────────────────────

def create_access_token(user_id: str, role: str, secret: str, ttl_minutes: int,
                        now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now(dt.UTC)
    claims = {"sub": user_id, "role": role, "iat": now,
              "exp": now + dt.timedelta(minutes=ttl_minutes), "jti": uuid.uuid4().hex}
    return jwt.encode(claims, secret, algorithm=ALGORITHM)


def decode_access_token(token: str, secret: str) -> dict:
    """Verify signature, algorithm and expiry. Only HS256 is accepted ("alg: none" and key
    confusion attacks are refused by naming the algorithm)."""
    try:
        return jwt.decode(token, secret, algorithms=[ALGORITHM],
                          options={"require": REQUIRED_CLAIMS})
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("TOKEN_EXPIRED", "The session has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("INVALID_TOKEN", "The access token is not valid.") from exc


# ── refresh tokens ───────────────────────────────────────────────────────────────────────

def token_jti(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


@dataclass(frozen=True)
class Session:
    """A freshly issued refresh token and when this login's session ends for good."""

    token: str
    expires_at: dt.datetime  # absolute


def _insert(conn: Connection, user_id: str, family_id: str, expires_at: dt.datetime,
            now: dt.datetime) -> str:
    token = secrets.token_urlsafe(32)  # 256 bits
    conn.execute(insert(refresh_tokens).values(
        jti=token_jti(token), user_id=user_id, family_id=family_id, issued_at=fmt_ts(now),
        expires_at=fmt_ts(expires_at), last_used_at=fmt_ts(now), revoked=0))
    return token


def start_session(conn: Connection, user_id: str, absolute_hours: int,
                  now: dt.datetime) -> Session:
    """A new login: a new family, valid for at most `absolute_hours`."""
    expires_at = now + dt.timedelta(hours=absolute_hours)
    return Session(_insert(conn, user_id, uuid.uuid4().hex, expires_at, now), expires_at)


@dataclass(frozen=True)
class RotateResult:
    status: str  # "ok" | "invalid" | "expired" | "idle" | "reuse"
    user_id: str | None = None
    family_id: str | None = None
    session: Session | None = None


def _revoke_family(conn: Connection, family_id: str) -> None:
    conn.execute(update(refresh_tokens).where(refresh_tokens.c.family_id == family_id)
                 .values(revoked=1))


def rotate(conn: Connection, token: str, idle_minutes: int, now: dt.datetime) -> RotateResult:
    """Exchange a refresh token for a new one. Never raises: the caller commits the
    revocations that happen here and then answers 401, so they must not be rolled back."""
    row = conn.execute(select(refresh_tokens).where(
        refresh_tokens.c.jti == token_jti(token))).mappings().first()
    if row is None:
        return RotateResult("invalid")
    who = {"user_id": row["user_id"], "family_id": row["family_id"]}
    if row["revoked"]:
        _revoke_family(conn, row["family_id"])
        return RotateResult("reuse", **who)
    expires_at = parse_ts(row["expires_at"])
    if now >= expires_at:
        _revoke_family(conn, row["family_id"])
        return RotateResult("expired", **who)
    if now >= parse_ts(row["last_used_at"]) + dt.timedelta(minutes=idle_minutes):
        _revoke_family(conn, row["family_id"])
        return RotateResult("idle", **who)
    conn.execute(update(refresh_tokens).where(refresh_tokens.c.jti == row["jti"]).values(revoked=1))
    new_token = _insert(conn, row["user_id"], row["family_id"], expires_at, now)
    return RotateResult("ok", session=Session(new_token, expires_at), **who)


def revoke_session(conn: Connection, token: str) -> str | None:
    """Log out: revoke the token's whole family. Returns the user id, or None if unknown."""
    row = conn.execute(select(refresh_tokens.c.user_id, refresh_tokens.c.family_id).where(
        refresh_tokens.c.jti == token_jti(token))).first()
    if row is None:
        return None
    _revoke_family(conn, row.family_id)
    return row.user_id


def revoke_all_sessions(conn: Connection, user_id: str) -> None:
    """Password change, deactivation or role change: every session of the user ends."""
    conn.execute(update(refresh_tokens).where(refresh_tokens.c.user_id == user_id)
                 .values(revoked=1))


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


__all__ = ["RotateResult", "Session", "TokenError", "create_access_token", "decode_access_token",
           "fmt_ts", "now_utc", "parse_ts", "revoke_all_sessions", "revoke_session", "rotate",
           "start_session", "token_jti", "utc_now"]
