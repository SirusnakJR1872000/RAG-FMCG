"""Asking questions: blocking and streaming endpoints (PROJECT_SPEC §9.4, §14.2, §16, §17).

Covers FR-01..FR-06, FR-08, AUD-01, AUD-04, AUD-05, SEC-10 with a scripted pipeline.
"""

import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from sqlalchemy import select

from audit.writer import Actor
from config import Settings
from database.models import audit_log
from services import query_service
from services.llm_queue import LLMQueue
from services.query_service import event_stream
from src.generation.ollama_client import LLMTimeout, LLMUnavailable
from tests.conftest import ORIGIN, PASSWORD, add_user, sign_in
from tests.fakes.fake_pipeline import FakePipeline

QUESTION = "What must happen after an out-of-specification result?"


def audit_events(app_or_client, event_type):
    app = getattr(app_or_client, "app", app_or_client)
    with app.state.db.read() as conn:
        rows = conn.execute(select(audit_log).where(audit_log.c.event_type == event_type)
                            .order_by(audit_log.c.seq)).mappings().all()
    return [{**r, "payload": json.loads(r["payload_json"])} for r in rows]


def ask(client, headers, question=QUESTION, **extra):
    return client.post("/api/query", headers=headers, json={"question": question, **extra})


def read_events(response):
    """Parse a text/event-stream body into [(event, data)] and a count of keep-alive comments."""
    events, name, keepalives = [], None, 0
    for line in response.iter_lines():
        if line.startswith(":"):
            keepalives += 1
        elif line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            events.append((name, json.loads(line[5:])))
    return events, keepalives


def stream(client, headers, question=QUESTION, **extra):
    with client.stream("POST", "/api/query/stream", headers=headers,
                       json={"question": question, **extra}) as response:
        assert response.status_code == 200, response.read()
        return read_events(response)[0], response


# ── blocking endpoint ────────────────────────────────────────────────────────────────────

def test_a_question_gets_a_cited_answer_in_the_shape_of_the_spec(client, make_headers):
    response = ask(client, make_headers("viewer"))
    body = response.json()
    assert response.status_code == 200
    assert body["answer_type"] == "answered" and body["answer"].startswith("OOS results")
    assert body["event_id"].startswith("evt_") and body["timestamp_utc"].endswith("Z")
    assert body["standalone_question"] and body["citation_check"] == {
        "status": "ok", "invalid": [], "uncited": False}
    assert set(body["latency_ms"]) >= {"retrieval", "rerank", "ttft", "total"}
    first, second = body["sources"]
    assert set(first) == {"n", "doc_code", "title", "version", "section", "section_title",
                          "page", "text", "is_fictional"}  # no hash, chunk id or score
    assert (first["n"], first["doc_code"], first["is_fictional"], first["page"]) == (
        1, "ICH-Q7", False, 29)
    assert (second["n"], second["is_fictional"], second["page"]) == (2, True, None)


def test_AUD_01_AUD_04_the_query_event_records_the_answer_and_the_exact_sources(client,
                                                                              make_headers):
    body = ask(client, make_headers("viewer")).json()
    (event,) = audit_events(client, "QUERY")
    payload = event["payload"]
    assert event["event_id"] == body["event_id"] and event["username"] == "viewer_user"
    assert (event["role"], event["client_ip"]) == ("viewer", "testclient")
    assert payload["original_question"] == QUESTION and payload["completed"] is True
    assert payload["answer"] == body["answer"] and payload["answer_type"] == "answered"
    assert payload["conversation_id"] == body["conversation_id"]
    assert payload["sources"][0] == {"n": 1, "chunk_id": "ICH-Q7:v1:11.1:000",
                                     "doc_code": "ICH-Q7", "version": "Step 4, 10 Nov 2000",
                                     "sha256": "ab" * 32, "section": "11.1", "page": 29}
    assert payload["reranker_scores"] == [4.0, 3.0] and payload["top_score"] == 4.2
    assert payload["models"]["llm"] == "llama3.1:8b" and payload["index_build_id"] == "build-test-1"
    assert payload["citation_check"]["status"] == "ok" and payload["latency_ms"]["total"] == 30000
    assert "passage" not in event["payload_json"].lower()  # passage text is not duplicated


