"""Running a question and recording it (PROJECT_SPEC §9.4, §14.2, §15.6, §17).

Rules implemented here:
- the QUERY audit event is written BEFORE the answer is delivered; if the write fails, the
  answer is not delivered (AUD-01: no audit record, no answer);
- a client that disconnects mid-stream still gets a QUERY event, with completed=false;
- a failed question is recorded as QUERY_FAILED with an error code;
- the queue place is always given back, however the request ends.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Callable

import structlog

from audit.writer import Actor, AuditEntry, log
from config import Settings
from database.session import Database
from errors import ApiError
from services.llm_queue import LLMQueue, Ticket
from src.generation.ollama_client import LLMTimeout, LLMUnavailable, OllamaError
from src.generation.pipeline import Done, QuestionError, Result, SourceInfo, SourcesReady, Status
from src.generation.pipeline import Token as TokenEvent

log_ = structlog.get_logger(__name__)
KEEPALIVE_SECONDS = 15.0  # §17: a comment line while waiting, so proxies keep the connection

# error code → (HTTP status, message). Used by both endpoints.
ERRORS = {
    "LLM_UNAVAILABLE": (503, "The language model is not available. Try again later."),
    "LLM_TIMEOUT": (504, "The model took too long to respond."),
    "INDEX_NOT_READY": (503, "The search index is not ready."),
    "QUEUE_FULL": (429, "Too many questions are waiting. Try again in a minute."),
    "VALIDATION_ERROR": (422, "The question is not valid."),
    "AUDIT_WRITE_FAILED": (500, "This answer could not be recorded, so it was not shown."),
    "INTERNAL_ERROR": (500, "Something went wrong on the server."),
}


def error_code_for(exc: Exception) -> str:
    if isinstance(exc, LLMUnavailable):
        return "LLM_UNAVAILABLE"
    if isinstance(exc, LLMTimeout):
        return "LLM_TIMEOUT"
    if isinstance(exc, QuestionError):
        return "VALIDATION_ERROR"
    if isinstance(exc, OllamaError):
        return "INTERNAL_ERROR"
    return "INTERNAL_ERROR"


def api_error(code: str) -> ApiError:
    status, message = ERRORS[code]
    headers = {"Retry-After": "60"} if code == "QUEUE_FULL" else None
    return ApiError(status, code, message, headers=headers)


# ── what goes to the browser ─────────────────────────────────────────────────────────────

def public_source(s: SourceInfo) -> dict:
    """A source as the UI needs it (§16): no internal chunk id, hash or score."""
    return {"n": s.n, "doc_code": s.doc_code, "title": s.title, "version": s.version,
            "section": s.section, "section_title": s.section_title, "page": s.page,
            "text": s.text, "is_fictional": s.is_fictional}


def sse(name: str, data: dict) -> str:
    """One Server-Sent Event (§17)."""
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ── what goes to the audit trail ─────────────────────────────────────────────────────────

def query_payload(settings: Settings, index_build_id: str | None, conversation_id: str,
                  question: str, result: Result | None, *, completed: bool,
                  partial_answer: str = "") -> dict:
    """The QUERY event payload of §14.2."""
    base = {"conversation_id": conversation_id, "original_question": question,
            "completed": completed,
            "models": {"llm": settings.llm_model, "embedding": settings.embedding_model,
                       "reranker": settings.reranker_model},
            "index_build_id": index_build_id}
    if result is None:  # the client left before the answer was finished
        return base | {"standalone_question": None, "answer": partial_answer,
                       "answer_type": None, "sources": [], "reranker_scores": [],
                       "top_score": None, "citation_check": None, "latency_ms": {}}
    return base | {
        "standalone_question": result.standalone_question, "answer": result.answer,
        "answer_type": result.answer_type,
        "sources": [{"n": s.n, "chunk_id": s.chunk_id, "doc_code": s.doc_code,
                     "version": s.version, "sha256": s.sha256, "section": s.section,
                     "page": s.page} for s in result.sources],  # AUD-04
        "reranker_scores": [s.score for s in result.sources], "top_score": result.top_score,
        "citation_check": result.citation_check.as_dict() if result.citation_check else None,
        "latency_ms": result.latency_ms, "llm": result.llm, "truncated": result.truncated,
        "rewrite_failed": result.rewrite_failed}


def write_query_audit(db: Database, actor: Actor, payload: dict) -> AuditEntry:
    with db.write() as conn:
        return log(conn, "QUERY", actor, payload)


def write_failed_audit(db: Database, actor: Actor, conversation_id: str | None, question: str,
                       error_code: str) -> AuditEntry:
    with db.write() as conn:
        return log(conn, "QUERY_FAILED", actor, {
            "conversation_id": conversation_id, "original_question": question,
            "error_code": error_code})


# ── the queue ────────────────────────────────────────────────────────────────────────────

async def acquire_turn(queue: LLMQueue, ticket: Ticket) -> None:
    """Wait (no events to send) until it is this ticket's turn, then take the slot."""
    while not ticket.ready:
        await queue.changed(KEEPALIVE_SECONDS)
    queue.start(ticket)


