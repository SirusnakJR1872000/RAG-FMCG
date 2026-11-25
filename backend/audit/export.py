"""Reading the audit trail: filters, one-line summaries and the JSON export (FR-10, §14.1).

Summaries are derived from the payload when read; they are not stored or hashed.
"""

import json
from dataclasses import dataclass

from sqlalchemy import Connection, func, select

from audit.writer import FAILURE_EVENTS
from database.models import audit_log

QUESTION_PREVIEW = 80


@dataclass(frozen=True)
class LogFilter:
    from_ts: str | None = None  # inclusive, ISO 8601 UTC
    to_ts: str | None = None  # inclusive
    username: str | None = None
    event_types: tuple[str, ...] = ()
    result: str | None = None  # "success" | "failure"
    event_id: str | None = None


def _conditions(f: LogFilter) -> list:
    cond = []
    if f.from_ts:
        cond.append(audit_log.c.timestamp_utc >= f.from_ts)
    if f.to_ts:
        cond.append(audit_log.c.timestamp_utc <= f.to_ts)
    if f.username:
        cond.append(audit_log.c.username == f.username)
    if f.event_types:
        cond.append(audit_log.c.event_type.in_(f.event_types))
    if f.result == "failure":
        cond.append(audit_log.c.event_type.in_(sorted(FAILURE_EVENTS)))
    elif f.result == "success":
        cond.append(audit_log.c.event_type.not_in(sorted(FAILURE_EVENTS)))
    if f.event_id:
        cond.append(audit_log.c.event_id == f.event_id)
    return cond


def summary(event_type: str, payload: dict) -> str:
    """A readable one-liner for the audit table."""
    p = payload
    if event_type == "QUERY":
        return "Asked: " + p.get("original_question", "")[:QUESTION_PREVIEW]
    if event_type == "QUERY_FAILED":
        return f"Query failed: {p.get('error_code', 'unknown error')}"
    if event_type == "LOGIN_FAILED":
        return "Login failed: " + p.get("reason", "unknown").replace("_", " ")
    if event_type == "ACCESS_DENIED":
        return f"Access denied: {p.get('endpoint', '?')} needs {p.get('permission', '?')}"
    if event_type == "PASSWORD_CHANGED":
        return "Password changed (" + p.get("kind", "voluntary") + ")"
    if event_type == "FEEDBACK":
        return "Rated an answer " + ("👍" if p.get("rating") == 1 else "👎")
    if event_type == "USER_CREATED":
        return f"User created: {p.get('target_username')} ({p.get('role')})"
    if event_type == "USER_ROLE_CHANGED":
        return f"Role changed: {p.get('before')} → {p.get('after')}"
    if event_type in ("USER_DEACTIVATED", "USER_UNLOCKED"):
        return f"{event_type.split('_')[1].capitalize()}: {p.get('target_username')}"
    if event_type.startswith("DOCUMENT_"):
        action = event_type.split("_")[1].lower()
        return f"Document {action}: {p.get('doc_code')} {p.get('version')}"
    if event_type in ("INDEX_BUILT", "INDEX_ACTIVATED"):
        return f"Index {event_type.split('_')[1].lower()}: {p.get('build_id')}"
    if event_type == "AUDIT_VERIFIED":
        if p.get("ok"):
            return f"Integrity check: chain intact ({p.get('checked')} records)"
        return f"Integrity check FAILED at record #{p.get('first_bad_seq')}"
    if event_type == "AUDIT_EXPORTED":
        return f"Exported {p.get('row_count')} records"
    return event_type.replace("_", " ").capitalize()


def _row(row) -> dict:
    payload = json.loads(row["payload_json"])
    return {"seq": row["seq"], "event_id": row["event_id"], "timestamp_utc": row["timestamp_utc"],
            "event_type": row["event_type"], "username": row["username"], "role": row["role"],
            "user_id": row["user_id"], "client_ip": row["client_ip"],
            "request_id": row["request_id"], "summary": summary(row["event_type"], payload),
            "payload": payload, "prev_hash": row["prev_hash"], "row_hash": row["row_hash"]}


def list_events(conn: Connection, f: LogFilter, page: int = 1, page_size: int = 50,
                ) -> tuple[list[dict], int]:
    """One page of events, newest first, and the total number matching the filter."""
    cond = _conditions(f)
    total = conn.execute(select(func.count()).select_from(audit_log).where(*cond)).scalar_one()
    rows = conn.execute(select(audit_log).where(*cond).order_by(audit_log.c.seq.desc())
                        .limit(page_size).offset((page - 1) * page_size)).mappings()
    return [_row(r) for r in rows], total


def export_events(conn: Connection, f: LogFilter) -> list[dict]:
    """Every matching event in chain order (oldest first), so an export can be re-verified."""
    rows = conn.execute(select(audit_log).where(*_conditions(f))
                        .order_by(audit_log.c.seq)).mappings()
    return [_row(r) for r in rows]
