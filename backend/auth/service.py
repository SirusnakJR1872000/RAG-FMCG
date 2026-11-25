"""Login, sessions, password changes and user creation (PROJECT_SPEC §13; SEC-03..SEC-06).

Every function runs inside one `db.write()` transaction and writes its audit event there, so
a lockout counter, a revoked token and the event that records them commit together.
Functions RETURN a status instead of raising for expected failures (wrong password, locked,
reuse): an exception would roll back the very counter or revocation that must be kept.
"""

import datetime as dt
import secrets
from dataclasses import dataclass, field

from sqlalchemy import Connection, insert, select, update

from audit.writer import Actor, log
from auth import passwords, tokens
from auth.permissions import LOGIN_ROLES
from config import Settings
from database.init_db import new_id
from database.models import password_history, users
from database.session import Database  # noqa: F401  (documented transaction contract)


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@dataclass(frozen=True)
class RequestInfo:
    """The parts of an HTTP request the audit trail needs."""

    client_ip: str | None = None
    request_id: str | None = None


def actor_for(user: dict, info: RequestInfo) -> Actor:
    return Actor(user["id"], user["username"], user["role"], info.client_ip, info.request_id)


def normalise_username(username: str) -> str:
    return username.strip().lower()


def get_user_by_username(conn: Connection, username: str) -> dict | None:
    row = conn.execute(select(users).where(
        users.c.username == normalise_username(username))).mappings().first()
    return dict(row) if row else None


def get_user(conn: Connection, user_id: str) -> dict | None:
    row = conn.execute(select(users).where(users.c.id == user_id)).mappings().first()
    return dict(row) if row else None


def password_expired(user: dict, settings: Settings, now: dt.datetime) -> bool:
    changed = tokens.parse_ts(user["password_changed_at"])
    return now >= changed + dt.timedelta(days=settings.password_expiry_days)


def must_change_password(user: dict, settings: Settings, now: dt.datetime) -> bool:
    """First login (temporary password) or an expired password (SEC-05)."""
    return bool(user["must_change_password"]) or password_expired(user, settings, now)


# ── failures and lockout ─────────────────────────────────────────────────────────────────

def _register_failure(conn: Connection, settings: Settings, user: dict, actor: Actor,
                      reason: str, now: dt.datetime) -> bool:
    """Count a failed attempt; lock the account on the 5th (SEC-04). True if it is now locked."""
    count = user["failed_login_count"] + 1
    values: dict = {"failed_login_count": count}
    locked = count >= settings.max_failed_logins
    if locked:
        values["locked_until"] = tokens.fmt_ts(now + dt.timedelta(minutes=settings.lockout_minutes))
    conn.execute(update(users).where(users.c.id == user["id"]).values(**values))
    log(conn, "LOGIN_FAILED", actor, {"attempted_username": user["username"], "reason": reason})
    if locked:
        log(conn, "ACCOUNT_LOCKED", actor, {"attempted_username": user["username"],
                                            "failed_attempts": count,
                                            "locked_until": values["locked_until"]})
    return locked


# ── login ────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LoginResult:
    status: str  # "ok" | "invalid" | "locked"
    user: dict | None = None
    session: tokens.Session | None = None
    must_change_password: bool = False


def login(conn: Connection, settings: Settings, username: str, password: str, info: RequestInfo,
          now: dt.datetime | None = None) -> LoginResult:
    now = now or now_utc()
    user = get_user_by_username(conn, username)
    attempted = normalise_username(username)
    if user is None:
        passwords.dummy_verify(password)  # same time as a wrong password (§13.2)
        log(conn, "LOGIN_FAILED", Actor(None, attempted, None, info.client_ip, info.request_id),
            {"attempted_username": attempted, "reason": "unknown_user"})
        return LoginResult("invalid")
    actor = actor_for(user, info)
    if not user["is_active"] or not user["can_login"]:
        passwords.dummy_verify(password)  # a deactivated account looks like a wrong password
        log(conn, "LOGIN_FAILED", actor, {"attempted_username": attempted, "reason": "inactive"})
        return LoginResult("invalid")
    if user["locked_until"]:
        if tokens.parse_ts(user["locked_until"]) > now:
            log(conn, "LOGIN_FAILED", actor, {"attempted_username": attempted,
                                              "reason": "account_locked"})
            return LoginResult("locked", user)  # the password is not even checked
        conn.execute(update(users).where(users.c.id == user["id"]).values(
            locked_until=None, failed_login_count=0))  # the lock has run out
        user = {**user, "locked_until": None, "failed_login_count": 0}
    if not passwords.verify_password(user["password_hash"], password):
        locked = _register_failure(conn, settings, user, actor, "wrong_password", now)
        return LoginResult("locked" if locked else "invalid", user)
    values: dict = {"failed_login_count": 0}
    if passwords.needs_rehash(user["password_hash"]):  # parameters were raised since
        values["password_hash"] = passwords.hash_password(password)
    conn.execute(update(users).where(users.c.id == user["id"]).values(**values))
    session = tokens.start_session(conn, user["id"], settings.refresh_absolute_hours, now)
    log(conn, "LOGIN_SUCCESS", actor, {"attempted_username": attempted})
    return LoginResult("ok", user, session, must_change_password(user, settings, now))


