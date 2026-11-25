"""User administration (PROJECT_SPEC §13, §16; design brief Users screen).

Admin only. Every change is audited in the same transaction as the change itself.
Safeguards: an admin cannot change or deactivate their own account here, and the last active
admin can never be removed (nobody could manage users afterwards).
"""

import datetime as dt
import re
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import Field, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from audit.writer import log
from auth import service, tokens
from auth.dependencies import AuthContext, require
from database.models import audit_log, users
from deps import get_db
from errors import ApiError
from schemas import Strict

router = APIRouter(prefix="/api/users", tags=["users"])
ADMIN = Depends(require("users:manage"))
USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
Role = Literal["viewer", "qa_user", "auditor", "admin"]


class CreateUser(Strict):
    username: str = Field(min_length=3, max_length=32)
    full_name: str = Field(min_length=1, max_length=100)
    role: Role


class UpdateUser(Strict):
    role: Role | None = None
    unlock: Literal[True] | None = None
    deactivate: Literal[True] | None = None

    @model_validator(mode="after")
    def _something_to_do(self):
        if self.role is None and self.unlock is None and self.deactivate is None:
            raise ValueError("send role, unlock or deactivate")
        return self


def status_of(user: dict, now: dt.datetime) -> str:
    if not user["is_active"]:
        return "deactivated"
    if user["locked_until"] and tokens.parse_ts(user["locked_until"]) > now:
        return "locked"
    return "must_change_password" if user["must_change_password"] else "active"


def public(user: dict, last_login: str | None) -> dict:
    return {"id": user["id"], "username": user["username"], "full_name": user["full_name"],
            "role": user["role"], "status": status_of(user, service.now_utc()),
            "last_login_at": last_login, "created_at": user["created_at"]}


def _last_logins(conn) -> dict[str, str]:
    rows = conn.execute(select(audit_log.c.user_id, func.max(audit_log.c.timestamp_utc))
                        .where(audit_log.c.event_type == "LOGIN_SUCCESS")
                        .group_by(audit_log.c.user_id))
    return {user_id: ts for user_id, ts in rows}


def _admin_count(conn) -> int:
    return conn.execute(select(func.count()).select_from(users).where(
        users.c.role == "admin", users.c.is_active == 1)).scalar_one()


@router.get("")
def list_users(request: Request, _: AuthContext = ADMIN):
    with get_db(request).read() as conn:
        rows = [dict(r) for r in conn.execute(
            select(users).where(users.c.can_login == 1).order_by(users.c.username)).mappings()]
        logins = _last_logins(conn)
    return {"items": [public(r, logins.get(r["id"])) for r in rows], "total": len(rows)}


@router.post("", status_code=201)
def create_user(body: CreateUser, request: Request, ctx: AuthContext = ADMIN):
    """The temporary password is in this response only: it is not stored in readable form."""
    username = service.normalise_username(body.username)
    if not USERNAME.match(username):
        raise ApiError(422, "VALIDATION_ERROR", "The request is not valid.", details=[{
            "field": "username",
            "message": "3–32 characters: letters, digits, dot, dash or underscore"}])
    temporary = service.generate_temporary_password()
    try:
        with get_db(request).write() as conn:
            user = service.create_user(
                conn, username=username, full_name=body.full_name, role=body.role,
                password=temporary, created_by=ctx.user["id"], actor=ctx.actor)
    except IntegrityError as exc:  # usernames are never reused, even by deactivated users
        raise ApiError(409, "USERNAME_TAKEN", "That username is already used.") from exc
    return {**public(user, None), "temporary_password": temporary}


@router.patch("/{user_id}")
def update_user(user_id: str, body: UpdateUser, request: Request, ctx: AuthContext = ADMIN):
    with get_db(request).write() as conn:
        target = service.get_user(conn, user_id)
        if target is None or not target["can_login"]:
            raise ApiError(404, "NOT_FOUND", "User not found.")
        changing_self = target["id"] == ctx.user["id"]
        if changing_self and (body.role is not None or body.deactivate):
            raise ApiError(409, "CANNOT_CHANGE_SELF",
                           "You cannot change your own role or deactivate yourself.")
        removes_admin = target["role"] == "admin" and target["is_active"] and (
            body.deactivate or (body.role is not None and body.role != "admin"))
        if removes_admin and _admin_count(conn) <= 1:
            raise ApiError(409, "LAST_ADMIN", "There must be at least one active admin.")
        who = {"target_username": target["username"], "target_user_id": target["id"]}
        if body.role is not None and body.role != target["role"]:
            conn.execute(update(users).where(users.c.id == user_id).values(role=body.role))
            log(conn, "USER_ROLE_CHANGED", ctx.actor, {
                **who, "before": target["role"], "after": body.role})
        if body.unlock:
            conn.execute(update(users).where(users.c.id == user_id).values(
                locked_until=None, failed_login_count=0))
            log(conn, "USER_UNLOCKED", ctx.actor, who)
        if body.deactivate and target["is_active"]:
            conn.execute(update(users).where(users.c.id == user_id).values(is_active=0))
            tokens.revoke_all_sessions(conn, user_id)  # their refresh tokens stop working now
            log(conn, "USER_DEACTIVATED", ctx.actor, who)
        updated = service.get_user(conn, user_id)
        last = _last_logins(conn).get(user_id)
    return public(updated, last)
