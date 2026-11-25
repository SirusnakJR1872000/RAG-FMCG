"""The one function that writes audit events (PROJECT_SPEC §14.1 "Consistent", §14.3).

`log()` must be called inside `db.write()`: that transaction holds SQLite's write lock from
its first statement, so reading the last row and appending the next one cannot interleave
with another writer. The event commits or rolls back together with the change it records.
"""

from dataclasses import dataclass

from sqlalchemy import Connection, insert, select

from audit.chain import GENESIS_HASH, dump_json, row_hash
from database.init_db import new_id, utc_now
from database.models import audit_log

# §14.2. USER_UNLOCKED is not in the catalogue: FR-11 requires admins to unlock accounts and
# AUD-01/AUD-05 require every action to be recorded; it is proposed as an addition (A-04).
EVENT_TYPES = frozenset({
    "SYSTEM_START", "LOGIN_SUCCESS", "LOGIN_FAILED", "ACCOUNT_LOCKED", "LOGOUT",
    "REFRESH_REUSE_DETECTED", "PASSWORD_CHANGED", "ACCESS_DENIED", "QUERY", "QUERY_FAILED",
    "FEEDBACK", "USER_CREATED", "USER_ROLE_CHANGED", "USER_DEACTIVATED", "USER_UNLOCKED",
    "DOCUMENT_INGESTED", "DOCUMENT_SUPERSEDED", "DOCUMENT_WITHDRAWN", "INDEX_BUILT",
    "INDEX_ACTIVATED", "AUDIT_VERIFIED", "AUDIT_EXPORTED"})
# Shown with a red marker in the audit screen (§5.6 of the design brief).
FAILURE_EVENTS = frozenset({"LOGIN_FAILED", "ACCOUNT_LOCKED", "ACCESS_DENIED", "QUERY_FAILED",
                            "REFRESH_REUSE_DETECTED"})


@dataclass(frozen=True)
class Actor:
    """Who did it (ALCOA "Attributable"): identity, role, network address and request."""

    user_id: str | None  # None only for login attempts on unknown usernames
    username: str
    role: str | None = None
    client_ip: str | None = None
    request_id: str | None = None


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    event_id: str
    timestamp_utc: str
    row_hash: str


def log(conn: Connection, event_type: str, actor: Actor, payload: dict | None = None,
        ) -> AuditEntry:
    """Append one event to the chain and return its identity."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown audit event type: {event_type}")
    if not conn.info.get("write"):
        raise RuntimeError("audit.log() must run inside db.write(): the chain needs the lock")
    last = conn.execute(select(audit_log.c.seq, audit_log.c.row_hash)
                        .order_by(audit_log.c.seq.desc()).limit(1)).first()
    seq, prev_hash = (1, GENESIS_HASH) if last is None else (last.seq + 1, last.row_hash)
    entry = {"seq": seq, "event_id": new_id("evt"), "timestamp_utc": utc_now(),
             "event_type": event_type, "user_id": actor.user_id, "username": actor.username,
             "role": actor.role, "client_ip": actor.client_ip, "request_id": actor.request_id,
             "payload": payload or {}}
    digest = row_hash(prev_hash, entry)
    conn.execute(insert(audit_log).values(
        **{k: v for k, v in entry.items() if k != "payload"},
        payload_json=dump_json(entry["payload"]), prev_hash=prev_hash, row_hash=digest))
    return AuditEntry(seq, entry["event_id"], entry["timestamp_utc"], digest)