# ── refresh and logout ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RefreshResult:
    status: str  # "ok" | "invalid" | "expired" | "idle" | "reuse"
    user: dict | None = None
    session: tokens.Session | None = None


def refresh(conn: Connection, settings: Settings, token: str, info: RequestInfo,
            now: dt.datetime | None = None) -> RefreshResult:
    now = now or now_utc()
    result = tokens.rotate(conn, token, settings.refresh_idle_minutes, now)
    user = get_user(conn, result.user_id) if result.user_id else None
    if result.status == "reuse" and user:
        log(conn, "REFRESH_REUSE_DETECTED", actor_for(user, info), {"family_id": result.family_id})
    if result.status != "ok":
        return RefreshResult(result.status)
    if user is None or not user["is_active"] or not user["can_login"]:
        tokens.revoke_all_sessions(conn, result.user_id)
        return RefreshResult("invalid")
    return RefreshResult("ok", user, result.session)


def logout(conn: Connection, token: str, info: RequestInfo) -> bool:
    """End the session of this refresh token. True if it belonged to a live session."""
    user_id = tokens.revoke_session(conn, token)
    user = get_user(conn, user_id) if user_id else None
    if user:
        log(conn, "LOGOUT", actor_for(user, info), {})
    return user is not None


# ── passwords ────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ChangeResult:
    status: str  # "ok" | "wrong_current" | "locked" | "policy"
    violations: list[str] = field(default_factory=list)
    session: tokens.Session | None = None


def change_password(conn: Connection, settings: Settings, user: dict, current_password: str,
                    new_password: str, info: RequestInfo,
                    now: dt.datetime | None = None) -> ChangeResult:
    now = now or now_utc()
    actor = actor_for(user, info)
    if not passwords.verify_password(user["password_hash"], current_password):
        # a stolen access token must not allow guessing the current password forever
        locked = _register_failure(conn, settings, user, actor, "wrong_current_password", now)
        return ChangeResult("locked" if locked else "wrong_current")
    recent = [r[0] for r in conn.execute(
        select(password_history.c.password_hash).where(password_history.c.user_id == user["id"])
        .order_by(password_history.c.id.desc()).limit(settings.password_history_count))]
    broken = passwords.check_policy(new_password, username=user["username"],
                                    min_length=settings.password_min_length, recent_hashes=recent)
    if broken:
        return ChangeResult("policy", broken)
    forced = must_change_password(user, settings, now)
    new_hash = passwords.hash_password(new_password)
    conn.execute(update(users).where(users.c.id == user["id"]).values(
        password_hash=new_hash, password_changed_at=tokens.fmt_ts(now), must_change_password=0,
        failed_login_count=0))
    conn.execute(insert(password_history).values(
        user_id=user["id"], password_hash=new_hash, created_at=tokens.fmt_ts(now)))
    tokens.revoke_all_sessions(conn, user["id"])  # every other device is signed out
    session = tokens.start_session(conn, user["id"], settings.refresh_absolute_hours, now)
    log(conn, "PASSWORD_CHANGED", actor, {"kind": "forced" if forced else "voluntary"})
    return ChangeResult("ok", session=session)


def generate_temporary_password() -> str:
    """Shown once to the admin; the user must replace it at the first login."""
    return secrets.token_urlsafe(12)


def create_user(conn: Connection, *, username: str, full_name: str, role: str, password: str,
                created_by: str | None, actor: Actor, now: dt.datetime | None = None) -> dict:
    """A new account with a temporary password (must be changed at the first login).

    Usernames are never reused, not even by deactivated users: the UNIQUE constraint makes a
    duplicate raise IntegrityError, which the caller turns into a 409.
    """
    if role not in LOGIN_ROLES:
        raise ValueError(f"role must be one of {LOGIN_ROLES}")
    now = now or now_utc()
    username = normalise_username(username)
    password_hash = passwords.hash_password(password)
    user_id = new_id("u")
    conn.execute(insert(users).values(
        id=user_id, username=username, full_name=full_name.strip(), password_hash=password_hash,
        role=role, is_active=1, can_login=1, must_change_password=1,
        password_changed_at=tokens.fmt_ts(now), created_at=tokens.fmt_ts(now),
        created_by=created_by))
    conn.execute(insert(password_history).values(
        user_id=user_id, password_hash=password_hash, created_at=tokens.fmt_ts(now)))
    log(conn, "USER_CREATED", actor, {"target_username": username, "target_user_id": user_id,
                                      "role": role})
    return get_user(conn, user_id)
