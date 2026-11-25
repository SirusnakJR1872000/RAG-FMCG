"""Ask a question: blocking and streaming (PROJECT_SPEC §16, §17; FR-01..FR-06; SEC-10).

Both endpoints: need `query:run`; 10 questions/min per user; wait in the LLM queue (one question
at a time); follow-ups use the conversation's last 2 exchanges; the QUERY audit event is
written before the answer is delivered.
"""

import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from audit.writer import Actor
from auth.dependencies import AuthContext, require
from database.session import Database
from deps import get_db, get_index, get_queue, get_settings_from
from errors import ApiError
from ratelimit import limiter, query_limit, user_key
from schemas import QueryRequest
from services import conversation_service
from services.llm_queue import LLMQueue, QueueFull, Ticket
from services.query_service import (
    acquire_turn,
    api_error,
    error_code_for,
    event_stream,
    public_source,
    query_payload,
    write_failed_audit,
    write_query_audit,
)

router = APIRouter(prefix="/api", tags=["query"])
CAN_QUERY = Depends(require("query:run"))


class Prepared:
    """Everything checked before a question is allowed to run."""

    def __init__(self, request: Request, body: QueryRequest, ctx: AuthContext):
        self.db: Database = get_db(request)
        self.settings = get_settings_from(request)
        self.queue: LLMQueue = get_queue(request)
        self.actor: Actor = ctx.actor
        self.question = body.question
        self.pipeline = get_index(request).pipeline  # held for the whole request (swap-safe)
        self.build_id = get_index(request).build_id
        user_id = ctx.user["id"]

        if self.pipeline is None:
            self._fail("INDEX_NOT_READY", None)
        with self.db.write() as conn:  # an unknown or foreign conversation is simply "not found"
            if body.conversation_id is None:
                self.conversation_id = conversation_service.create_conversation(conn, user_id)["id"]
            elif conversation_service.owns_conversation(conn, body.conversation_id, user_id):
                self.conversation_id = body.conversation_id
            else:
                raise ApiError(404, "CONVERSATION_NOT_FOUND", "Conversation not found.")

        def load_history():
            with self.db.read() as conn:
                return conversation_service.recent_exchanges(
                    conn, user_id, self.conversation_id, self.settings.history_turns)

        self.load_history = load_history
        try:
            self.ticket: Ticket = self.queue.join()
        except QueueFull:
            self._fail("QUEUE_FULL", self.conversation_id)

    def _fail(self, code: str, conversation_id: str | None):
        write_failed_audit(self.db, self.actor, conversation_id, self.question, code)
        raise api_error(code)


@router.post("/query")
@limiter.limit(query_limit, key_func=user_key)
async def query(request: Request, body: QueryRequest, ctx: AuthContext = CAN_QUERY):
    """The whole answer at once (for scripts and integrations)."""
    prep = Prepared(request, body, ctx)
    result = None
    try:
        await acquire_turn(prep.queue, prep.ticket)
        history = await asyncio.to_thread(prep.load_history)
        result = await prep.pipeline.answer(body.question, history)
    except asyncio.CancelledError:  # the caller hung up: still record the attempt
        write_query_audit(prep.db, prep.actor, query_payload(
            prep.settings, prep.build_id, prep.conversation_id, body.question, None,
            completed=False))
        raise
    except Exception as exc:
        code = error_code_for(exc)
        await asyncio.to_thread(write_failed_audit, prep.db, prep.actor, prep.conversation_id,
                                body.question, code)
        if code == "INTERNAL_ERROR":
            raise
        raise api_error(code) from exc
    finally:
        prep.queue.release(prep.ticket)
    payload = query_payload(prep.settings, prep.build_id, prep.conversation_id, body.question,
                            result, completed=True)
    try:  # no audit record, no answer
        entry = await asyncio.to_thread(write_query_audit, prep.db, prep.actor, payload)
    except Exception as exc:
        raise api_error("AUDIT_WRITE_FAILED") from exc
    return {"event_id": entry.event_id, "conversation_id": prep.conversation_id,
            "answer_type": result.answer_type, "standalone_question": result.standalone_question,
            "answer": result.answer, "sources": [public_source(s) for s in result.sources],
            "citation_check": result.citation_check.as_dict() if result.citation_check else None,
            "latency_ms": result.latency_ms, "timestamp_utc": entry.timestamp_utc}


@router.post("/query/stream")
@limiter.limit(query_limit, key_func=user_key)
async def query_stream(request: Request, body: QueryRequest, ctx: AuthContext = CAN_QUERY):
    """The answer as Server-Sent Events (§17): queued, status, sources, token…, done | error.

    Not `EventSource`: it cannot send an Authorization header and only supports GET, so the
    browser reads this with fetch + ReadableStream.
    """
    prep = Prepared(request, body, ctx)
    stream = event_stream(
        ticket=prep.ticket, queue=prep.queue, pipeline=prep.pipeline, db=prep.db,
        actor=prep.actor, settings=prep.settings, index_build_id=prep.build_id,
        question=body.question, conversation_id=prep.conversation_id,
        load_history=prep.load_history)
    return StreamingResponse(
        stream, media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        background=BackgroundTask(prep.queue.release, prep.ticket))  # in case it never started