def test_FR_01_the_question_must_be_3_to_1000_characters(client, make_headers, pipeline):
    headers = make_headers("viewer")
    for bad in ("ab", "x" * 1001, ""):
        assert ask(client, headers, bad).status_code == 422, len(bad)
    assert client.post("/api/query", headers=headers, json={}).status_code == 422
    assert client.post("/api/query", headers=headers,
                       json={"question": QUESTION, "top_k": 50}).status_code == 422  # not settable
    assert ask(client, headers, "abc").status_code == 200 and ask(client, headers, "x" * 1000
                                                                   ).status_code == 200
    assert len(pipeline.calls) == 2


def test_SEC_01_SEC_02_only_roles_with_query_run_may_ask(client, make_headers, pipeline):
    assert client.post("/api/query", json={"question": QUESTION}).status_code == 401
    assert ask(client, make_headers("auditor")).status_code == 403  # reviewers cannot query
    assert pipeline.calls == []  # the pipeline was never reached
    assert [e["payload"]["permission"] for e in audit_events(client, "ACCESS_DENIED")] \
        == ["query:run"]
    for role in ("viewer", "qa_user", "admin"):
        assert ask(client, make_headers(role)).status_code == 200


def test_a_retrieval_refusal_has_no_sources_and_is_recorded(settings, make_client):
    pipeline = FakePipeline(settings, answer_type="retrieval_refusal")
    client = make_client(pipeline_=pipeline)
    add_user(client, "vera")
    body = ask(client, sign_in(client, "vera")).json()
    assert body["answer_type"] == "retrieval_refusal" and body["sources"] == []
    assert body["answer"] == "The approved documents don't cover this question."
    (event,) = audit_events(client, "QUERY")
    assert event["payload"]["answer_type"] == "retrieval_refusal"
    assert event["payload"]["sources"] == [] and event["payload"]["citation_check"] is None


# ── conversations and follow-ups ─────────────────────────────────────────────────────────

def test_a_conversation_can_be_created_and_a_question_creates_one_if_none_is_given(
        client, make_headers):
    headers = make_headers("viewer")
    created = client.post("/api/conversations", headers=headers)
    assert created.status_code == 201 and created.json()["id"].startswith("c_")
    first = ask(client, headers, conversation_id=created.json()["id"]).json()
    assert first["conversation_id"] == created.json()["id"]
    assert ask(client, headers).json()["conversation_id"] != first["conversation_id"]


def test_FR_06_follow_ups_get_the_last_two_exchanges_of_the_same_conversation(
        client, make_headers, pipeline):
    headers = make_headers("viewer")
    conversation = client.post("/api/conversations", headers=headers).json()["id"]
    for question in ("First question here?", "Second question here?", "Third question here?",
                     "Fourth question here?"):
        assert ask(client, headers, question, conversation_id=conversation).status_code == 200
    histories = [[(e.question, e.answer[:7]) for e in call[1]] for call in pipeline.calls]
    assert histories[0] == []
    assert histories[1] == [("First question here?", "OOS res")]
    assert [q for q, _ in histories[3]] == ["Second question here?", "Third question here?"]
    other = ask(client, headers, "A new topic entirely?").json()["conversation_id"]
    assert pipeline.calls[-1][1] == [] and other != conversation  # no history across conversations


def test_a_conversation_of_another_user_or_an_unknown_one_is_not_found(client, make_headers,
                                                                       pipeline):
    mine = client.post("/api/conversations", headers=make_headers("viewer")).json()["id"]
    for conversation in (mine, "c_doesnotexist"):
        response = ask(client, make_headers("qa_user"), conversation_id=conversation)
        assert (response.status_code, response.json()["error"]["code"]) \
            == (404, "CONVERSATION_NOT_FOUND")
    assert pipeline.calls == []


