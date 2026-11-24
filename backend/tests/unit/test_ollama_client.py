"""Ollama client against the fake server (PROJECT_SPEC §9.1, §15.6)."""

import httpx
import pytest

from config import Settings
from src.generation.ollama_client import LLMTimeout, LLMUnavailable, OllamaClient, OllamaError
from tests.fakes.fake_ollama import FakeOllama

SETTINGS = Settings(_env_file=None, jwt_secret_key="x" * 64)


def make(fake: FakeOllama) -> OllamaClient:
    return OllamaClient(SETTINGS, transport=fake.transport())


async def test_chat_returns_full_text_and_stats():
    fake = FakeOllama(answer="Retesting needs a plan [1].")
    text, stats = await make(fake).chat("system", "question", max_tokens=400)
    assert text == "Retesting needs a plan [1]."
    assert (stats.prompt_tokens, stats.completion_tokens) == (1200, 40)
    assert stats.tokens_per_second == pytest.approx(4.0)
    assert stats.done_reason == "stop"


async def test_stream_yields_pieces_in_order():
    fake = FakeOllama(answer="one two three")
    pieces = [p async for p in make(fake).chat_stream("s", "q", 400)]
    assert len(pieces) == 3 and "".join(pieces) == "one two three"


async def test_every_call_sends_num_ctx_4096_and_the_configured_options():
    fake = FakeOllama()
    client = make(fake)
    await client.chat("s", "q", max_tokens=400)
    await client.chat("s", "q", max_tokens=64)
    assert len(fake.requests) == 2
    for body in fake.requests:  # §9.1: never rely on Ollama's default context
        assert body["options"]["num_ctx"] == 4096
        assert body["model"] == "llama3.1:8b"
        assert body["keep_alive"] == "30m"
        assert body["options"]["temperature"] == 0.1
        assert body["options"]["top_p"] == 0.9
        assert body["options"]["repeat_penalty"] == 1.1
    assert [b["options"]["num_predict"] for b in fake.requests] == [400, 64]


async def test_preload_also_sets_num_ctx():
    fake = FakeOllama()
    await make(fake).preload()
    assert fake.generate_calls[0]["options"]["num_ctx"] == 4096
    assert fake.generate_calls[0]["keep_alive"] == "30m"


async def test_ollama_down_gives_a_clear_error_with_the_url():
    fake = FakeOllama()
    fake.fail = httpx.ConnectError("refused")
    with pytest.raises(LLMUnavailable, match=r"http://127\.0\.0\.1:11434"):
        await make(fake).chat("s", "q", 400)


async def test_read_timeout_becomes_llm_timeout():
    fake = FakeOllama()
    fake.fail = httpx.ReadTimeout("slow")
    with pytest.raises(LLMTimeout, match="180"):
        await make(fake).chat("s", "q", 400)


async def test_missing_model_tells_you_how_to_pull_it():
    fake = FakeOllama()
    fake.status = 404
    with pytest.raises(LLMUnavailable, match="ollama pull llama3.1:8b"):
        await make(fake).chat("s", "q", 400)


async def test_other_http_errors_are_ollama_errors():
    fake = FakeOllama()
    fake.status = 500
    with pytest.raises(OllamaError, match="500"):
        await make(fake).chat("s", "q", 400)


async def test_error_codes_match_the_api_spec():
    assert LLMUnavailable.code == "LLM_UNAVAILABLE" and LLMTimeout.code == "LLM_TIMEOUT"


async def test_ping_and_loaded_models():
    fake = FakeOllama()
    client = make(fake)
    assert await client.ping() is True
    assert (await client.loaded_models())[0]["name"] == "llama3.1:8b"
    fake.fail = httpx.ConnectError("down")
    assert await client.ping() is False
    assert await client.loaded_models() == []


async def test_unload_sends_keep_alive_zero():
    fake = FakeOllama()
    await make(fake).unload()
    assert fake.generate_calls[0]["keep_alive"] == 0
    fake.fail = httpx.ConnectError("down")
    with pytest.raises(LLMUnavailable):
        await make(fake).unload()
