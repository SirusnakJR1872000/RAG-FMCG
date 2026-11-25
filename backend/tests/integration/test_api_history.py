"""History (read from the audit trail) and feedback (PROJECT_SPEC §16; FR-07, FR-08)."""

import json

from sqlalchemy import insert, select, update

from audit.writer import Actor, log
from database.init_db import SYSTEM_USER_ID, new_id, utc_now
from database.models import audit_log, documents, feedback, users
from src.generation.ollama_client import LLMTimeout
from tests.conftest import add_user, sign_in
from tests.fakes.fake_pipeline import FakePipeline


def ask(client, headers, question, **extra):
    response = client.post("/api/query", headers=headers, json={"question": question, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def history(client, headers, **params):
    response = client.get("/api/history", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def rate(client, headers, event_id, rating=1, comment=None):
    return client.post("/api/feedback", headers=headers, json={
        "query_event_id": event_id, "rating": rating, "comment": comment})


# ── listing ──────────────────────────────────────────────────────────────────────────────

def test_FR_07_a_user_sees_their_own_questions_newest_first(client, make_headers):
    viewer, qa = make_headers("viewer"), make_headers("qa_user")
    ask(client, viewer, "First question about OOS?")
    ask(client, qa, "Someone else's question?")
    ask(client, viewer, "Second question about CAPA?")
    page = history(client, viewer)
    assert page["total"] == 2 and [i["question"] for i in page["items"]] == [
        "Second question about CAPA?", "First question about OOS?"]
    item = page["items"][0]
    assert item["result"] == "answered" and item["sources_count"] == 2
    assert item["feedback"] is None and item["time_taken_ms"] == 30000 and item["completed"]
    assert item["username"] == "viewer_user" and item["event_id"].startswith("evt_")


def test_the_result_column_distinguishes_answered_not_covered_failed_and_interrupted(
        settings, make_client):
    client = make_client(pipeline_=FakePipeline(settings, answer_type="retrieval_refusal"))
    add_user(client, "vera")
    headers = sign_in(client, "vera")
    ask(client, headers, "Something the documents do not cover?")
    client.app.state.index.pipeline.fail = None
    client.app.state.index.swap(FakePipeline(settings, fail=LLMTimeout("slow")))
    client.post("/api/query", headers=headers, json={"question": "This one will fail, sadly?"})
    with client.app.state.db.write() as conn:  # an interrupted stream, as a disconnect leaves it
        uid = conn.execute(select(users.c.id).where(users.c.username == "vera")).scalar()
        log(conn, "QUERY", Actor(uid, "vera", "viewer"), {
            "original_question": "Left half way through?", "completed": False, "sources": [],
            "answer": "OOS results", "conversation_id": "c_x"})
    results = {i["question"]: i["result"] for i in history(client, headers)["items"]}
    assert results == {"Something the documents do not cover?": "not_covered",
                       "This one will fail, sadly?": "failed",
                       "Left half way through?": "interrupted"}
    failed = [i for i in history(client, headers)["items"] if i["result"] == "failed"][0]
    assert failed["error_code"] == "LLM_TIMEOUT" and failed["sources_count"] == 0


def test_pagination_filters_and_text_search(client, make_headers):
    viewer = make_headers("viewer")
    conv = client.post("/api/conversations", headers=viewer).json()["id"]
    ask(client, viewer, "How is a CAPA raised?", conversation_id=conv)
    ask(client, viewer, "Is 100% of the data reviewed?")
    ask(client, viewer, "What is a PQR for Acme?")
    assert history(client, viewer, page_size=2)["items"][0]["question"] == "What is a PQR for Acme?"
    assert len(history(client, viewer, page_size=2)["items"]) == 2
    assert [i["question"] for i in history(client, viewer, page=2, page_size=2)["items"]] \
        == ["How is a CAPA raised?"]
    assert [i["question"] for i in history(client, viewer, conversation=conv)["items"]] \
        == ["How is a CAPA raised?"]
    assert [i["question"] for i in history(client, viewer, q="capa")["items"]] \
        == ["How is a CAPA raised?"]  # case-insensitive
    assert history(client, viewer, q="100%")["total"] == 1  # % is a character, not a wildcard
    assert history(client, viewer, q="_")["total"] == 0  # and so is _
    assert history(client, viewer, q="nothing like this")["total"] == 0


def test_date_filters_cover_whole_days(client, make_headers):
    viewer = make_headers("viewer")
    ask(client, viewer, "A question asked today?")
    today = utc_now()[:10]
    assert history(client, viewer, **{"from": today, "to": today})["total"] == 1
    assert history(client, viewer, **{"from": "2999-01-01"})["total"] == 0
    assert history(client, viewer, to="2000-01-01")["total"] == 0
    bad = client.get("/api/history", headers=viewer, params={"from": "yesterday"})
    assert bad.status_code == 422


def test_page_size_is_bounded(client, make_headers):
    for params in ({"page_size": 0}, {"page_size": 101}, {"page": 0}):
        assert client.get("/api/history", headers=make_headers("viewer"),
                          params=params).status_code == 422


# ── who sees whose ───────────────────────────────────────────────────────────────────────

def test_an_auditor_sees_everyones_history_and_an_admin_only_their_own_by_default(
        client, make_headers):
    viewer, qa, admin = make_headers("viewer"), make_headers("qa_user"), make_headers("admin")
    ask(client, viewer, "Question from the viewer?")
    ask(client, qa, "Question from the qa user?")
    ask(client, admin, "Question from the admin?")
    auditor = make_headers("auditor")
    assert history(client, auditor)["total"] == 3
    assert [i["username"] for i in history(client, auditor, user="qa_user_user")["items"]] \
        == ["qa_user_user"]
    assert history(client, admin)["total"] == 1  # an admin's own; everyone's is in Audit
    assert history(client, admin, user="viewer_user")["total"] == 1  # ...unless they ask
    assert history(client, viewer)["total"] == 1


def test_a_user_cannot_ask_for_somebody_elses_history_and_the_attempt_is_recorded(
        client, make_headers):
    viewer = make_headers("viewer")
    ask(client, make_headers("qa_user"), "Private question here?")
    response = client.get("/api/history", headers=viewer, params={"user": "qa_user_user"})
    assert response.status_code == 403
    with client.app.state.db.read() as conn:
        denied = conn.execute(select(audit_log.c.payload_json).where(
            audit_log.c.event_type == "ACCESS_DENIED")).scalar()
    assert json.loads(denied)["permission"] == "audit:read"


def test_history_needs_a_token_and_a_role_that_may_use_it(client):
    assert client.get("/api/history").status_code == 401


# ── detail ───────────────────────────────────────────────────────────────────────────────

def test_the_detail_shows_the_answer_the_sources_and_the_passages_as_they_were(client,
                                                                              make_headers):
    viewer = make_headers("viewer")
    event_id = ask(client, viewer, "How are OOS results handled?")["event_id"]
    with client.app.state.db.write() as conn:  # a registry in which ICH-Q7 has been replaced
        for code, version, status in (("ICH-Q7", "Step 4, 10 Nov 2000", "superseded"),
                                      ("ACME-SOP-QC-007", "3.0", "active")):
            conn.execute(insert(documents).values(
                id=new_id("d"), doc_code=code, title=code, version=version, file_path="f",
                sha256="ab" * 32, chunk_count=1, status=status, ingested_at=utc_now(),
                ingested_by=SYSTEM_USER_ID))
    detail = client.get(f"/api/history/{event_id}", headers=viewer).json()
    assert detail["question"] == "How are OOS results handled?"
    assert detail["answer"].startswith("OOS results") and detail["standalone_question"]
    assert detail["citation_check"]["status"] == "ok" and detail["models"]["llm"] == "llama3.1:8b"
    first, second = detail["sources"]
    assert first["text"] == "Passage 1 text." and first["title"] == "ICH-Q7 title"
    assert first["sha256"] == "ab" * 32 and first["version"] == "Step 4, 10 Nov 2000"
    assert (first["superseded"], second["superseded"]) == (True, False)  # "answered using v…"
    assert detail["feedback"] is None


def test_the_detail_is_for_the_owner_and_for_audit_readers_only(client, make_headers):
    event_id = ask(client, make_headers("viewer"), "A private question here?")["event_id"]
    path = f"/api/history/{event_id}"
    assert client.get(path, headers=make_headers("viewer")).status_code == 200
    assert client.get(path, headers=make_headers("auditor")).status_code == 200
    assert client.get(path, headers=make_headers("admin")).status_code == 200
    other = client.get(path, headers=make_headers("qa_user"))
    assert (other.status_code, other.json()["error"]["code"]) == (404, "NOT_FOUND")
    assert client.get("/api/history/evt_missing", headers=make_headers("viewer")).status_code == 404
    login_event = _first_event_of_type(client, "LOGIN_SUCCESS")  # not a question
    not_a_question = client.get(f"/api/history/{login_event}", headers=make_headers("admin"))
    assert not_a_question.status_code == 404


def _first_event_of_type(client, event_type):
    with client.app.state.db.read() as conn:
        return conn.execute(select(audit_log.c.event_id).where(
            audit_log.c.event_type == event_type)).scalar()


def test_a_detail_without_a_registry_does_not_claim_anything_about_versions(client, make_headers):
    viewer = make_headers("viewer")
    event_id = ask(client, viewer, "Anything at all here?")["event_id"]
    sources = client.get(f"/api/history/{event_id}", headers=viewer).json()["sources"]
    assert all(s["superseded"] is None for s in sources)


# ── feedback ─────────────────────────────────────────────────────────────────────────────

def test_FR_08_an_answer_can_be_rated_and_the_rating_shows_in_history(client, make_headers):
    viewer = make_headers("viewer")
    event_id = ask(client, viewer, "Was this helpful, then?")["event_id"]
    response = rate(client, viewer, event_id, 1, "Clear and cited.")
    assert response.status_code == 201 and response.json()["rating"] == 1
    assert history(client, viewer)["items"][0]["feedback"] == 1
    detail = client.get(f"/api/history/{event_id}", headers=viewer).json()
    assert detail["feedback"] == {"rating": 1, "comment": "Clear and cited."}
    with client.app.state.db.read() as conn:
        (event,) = conn.execute(select(audit_log.c.payload_json).where(
            audit_log.c.event_type == "FEEDBACK")).all()
    assert json.loads(event[0]) == {"query_event_id": event_id, "rating": 1,
                                    "comment": "Clear and cited."}


def test_rating_again_replaces_the_rating_there_is_only_one_per_answer(client, make_headers):
    viewer = make_headers("viewer")
    event_id = ask(client, viewer, "Changing my mind here?")["event_id"]
    first = rate(client, viewer, event_id, 1).json()["id"]
    second = rate(client, viewer, event_id, -1, "On reflection, no.").json()["id"]
    assert first == second
    with client.app.state.db.read() as conn:
        rows = conn.execute(select(feedback.c.rating, feedback.c.comment)).all()
    assert [tuple(r) for r in rows] == [(-1, "On reflection, no.")]
    assert history(client, viewer)["items"][0]["feedback"] == -1


def test_only_the_asker_can_rate_and_only_questions_not_other_events(client, make_headers):
    event_id = ask(client, make_headers("viewer"), "Whose answer is this?")["event_id"]
    assert rate(client, make_headers("qa_user"), event_id).status_code == 404
    login_event = _first_event_of_type(client, "LOGIN_SUCCESS")
    assert rate(client, make_headers("viewer"), login_event).status_code == 404
    assert rate(client, make_headers("viewer"), "evt_missing").status_code == 404
    assert rate(client, make_headers("auditor"), event_id).status_code == 403  # no query:run


def test_the_rating_and_comment_are_validated(client, make_headers):
    viewer = make_headers("viewer")
    event_id = ask(client, viewer, "Validate the rating here?")["event_id"]
    for rating in (0, 2, -2):
        assert rate(client, viewer, event_id, rating).status_code == 422
    assert rate(client, viewer, event_id, 1, "x" * 1001).status_code == 422
    assert rate(client, viewer, event_id, 1, "x" * 1000).status_code == 201
    assert client.post("/api/feedback", headers=viewer,
                       json={"query_event_id": event_id, "rating": 1, "extra": 1}
                       ).status_code == 422


def test_history_for_an_account_that_was_deactivated_stays_readable_by_auditors(
        client, make_headers):
    viewer = make_headers("viewer")
    ask(client, viewer, "A question before leaving?")
    with client.app.state.db.write() as conn:
        conn.execute(update(users).where(users.c.username == "viewer_user").values(is_active=0))
    assert client.get("/api/history", headers=viewer).status_code == 401
    assert history(client, make_headers("auditor"), user="viewer_user")["total"] == 1
