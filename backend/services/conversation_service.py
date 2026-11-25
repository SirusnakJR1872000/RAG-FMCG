"""Conversations and the exchanges used for follow-up questions (PROJECT_SPEC §12, FR-06).

Query history is not a separate table: it is read from the QUERY events of the audit trail,
so history and audit can never disagree.
"""

import json

from sqlalchemy import Connection, func, insert, select

from audit.writer import AuditEntry  # noqa: F401  (re-exported for callers)
from database.init_db import new_id, utc_now
from database.models import audit_log, conversations
from src.generation.prompts import Exchange


def create_conversation(conn: Connection, user_id: str) -> dict:
    conversation = {"id": new_id("c"), "user_id": user_id, "created_at": utc_now()}
    conn.execute(insert(conversations).values(**conversation))
    return conversation


def owns_conversation(conn: Connection, conversation_id: str, user_id: str) -> bool:
    row = conn.execute(select(conversations.c.user_id).where(
        conversations.c.id == conversation_id)).first()
    return row is not None and row.user_id == user_id


def recent_exchanges(conn: Connection, user_id: str, conversation_id: str,
                     limit: int) -> list[Exchange]:
    """The last `limit` finished exchanges of this conversation, oldest first.

    An exchange cut short (client disconnected, completed=false) has no usable answer and is
    skipped.
    """
    rows = conn.execute(
        select(audit_log.c.payload_json)
        .where(audit_log.c.event_type == "QUERY", audit_log.c.user_id == user_id,
               func.json_extract(audit_log.c.payload_json, "$.conversation_id") == conversation_id,
               func.json_extract(audit_log.c.payload_json, "$.completed") == 1)
        .order_by(audit_log.c.seq.desc()).limit(limit)).all()
    payloads = [json.loads(r[0]) for r in reversed(rows)]
    return [Exchange(p["original_question"], p["answer"]) for p in payloads]
