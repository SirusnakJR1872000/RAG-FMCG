"""Follow-up rewrite (PROJECT_SPEC §8.2 step 1, §9.5)."""

import httpx
import pytest

from config import Settings
from src.generation.ollama_client import OllamaClient
from src.generation.prompts import Exchange
from src.generation.rewriter import (
    clean_rewrite,
    needs_context,
    rewrite_question,
    should_rewrite,
)
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


@pytest.mark.parametrize("question", [
    "How long does Acme allow for the first laboratory investigation of it?",
    "And when does a CAPA have to be raised in that case?",
    "who approves it?", "What about retesting?", "and then?", "Why?",
    "Does that apply to contract labs too?", "Is the same true for the SOP?",
])
def test_questions_that_depend_on_the_conversation_are_rewritten(question):
    assert needs_context(question)


@pytest.mark.parametrize("question", [
    "What does Annex 11 say about audit trails?",
    "How many working days does Acme allow for the first laboratory investigation?",
    "Who has to approve the retest plan?",
    "What are the three stages of process validation in the FDA guidance?",
    "Which records must be kept for a batch after release?",
])
def test_self_contained_questions_are_searched_as_typed(question):
    assert not needs_context(question)


def test_a_reference_word_only_counts_as_a_whole_word():
    assert not needs_context("Which specifications apply to the withdrawal of intermediates?")


def test_should_rewrite_needs_history_and_a_dependent_question():
    assert should_rewrite("who approves it?", HISTORY, 2)
    assert not should_rewrite("who approves it?", [], 2)  # no history
    assert not should_rewrite("who approves it?", HISTORY, 0)  # history turned off
    assert not should_rewrite("What does Annex 11 say about audit trails?", HISTORY, 2)


async def test_a_self_contained_question_makes_no_llm_call_even_with_history():
    fake = FakeOllama()
    q = "What does Annex 11 say about audit trails?"
    result = await rewrite_question(client(fake), q, HISTORY, 2, 64)
    assert (result.question, result.rewritten, result.failed) == (q, False, False)
    assert fake.requests == []
