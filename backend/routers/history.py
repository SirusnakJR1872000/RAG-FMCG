"""Query history, read from the audit trail (PROJECT_SPEC §12 rules, §16, FR-07).

There is no history table: history IS the QUERY events (and QUERY_FAILED ones, shown as
"failed"), so it can never disagree with the audit.

Who sees what:
- anyone with `history:own` sees their own questions (an admin too: everyone's are in Audit);
- an auditor has no questions of their own, so by default sees everyone's;
- `?user=` (needs `audit:read`) shows one person's.
"""

import json
import re

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import Connection, func, select

from auth.dependencies import AuthContext, deny, require_any
from auth.permissions import has_permission
from database.models import audit_log, documents, feedback
from deps import get_db, get_index
from errors import ApiError

router = APIRouter(prefix="/api/history", tags=["history"])
HISTORY_EVENTS = ("QUERY", "QUERY_FAILED")
CAN_SEE_HISTORY = Depends(require_any("history:own", "audit:read"))
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(T[0-9:.]+Z?)?$")


def result_of(event_type: str, payload: dict) -> str:
    """What the History screen's Result column shows."""
    if event_type == "QUERY_FAILED":
        return "failed"
    if not payload.get("completed", True):
        return "interrupted"
    return "answered" if payload.get("answer_type") == "answered" else "not_covered"


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"


def _date(value: str | None, end_of_day: bool = False) -> str | None:
    if value is None:
        return None
    if not DATE.match(value):
        raise ApiError(422, "VALIDATION_ERROR", "The request is not valid.",
                       details=[{"field": "date", "message": "use YYYY-MM-DD"}])
    if len(value) == 10:  # a plain date means the whole day
        return value + ("T23:59:59.999999Z" if end_of_day else "T00:00:00.000000Z")
    return value


def _item(row) -> dict:
    payload = json.loads(row["payload_json"])
    return {"event_id": row["event_id"], "timestamp_utc": row["timestamp_utc"],
            "conversation_id": payload.get("conversation_id"),
            "question": payload.get("original_question"),
            "result": result_of(row["event_type"], payload),
            "answer_type": payload.get("answer_type"), "completed": payload.get("completed"),
            "sources_count": len(payload.get("sources", [])), "feedback": row["rating"],
            "time_taken_ms": payload.get("latency_ms", {}).get("total"),
            "username": row["username"], "error_code": payload.get("error_code")}


@router.get("")
def list_history(
        request: Request, ctx: AuthContext = CAN_SEE_HISTORY,
        conversation: str | None = Query(None, max_length=64),
        q: str | None = Query(None, max_length=200, description="text in the question"),
        from_: str | None = Query(None, alias="from"), to: str | None = None,
        user: str | None = Query(None, max_length=64),
        page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    role = ctx.user["role"]
    sees_all = has_permission(role, "audit:read")
    if user and not sees_all:
        raise deny(request, ctx, "audit:read")
    cond = [audit_log.c.event_type.in_(HISTORY_EVENTS)]
    if user:
        cond.append(audit_log.c.username == user.strip().lower())
    elif has_permission(role, "history:own"):
        cond.append(audit_log.c.user_id == ctx.user["id"])  # own questions
    if conversation:
        cond.append(func.json_extract(audit_log.c.payload_json, "$.conversation_id")
                    == conversation)
    if q:
        cond.append(func.json_extract(audit_log.c.payload_json, "$.original_question")
                    .like(_like(q), escape="\\"))
    if (start := _date(from_)):
        cond.append(audit_log.c.timestamp_utc >= start)
    if (end := _date(to, end_of_day=True)):
        cond.append(audit_log.c.timestamp_utc <= end)
    joined = audit_log.outerjoin(feedback, feedback.c.query_event_id == audit_log.c.event_id)
    with get_db(request).read() as conn:
        total = conn.execute(select(func.count()).select_from(audit_log).where(*cond)).scalar_one()
        rows = conn.execute(
            select(audit_log, feedback.c.rating).select_from(joined).where(*cond)
            .order_by(audit_log.c.seq.desc()).limit(page_size).offset((page - 1) * page_size)
        ).mappings().all()
    return {"items": [_item(r) for r in rows], "page": page, "page_size": page_size,
            "total": total}


def _active_versions(conn: Connection) -> set[tuple[str, str]] | None:
    rows = conn.execute(select(documents.c.doc_code, documents.c.version)
                        .where(documents.c.status == "active")).all()
    return {(r.doc_code, r.version) for r in rows} or None  # None: registry not filled yet


def _enrich(sources: list[dict], pipeline, active: set | None) -> list[dict]:
    """Add the passage text and title (looked up by chunk id) and a superseded flag."""
    out = []
    for s in sources:
        extra = {"title": None, "section_title": None, "text": None}
        if pipeline is not None and s["chunk_id"] in pipeline.chunks.index:
            row = pipeline.chunks.loc[s["chunk_id"]]
            extra = {"title": row["doc_title"], "section_title": row["section_title"],
                     "text": row["text"]}
        superseded = None if active is None else (s["doc_code"], s["version"]) not in active
        out.append({**s, **extra, "superseded": superseded})
    return out


@router.get("/{event_id}")
def history_detail(event_id: str, request: Request, ctx: AuthContext = CAN_SEE_HISTORY):
    """One question in full. Owners see their own; `audit:read` sees anyone's; others get 404."""
    with get_db(request).read() as conn:
        row = conn.execute(
            select(audit_log, feedback.c.rating, feedback.c.comment)
            .select_from(audit_log.outerjoin(feedback, feedback.c.query_event_id
                                             == audit_log.c.event_id))
            .where(audit_log.c.event_id == event_id, audit_log.c.event_type.in_(HISTORY_EVENTS))
        ).mappings().first()
        allowed = row is not None and (row["user_id"] == ctx.user["id"]
                                       or has_permission(ctx.user["role"], "audit:read"))
        if not allowed:
            raise ApiError(404, "NOT_FOUND", "Not found.")
        active = _active_versions(conn)
    payload = json.loads(row["payload_json"])
    item = _item(row)
    return item | {
        "standalone_question": payload.get("standalone_question"),
        "answer": payload.get("answer"),
        "sources": _enrich(payload.get("sources", []), get_index(request).pipeline, active),
        "citation_check": payload.get("citation_check"), "latency_ms": payload.get("latency_ms"),
        "models": payload.get("models"), "index_build_id": payload.get("index_build_id"),
        "feedback": ({"rating": row["rating"], "comment": row["comment"]}
                     if row["rating"] is not None else None)}
