"""Start-up, health, request ids and the error envelope (PROJECT_SPEC §14, §15.6, §16; SEC-12)."""

import json
import re

import pytest
from sqlalchemy import select

from database.models import audit_log
from tests.conftest import ORIGIN, add_user, sign_in


def events(client, event_type):
    with client.app.state.db.read() as conn:
        rows = conn.execute(select(audit_log).where(audit_log.c.event_type == event_type)
                            .order_by(audit_log.c.seq)).mappings().all()
    return [{**r, "payload": json.loads(r["payload_json"])} for r in rows]


# ── start-up ─────────────────────────────────────────────────────────────────────────────

def test_start_up_records_system_start_with_versions_models_and_the_chain_check(client):
    (start,) = events(client, "SYSTEM_START")
    payload = start["payload"]
    assert (start["username"], start["role"]) == ("system", "system")
    assert payload["app_version"] == "0.1.0" and payload["audit_verify"]["ok"] is True
    assert payload["models"] == {"llm": "llama3.1:8b", "embedding": "intfloat/e5-small-v2",
                                 "reranker": "cross-encoder/ms-marco-MiniLM-L-6-v2"}
    assert payload["index_build_id"] == "build-test-1" and payload["os_user"]
    assert re.fullmatch(r"[0-9a-f]{16}", payload["config_hash"])


def test_SEC_09_the_secret_never_appears_in_the_audit_trail(client):
    assert "k" * 64 not in events(client, "SYSTEM_START")[0]["payload_json"]


def test_a_tampered_chain_is_noticed_at_start_up_and_reported(settings, make_client):
    first = make_client()
    add_user(first, "someone")
    path = first.app.state.settings.sqlite_path
    first.__exit__(None, None, None)
    import sqlite3

    raw = sqlite3.connect(path, isolation_level=None)  # an attacker with file access
    raw.execute("DROP TRIGGER audit_no_update")
    raw.execute("UPDATE audit_log SET username = 'forged' WHERE seq = 2")
    raw.close()
    second = make_client()
    (_, restart) = events(second, "SYSTEM_START")
    assert restart["payload"]["audit_verify"]["ok"] is False
    assert restart["payload"]["audit_verify"]["first_bad_seq"] == 2
    admin = add_user(second, "root", "admin")
    assert admin and second.get("/api/health").json() == {"status": "degraded"}
    details = second.get("/api/health/details", headers=sign_in(second, "root")).json()
    assert details["audit"]["ok"] is False and details["audit"]["first_bad_seq"] == 2


# ── health ───────────────────────────────────────────────────────────────────────────────

def test_health_is_public_and_reveals_only_a_status_word(client):
    response = client.get("/api/health")
    assert response.status_code == 200 and response.json() == {"status": "ready"}


def test_health_is_degraded_when_ollama_is_unreachable(client, pipeline):
    pipeline.client.reachable = False
    assert client.get("/api/health").json() == {"status": "degraded"}


def test_health_is_not_ready_without_a_search_index(make_client):
    client = make_client(pipeline_=None)  # no data/chunks.parquet in the temp dirs
    assert client.get("/api/health").json() == {"status": "not_ready"}


def test_the_llm_check_is_cached_between_polls(client, pipeline):
    client.get("/api/health")
    pipeline.client.reachable = False  # changes, but the answer is cached for 10 s
    assert client.get("/api/health").json() == {"status": "ready"}


def test_health_details_are_for_admins_only_and_a_refusal_is_audited(client, make_headers):
    viewer = make_headers("viewer")
    denied = client.get("/api/health/details", headers=viewer)
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "FORBIDDEN"
    (event,) = events(client, "ACCESS_DENIED")
    assert event["username"] == "viewer_user"
    assert event["payload"] == {"endpoint": "GET /api/health/details",
                                "permission": "health:details"}
    assert client.get("/api/health/details").status_code == 401  # no token at all


def test_health_details_show_the_state_and_never_a_secret(client, make_headers):
    body = client.get("/api/health/details", headers=make_headers("admin"))
    assert body.status_code == 200
    details = body.json()
    assert details["llm"] == {"reachable": True, "model": "llama3.1:8b", "loaded": True}
    assert details["index"]["build_id"] == "build-test-1" and details["index"]["chunk_count"] == 681
    assert details["audit"]["ok"] is True and details["disk"]["free_gb"] > 0
    assert details["version"]["app"] == "0.1.0" and "documents" in details
    assert "k" * 64 not in body.text and "secret" not in body.text.lower()


# ── request ids and the error envelope ───────────────────────────────────────────────────

def test_every_response_has_a_request_id_and_errors_repeat_it(client):
    ok = client.get("/api/health")
    assert re.fullmatch(r"req_[0-9a-f]{6}", ok.headers["x-request-id"])
    bad = client.get("/api/me")
    assert bad.json()["error"]["request_id"] == bad.headers["x-request-id"]
    assert bad.headers["x-request-id"] != ok.headers["x-request-id"]


def test_unknown_paths_and_methods_use_the_same_envelope(client):
    missing = client.get("/api/nothing-here")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "NOT_FOUND"
    wrong = client.delete("/api/health")
    assert wrong.status_code == 405 and wrong.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


def test_a_validation_error_lists_the_fields_but_never_echoes_the_values(client):
    secret = "p" * 300  # too long: rejected, and must not come back in the response
    response = client.post("/api/auth/login", json={"username": "a", "password": secret})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR" and error["details"][0]["field"] == "password"
    assert secret not in response.text


def test_unknown_fields_are_rejected(client):
    response = client.post("/api/auth/login",
                           json={"username": "a", "password": "b", "admin": True})
    assert response.status_code == 422


def test_SEC_12_an_unexpected_error_returns_no_stack_trace(client):
    @client.app.get("/api/boom")
    def boom():
        raise RuntimeError("secret internal detail at /home/gaurav/app.py")

    response = client.get("/api/boom")
    assert response.status_code == 500 and response.json()["error"]["code"] == "INTERNAL_ERROR"
    for leak in ("secret internal detail", "Traceback", "/home/gaurav", "RuntimeError"):
        assert leak not in response.text
    assert re.fullmatch(r"req_[0-9a-f]{6}", response.json()["error"]["request_id"])


def test_the_openapi_description_is_served(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/api/auth/login", "/api/me", "/api/health"} <= set(paths)
    assert ORIGIN  # silence unused import in some configurations


@pytest.mark.parametrize("method", ["get", "post"])
def test_protected_paths_without_a_token_are_401(client, method):
    path = "/api/me" if method == "get" else "/api/auth/change-password"
    response = getattr(client, method)(path)
    assert response.status_code == 401 and response.json()["error"]["code"] == "NOT_AUTHENTICATED"