# ── failures ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("error", "status", "code"), [
    (LLMUnavailable("down"), 503, "LLM_UNAVAILABLE"),
    (LLMTimeout("slow"), 504, "LLM_TIMEOUT"),
])
def test_a_model_failure_gives_503_or_504_and_is_recorded_as_a_failed_query(
        settings, make_client, error, status, code):
    client = make_client(pipeline_=FakePipeline(settings, fail=error))
    add_user(client, "vera")
    response = ask(client, sign_in(client, "vera"))
    assert (response.status_code, response.json()["error"]["code"]) == (status, code)
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
    (failed,) = audit_events(client, "QUERY_FAILED")
    assert failed["payload"]["error_code"] == code and failed["payload"]["original_question"]
    assert audit_events(client, "QUERY") == []


def test_without_a_search_index_a_question_is_503_index_not_ready_and_recorded(make_client):
    client = make_client(pipeline_=None)
    add_user(client, "vera")
    response = ask(client, sign_in(client, "vera"))
    assert (response.status_code, response.json()["error"]["code"]) == (503, "INDEX_NOT_READY")
    assert audit_events(client, "QUERY_FAILED")[0]["payload"]["error_code"] == "INDEX_NOT_READY"


def test_an_unexpected_pipeline_error_is_a_500_without_details_and_still_recorded(
        settings, make_client):
    client = make_client(pipeline_=FakePipeline(settings, fail=RuntimeError("internal /secret")))
    add_user(client, "vera")
    response = ask(client, sign_in(client, "vera"))
    assert response.status_code == 500 and "internal" not in response.text
    assert audit_events(client, "QUERY_FAILED")[0]["payload"]["error_code"] == "INTERNAL_ERROR"


