"""Rate an answer 👍/👎 with an optional comment (PROJECT_SPEC §16, FR-08)."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import insert, select, update

from audit.writer import log
from auth.dependencies import AuthContext, require
from database.init_db import new_id, utc_now
from database.models import audit_log, feedback
from database.session import Database
from deps import get_db
from errors import ApiError
from schemas import FeedbackRequest

router = APIRouter(prefix="/api", tags=["query"])
CAN_QUERY = Depends(require("query:run"))


@router.post("/feedback", status_code=201)
def give_feedback(body: FeedbackRequest, request: Request, ctx: AuthContext = CAN_QUERY,
                  db: Database = Depends(get_db)):
    """Own questions only. Rating again replaces the earlier rating."""
    if body.rating not in (-1, 1):
        raise ApiError(422, "VALIDATION_ERROR", "The request is not valid.",
                       details=[{"field": "rating", "message": "must be 1 or -1"}])
    with db.write() as conn:
        event = conn.execute(select(audit_log.c.user_id, audit_log.c.event_type).where(
            audit_log.c.event_id == body.query_event_id)).first()
        if event is None or event.event_type != "QUERY" or event.user_id != ctx.user["id"]:
            raise ApiError(404, "QUERY_NOT_FOUND", "Answer not found.")
        existing = conn.execute(select(feedback.c.id).where(
            feedback.c.query_event_id == body.query_event_id,
            feedback.c.user_id == ctx.user["id"])).first()
        if existing:
            feedback_id = existing.id
            conn.execute(update(feedback).where(feedback.c.id == feedback_id).values(
                rating=body.rating, comment=body.comment, created_at=utc_now()))
        else:
            feedback_id = new_id("f")
            conn.execute(insert(feedback).values(
                id=feedback_id, query_event_id=body.query_event_id, user_id=ctx.user["id"],
                rating=body.rating, comment=body.comment, created_at=utc_now()))
        log(conn, "FEEDBACK", ctx.actor, {"query_event_id": body.query_event_id,
                                          "rating": body.rating, "comment": body.comment})
    return {"id": feedback_id, "query_event_id": body.query_event_id, "rating": body.rating,
            "comment": body.comment}
