"""Reading, verifying and exporting the audit trail (PROJECT_SPEC §14, §16; FR-10).

Verifying and exporting are themselves audited (AUDIT_VERIFIED, AUDIT_EXPORTED).
"""

import json
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from audit.chain import verify
from audit.export import LogFilter, export_events, list_events
from audit.writer import EVENT_TYPES, log
from auth.dependencies import AuthContext, require
from database.init_db import utc_now
from deps import get_db
from errors import ApiError
from routers.history import _date

router = APIRouter(prefix="/api/audit", tags=["audit"])
CAN_READ = Depends(require("audit:read"))
CAN_EXPORT = Depends(require("audit:export"))


def _filter(from_: str | None, to: str | None, user: str | None, event_type: list[str],
            result: str | None) -> LogFilter:
    unknown = [t for t in event_type if t not in EVENT_TYPES]
    if unknown:
        raise ApiError(422, "VALIDATION_ERROR", "The request is not valid.",
                       details=[{"field": "event_type", "message": f"unknown: {unknown[0]}"}])
    return LogFilter(from_ts=_date(from_), to_ts=_date(to, end_of_day=True), username=user,
                     event_types=tuple(event_type), result=result)


def _applied(f: LogFilter) -> dict:
    return {"from": f.from_ts, "to": f.to_ts, "user": f.username,
            "event_type": list(f.event_types), "result": f.result}


@router.get("/log")
def audit_log_page(request: Request, from_: str | None = Query(None, alias="from"),
                   to: str | None = None, user: str | None = Query(None, max_length=64),
                   event_type: list[str] = Query(default=[]),
                   result: Literal["success", "failure"] | None = None,
                   page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                   _: AuthContext = CAN_READ):
    f = _filter(from_, to, user, event_type, result)
    with get_db(request).read() as conn:
        items, total = list_events(conn, f, page, page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/verify")
def verify_chain(request: Request, ctx: AuthContext = CAN_READ):
    """Recompute every hash. The check itself is recorded, so the log shows who looked."""
    with get_db(request).write() as conn:
        outcome = verify(conn).as_dict()
        log(conn, "AUDIT_VERIFIED", ctx.actor, outcome)
    request.app.state.audit = {**outcome, "verified_at": utc_now()}
    return {**outcome, "verified_at": request.app.state.audit["verified_at"]}


@router.get("/export")
def export(request: Request, from_: str | None = Query(None, alias="from"),
           to: str | None = None, user: str | None = Query(None, max_length=64),
           event_type: list[str] = Query(default=[]),
           result: Literal["success", "failure"] | None = None,
           format: Literal["json"] = "json",  # noqa: A002 — the public query parameter name
           ctx: AuthContext = CAN_EXPORT):
    """Every matching event in chain order, with its hashes, so the file can be re-verified.
    CSV is Tier 2 (§16)."""
    f = _filter(from_, to, user, event_type, result)
    with get_db(request).write() as conn:
        rows = export_events(conn, f)
        log(conn, "AUDIT_EXPORTED", ctx.actor, {
            "filters": _applied(f), "format": format, "row_count": len(rows)})
    body = {"exported_at": utc_now(), "filters": _applied(f), "row_count": len(rows),
            "rows": rows}
    return Response(json.dumps(body, ensure_ascii=False), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="audit_export.json"'})