def test_AUD_01_if_the_audit_write_fails_the_answer_is_not_delivered(client, make_headers,
                                                                    monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(query_service, "write_query_audit", broken)
    monkeypatch.setattr("routers.query.write_query_audit", broken)
    response = ask(client, make_headers("viewer"))
    assert response.status_code == 500 and response.json()["error"]["code"] == "AUDIT_WRITE_FAILED"
    assert "OOS results" not in response.text  # no audit record, no answer


def test_SEC_10_questions_are_rate_limited_per_user(settings, make_client):
    client = make_client(settings.model_copy(update={"rate_limit_query": "2/minute"}))
    add_user(client, "vera")
    add_user(client, "walt")
    vera, walt = sign_in(client, "vera"), sign_in(client, "walt")
    assert [ask(client, vera).status_code for _ in range(3)] == [200, 200, 429]
    assert ask(client, walt).status_code == 200  # another user has their own allowance
    limited = ask(client, vera)
    assert limited.json()["error"]["code"] == "RATE_LIMITED"


# ── streaming endpoint ───────────────────────────────────────────────────────────────────

def test_FR_02_FR_03_the_stream_sends_status_then_sources_then_tokens_then_done(client,
                                                                               make_headers):
    events, response = stream(client, make_headers("viewer"))
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    names = [name for name, _ in events]
    assert names[:3] == ["status", "status", "sources"]  # sources BEFORE any token (FR-03)
    assert [d["stage"] for n, d in events if n == "status"] == [
        "retrieving", "reranking", "generating"]
    assert names.index("sources") < names.index("token") and names[-1] == "done"
    assert names.count("done") == 1 and "error" not in names
    tokens = "".join(d["t"] for n, d in events if n == "token")
    done = events[-1][1]
    assert tokens.strip().startswith("OOS results") and done["answer_type"] == "answered"
    assert done["citation_check"]["status"] == "ok" and done["latency_ms"]["total"] == 30000
    assert dict(events)["sources"]["sources"][0]["doc_code"] == "ICH-Q7"


def test_the_query_is_recorded_before_done_is_sent(client, make_headers):
    headers = make_headers("viewer")
    with client.stream("POST", "/api/query/stream", headers=headers,
                       json={"question": QUESTION}) as response:
        seen_before_done = None
        name = None
        for line in response.iter_lines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:") and name == "done":
                event_id = json.loads(line[5:])["event_id"]
                seen_before_done = [e["event_id"] for e in audit_events(client, "QUERY")]
    assert seen_before_done == [event_id]  # §17: the audit event is written before `done`


def test_the_stream_for_a_refusal_has_empty_sources_and_no_tokens(settings, make_client):
    client = make_client(pipeline_=FakePipeline(settings, answer_type="retrieval_refusal"))
    add_user(client, "vera")
    events, _ = stream(client, sign_in(client, "vera"))
    names = [n for n, _ in events]
    assert "token" not in names and names[-1] == "done"
    assert dict(events)["sources"] == {"sources": []}
    assert events[-1][1]["answer_type"] == "retrieval_refusal"


def test_a_failure_during_the_stream_ends_with_an_error_event_and_a_failed_record(
        settings, make_client):
    client = make_client(pipeline_=FakePipeline(settings, fail=LLMTimeout("slow")))
    add_user(client, "vera")
    events, _ = stream(client, sign_in(client, "vera"))
    names = [n for n, _ in events]
    assert names[-1] == "error" and "done" not in names
    error = events[-1][1]
    assert error["code"] == "LLM_TIMEOUT" and error["request_id"].startswith("req_")
    assert "Traceback" not in json.dumps(error)
    assert audit_events(client, "QUERY_FAILED")[0]["payload"]["error_code"] == "LLM_TIMEOUT"
    assert audit_events(client, "QUERY") == []


def test_AUD_01_a_stream_whose_audit_write_fails_ends_with_error_not_done(client, make_headers,
                                                                         monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(query_service, "write_query_audit", broken)
    events, _ = stream(client, make_headers("viewer"))
    names = [n for n, _ in events]
    assert names[-1] == "error" and "done" not in names
    assert events[-1][1]["code"] == "AUDIT_WRITE_FAILED"  # the UI hides the answer (state 10)


def test_stream_requests_are_checked_like_blocking_ones(client, make_headers, pipeline):
    body = {"question": QUESTION}
    assert client.post("/api/query/stream", json=body).status_code == 401
    assert client.post("/api/query/stream", headers=make_headers("auditor"), json=body
                       ).status_code == 403
    assert client.post("/api/query/stream", headers=make_headers("viewer"),
                       json={"question": "x"}).status_code == 422
    assert pipeline.calls == []


# ── disconnects, the queue and keep-alives (driving the generator directly) ──────────────

class StreamEnv:
    """Everything `event_stream` needs, built around a real database and queue."""

    def __init__(self, app, pipeline, queue, user="viewer_user"):
        add_user(app, user)
        self.app, self.pipeline, self.queue = app, pipeline, queue
        with app.state.db.read() as conn:
            from auth import service

            row = service.get_user_by_username(conn, user)
        self.actor = Actor(row["id"], user, "viewer", "10.0.0.9", "req_stream")

    def stream(self, keepalive=15.0, ticket=None):
        return event_stream(
            ticket=ticket or self.queue.join(), queue=self.queue, pipeline=self.pipeline,
            db=self.app.state.db, actor=self.actor, settings=self.app.state.settings,
            index_build_id="build-test-1", question=QUESTION, conversation_id="c_direct",
            load_history=lambda: [], keepalive=keepalive)


@pytest.fixture
def env(client, pipeline):
    return StreamEnv(client.app, pipeline, LLMQueue(10))


async def test_a_client_that_disconnects_mid_stream_is_recorded_as_not_completed(env):
    generator = env.stream()
    seen = []
    async for chunk in generator:
        seen.append(chunk)
        if chunk.startswith("event: token"):  # got the first words, then the client leaves
            break
    await generator.aclose()
    (event,) = audit_events(env.app, "QUERY")
    assert event["payload"]["completed"] is False and event["payload"]["answer"].startswith("OOS")
    assert event["payload"]["original_question"] == QUESTION
    assert not env.queue.busy and env.pipeline.active == 0  # slot freed, generation stopped
    assert audit_events(env.app, "QUERY_FAILED") == []


async def test_a_client_that_leaves_while_still_queued_is_recorded_and_frees_its_place(env):
    blocker = env.queue.join()
    env.queue.start(blocker)  # someone else is running
    generator = env.stream()
    first = await generator.__anext__()
    assert first == 'event: queued\ndata: {"position": 1}\n\n'
    await generator.aclose()
    assert env.queue.depth == 0  # it left the line
    (event,) = audit_events(env.app, "QUERY")
    assert event["payload"]["completed"] is False and event["payload"]["answer"] == ""
    assert env.pipeline.calls == []


async def test_waiting_in_the_queue_sends_position_updates_and_keep_alives(env):
    blocker = env.queue.join()
    env.queue.start(blocker)
    second = env.queue.join()
    third_stream = env.stream(keepalive=0.02)  # joins behind `second`
    chunks = []

    async def consume():
        async for chunk in third_stream:
            chunks.append(chunk)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.15)  # long enough for several keep-alive intervals
    assert chunks[0] == 'event: queued\ndata: {"position": 2}\n\n'
    assert chunks.count(": keep-alive\n\n") >= 2
    env.queue.release(blocker)  # the line moves: now position 1
    await asyncio.sleep(0.05)
    assert 'event: queued\ndata: {"position": 1}\n\n' in chunks
    env.queue.start(second)
    env.queue.release(second)  # and now it is this stream's turn
    await asyncio.wait_for(task, 5)
    assert chunks[-1].startswith("event: done")


async def test_keep_alives_are_sent_while_waiting_for_the_model(settings, env):
    env.pipeline.delay = 0.2  # the model is slow to start
    chunks = [c async for c in env.stream(keepalive=0.03)]
    assert chunks.count(": keep-alive\n\n") >= 2 and chunks[-1].startswith("event: done")


# ── concurrency through the real app (async client) ──────────────────────────────────────

@asynccontextmanager
async def running(app):
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url=ORIGIN) as client:
            yield client