# ── the streaming endpoint's generator ───────────────────────────────────────────────────

async def event_stream(*, ticket: Ticket, queue: LLMQueue, pipeline, db: Database,
                       actor: Actor, settings: Settings, index_build_id: str | None,
                       question: str, conversation_id: str, load_history: Callable,
                       keepalive: float = KEEPALIVE_SECONDS) -> AsyncIterator[str]:
    """Server-Sent Events for one question: queued → status → sources → token… → done.

    On a failure: a QUERY_FAILED record and an `error` event instead of `done`.
    If the client leaves, Starlette cancels this generator; the `finally` block then stops
    the model, gives the queue place back and records the question with completed=false.
    """
    tokens: list[str] = []
    result: Result | None = None
    pump: asyncio.Task | None = None
    finished = False  # `done` or `error` was produced: nothing is left to record

    def payload(completed: bool) -> dict:
        return query_payload(settings, index_build_id, conversation_id, question, result,
                             completed=completed, partial_answer="".join(tokens))

    try:
        last_position = None
        while not ticket.ready:
            if ticket.position != last_position:
                last_position = ticket.position
                yield sse("queued", {"position": last_position})
            if not await queue.changed(keepalive):
                yield ": keep-alive\n\n"
        queue.start(ticket)

        history = await asyncio.to_thread(load_history)
        events: asyncio.Queue = asyncio.Queue()

        async def run_pipeline() -> None:
            try:
                async for event in pipeline.stream(question, history):
                    await events.put(event)
                await events.put(None)
            except Exception as exc:  # handed to the consumer below, which reports it
                await events.put(exc)

        pump = asyncio.create_task(run_pipeline())
        while True:
            try:
                item = await asyncio.wait_for(events.get(), keepalive)
            except TimeoutError:
                yield ": keep-alive\n\n"  # still waiting for the model (§17)
                continue
            if item is None:
                break
            if isinstance(item, Exception):
                raise item
            if isinstance(item, Status):
                yield sse("status", {"stage": item.stage})
            elif isinstance(item, SourcesReady):
                yield sse("sources", {"sources": [public_source(s) for s in item.sources]})
            elif isinstance(item, TokenEvent):
                tokens.append(item.text)
                yield sse("token", {"t": item.text})
            elif isinstance(item, Done):
                result = item.result

        try:  # the record comes BEFORE `done`: no audit record, no answer (§17)
            entry = await asyncio.to_thread(write_query_audit, db, actor, payload(True))
        except Exception:
            log_.error("audit_write_failed", request_id=actor.request_id, exc_info=True)
            finished = True
            yield sse("error", error_data("AUDIT_WRITE_FAILED", actor.request_id))
            return
        finished = True
        yield sse("done", {"event_id": entry.event_id, "conversation_id": conversation_id,
                           "answer_type": result.answer_type,
                           "standalone_question": result.standalone_question,
                           "citation_check": (result.citation_check.as_dict()
                                              if result.citation_check else None),
                           "latency_ms": result.latency_ms})
    except Exception as exc:  # a failure, not a disconnect (those are BaseException)
        finished = True
        code = error_code_for(exc)
        if code == "INTERNAL_ERROR":
            log_.error("query_failed", request_id=actor.request_id, exc_info=exc)
        try:
            await asyncio.to_thread(write_failed_audit, db, actor, conversation_id, question,
                                    code)
        except Exception:
            code = "AUDIT_WRITE_FAILED"
        yield sse("error", error_data(code, actor.request_id))
    finally:
        if pump is not None and not pump.done():
            pump.cancel()  # stop generating: frees the CPU for the next person
        queue.release(ticket)
        if not finished:  # the client disconnected (CancelledError / GeneratorExit)
            try:  # synchronous on purpose: awaiting inside a cancelled task is unreliable
                write_query_audit(db, actor, payload(False))
            except Exception:
                log_.error("abandoned_query_not_recorded", request_id=actor.request_id,
                           exc_info=True)


def error_data(code: str, request_id: str | None) -> dict:
    return {"code": code, "message": ERRORS[code][1], "request_id": request_id}
