"""Create the schema and the system account (PROJECT_SPEC §12 rules)."""

import datetime as dt
import uuid

from sqlalchemy import insert, select

from database.models import users
from database.session import Database

SYSTEM_USER_ID = "u_system"
SYSTEM_USERNAME = "system"
NO_LOGIN_HASH = "!"  # not a valid Argon2 hash: no password can ever match it


def utc_now() -> str:
    """Server UTC time, ISO 8601 with microseconds and 'Z' (§14.3)."""
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def init_db(db: Database) -> None:
    """Idempotent: create missing tables and the `system` account that owns CLI actions."""
    db.create_all()
    with db.write() as conn:
        if conn.execute(select(users.c.id).where(users.c.id == SYSTEM_USER_ID)).first():
            return
        conn.execute(insert(users).values(
            id=SYSTEM_USER_ID, username=SYSTEM_USERNAME, full_name="System",
            password_hash=NO_LOGIN_HASH, role="system", is_active=1, can_login=0,
            must_change_password=0, password_changed_at=utc_now(), created_at=utc_now()))