async def test_FR_questions_run_one_at_a_time_and_a_full_queue_gets_429(settings, tmp_path):
    from api import create_app

    cfg: Settings = settings.model_copy(update={"llm_queue_max": 1})
    pipeline = FakePipeline(cfg, delay=0.3)
    app = create_app(cfg, pipeline=pipeline)
    async with running(app) as http:
        for name in ("ann", "bob", "cy"):
            add_user(app, name)
        tokens = {}
        for name in ("ann", "bob", "cy"):
            response = await http.post("/api/auth/login",
                                       json={"username": name, "password": PASSWORD})
            tokens[name] = {"Authorization": f"Bearer {response.json()['access_token']}"}

        async def go(name):
            return await http.post("/api/query", headers=tokens[name], json={"question": QUESTION})

        first = asyncio.create_task(go("ann"))
        await asyncio.sleep(0.05)
        second = asyncio.create_task(go("bob"))  # waits: 1 place in the queue
        await asyncio.sleep(0.05)
        third = await go("cy")  # no place left
        assert third.status_code == 429 and third.json()["error"]["code"] == "QUEUE_FULL"
        assert third.headers["retry-after"] == "60"
        assert (await first).status_code == 200 and (await second).status_code == 200
    assert pipeline.max_active == 1  # never two at once
    (failed,) = audit_events(app, "QUERY_FAILED")  # and the refused one is on record
    assert failed["payload"]["error_code"] == "QUEUE_FULL" and failed["username"] == "cy"
