"""Follow-up rewrite (PROJECT_SPEC §8.2 step 1, §9.5)."""

import httpx

from config import Settings
from src.generation.ollama_client import OllamaClient
from src.generation.prompts import Exchange
from src.generation.rewriter import clean_rewrite, rewrite_question
from tests.fakes.fake_ollama import FakeOllama

SETTINGS = Settings(_env_file=None, jwt_secret_key="x" * 64)
HISTORY = [Exchange("What is a CAPA?", "A corrective and preventive action [1]."),
           Exchange("When is it raised?", "After a confirmed cause [2].")]


def client(fake):
    return OllamaClient(SETTINGS, transport=fake.transport())


async def test_no_history_means_no_llm_call():
    fake = FakeOllama()
    result = await rewrite_question(client(fake), "What is a CAPA?", [], turns=2, max_tokens=64)
    assert (result.question, result.rewritten, result.failed) == ("What is a CAPA?", False, False)
    assert fake.requests == []


async def test_follow_up_is_rewritten_with_the_small_token_cap():
    fake = FakeOllama(rewrite="Who approves a CAPA at Acme?")
    result = await rewrite_question(client(fake), "who approves it?", HISTORY, 2, 64)
    assert (result.question, result.rewritten) == ("Who approves a CAPA at Acme?", True)
    assert len(fake.rewrite_calls) == 1 and fake.answer_calls == []
    assert fake.rewrite_calls[0]["options"]["num_predict"] == 64
    assert fake.rewrite_calls[0]["options"]["num_ctx"] == 4096


async def test_only_the_last_turns_are_used():
    fake = FakeOllama()
    await rewrite_question(client(fake), "and then?", HISTORY, turns=1, max_tokens=64)
    prompt = fake.rewrite_calls[0]["messages"][1]["content"]
    assert "When is it raised?" in prompt and "What is a CAPA?" not in prompt


async def test_failure_falls_back_to_the_original_question():
    fake = FakeOllama()
    fake.fail_rewrite = httpx.ReadTimeout("slow")
    result = await rewrite_question(client(fake), "who approves it?", HISTORY, 2, 64)
    assert (result.question, result.rewritten, result.failed) == ("who approves it?", False, True)


async def test_rambling_output_is_not_used():
    fake = FakeOllama(rewrite="x" * 400)
    result = await rewrite_question(client(fake), "who approves it?", HISTORY, 2, 64)
    assert (result.question, result.failed) == ("who approves it?", True)


def test_clean_rewrite():
    assert clean_rewrite('Standalone question: "Who approves a CAPA?"\nExplanation...') \
        == "Who approves a CAPA?"
    assert clean_rewrite("  \n  ") == ""


async def test_rewrite_that_copies_source_labels_is_rejected():
    # the real failure seen with llama3.1:8b: labels from the previous answer leaked in
    bad = ("What is the time frame allowed by ACME-SOP-QC-007 §1 Purpose (v3.0) and "
           "ICH-Q7 §11.15 for the initial investigation?")
    fake = FakeOllama(rewrite=bad)
    result = await rewrite_question(client(fake), "how long does Acme allow for it?",
                                    HISTORY, 2, 64)
    assert (result.question, result.failed) == ("how long does Acme allow for it?", True)


def test_label_detection():
    from src.generation.rewriter import introduces_source_labels as bad

    assert bad("What does §11.15 say?", "what does it say?")
    assert bad("What does the SOP say [1]?", "what does it say?")
    assert bad("What is required (v3.0)?", "what is required?")
    assert bad("What does ICH-Q7 require for OOS?", "what does it require for OOS?")
    assert not bad("What does ICH-Q7 require for OOS?", "what does ICH-Q7 require for it?")
    assert not bad("What does ICH Q7 say about reprocessing?", "and reprocessing?")
    assert not bad("Who approves a CAPA at Acme?", "who approves it?")
