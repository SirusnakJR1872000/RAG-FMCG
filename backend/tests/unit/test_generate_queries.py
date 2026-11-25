"""Training-data generation: leakage control, parsing and filters (PROJECT_SPEC §10.2)."""

import json

import httpx
import pandas as pd
import pytest

from config import Settings
from src.evaluation.golden import Expected, GoldenItem, SectionTree
from src.finetuning.generate_queries import (
    MAX_WORDS,
    build_prompt,
    chat_with_retry,
    filter_questions,
    generate,
    leaked_chunk_ids,
    normalise,
    parse_questions,
    pick_chunks,
    read_raw,
)
from src.generation.ollama_client import LLMUnavailable, OllamaClient, OllamaError
from src.ingestion.sections import Section
from tests.fakes.fake_ollama import FakeOllama

# ── leakage control ──────────────────────────────────────────────────────────────────────

CHUNKS = pd.DataFrame({
    "chunk_id": ["Q7:11.14–11.16:0", "Q7:11.2:0", "Q7:12:0", "SOP:5.2:0", "SOP:5.2:1", "SOP:5.3:0",
                 "SOP:7:0"],
    "doc_code": ["ICH-Q7"] * 3 + ["ACME-SOP-QC-007"] * 4,
    "section": ["11.14–11.16", "11.2", "12", "5.2.1–5.2.3", "5.2.4", "5.3", "7"]})
TREES = {
    "ICH-Q7": SectionTree.from_sections([
        Section("11", "", None, True), Section("11.1", "", "11", True),
        Section("11.14", "", "11.1", False), Section("11.15", "", "11.1", False),
        Section("11.16", "", "11.1", False), Section("11.2", "", "11", True),
        Section("12", "", None, True)]),
    "ACME-SOP-QC-007": SectionTree.from_sections([
        Section("5", "", None, True), Section("5.2", "", "5", True),
        Section("5.2.1", "", "5.2", False), Section("5.2.3", "", "5.2", False),
        Section("5.2.4", "", "5.2", False), Section("5.3", "", "5", True),
        Section("7", "", None, True)])}


def item(split, *expected, answerable=True):
    return GoldenItem(id="G-001", split=split, answerable=answerable,
                      question="A question about GMP?",
                      expected=[Expected(doc_code=d, section=s) for d, s in expected],
                      key_facts=["x"] if answerable else [])


def test_chunks_answering_a_test_question_are_excluded():
    leaked = leaked_chunk_ids(CHUNKS, [item("test", ("ICH-Q7", "11.15"))], TREES)
    assert leaked == {"Q7:11.14–11.16:0"}  # the merged chunk contains 11.15; 11.2 and 12 do not


def test_every_chunk_of_the_same_or_a_nested_section_is_excluded():
    leaked = leaked_chunk_ids(CHUNKS, [item("test", ("ACME-SOP-QC-007", "5.2"))], TREES)
    assert leaked == {"SOP:5.2:0", "SOP:5.2:1"}  # both chunks inside 5.2, not 5.3


def test_an_expected_parent_section_excludes_all_its_children():
    leaked = leaked_chunk_ids(CHUNKS, [item("test", ("ACME-SOP-QC-007", "5"))], TREES)
    assert leaked == {"SOP:5.2:0", "SOP:5.2:1", "SOP:5.3:0"}


def test_the_document_must_match():
    leaked = leaked_chunk_ids(CHUNKS, [item("test", ("ICH-Q7", "7"))], TREES)
    assert leaked == set()  # "7" exists in the SOP, but the expected document is ICH-Q7


def test_unanswerable_questions_exclude_nothing():
    assert leaked_chunk_ids(CHUNKS, [item("test", answerable=False)], TREES) == set()


# ── parsing ──────────────────────────────────────────────────────────────────────────────

def test_parse_questions_handles_numbering_bullets_and_quotes():
    raw = ('1. What must be done when a result is out of specification?\n'
           '- "How is an OOS result investigated and documented?"\n'
           '3) What happens after the laboratory investigation is finished?\n'
           'Hope this helps!\n')
    assert parse_questions(raw) == [
        "What must be done when a result is out of specification?",
        "How is an OOS result investigated and documented?",
        "What happens after the laboratory investigation is finished?"]


def test_parse_questions_keeps_at_most_three_and_no_repeats():
    raw = "\n".join(["Is a deviation report required for this event?"] * 2
                     + [f"Question number {i} about the quality system?" for i in range(5)])
    out = parse_questions(raw)
    assert len(out) == 3 and len(set(out)) == 3


def test_prompt_contains_the_passage_and_the_rules():
    system, user = build_prompt("ICH-Q7 | 11.15 Controls\nOOS results must be investigated.")
    assert "OOS results must be investigated." in user
    assert "exactly 3" in user and "6 and 40 words" in user and "never say" in user
    assert "pharmaceutical" in system


# ── filters ──────────────────────────────────────────────────────────────────────────────

def rows(*pairs):
    return [{"chunk_id": cid, "questions": qs} for cid, qs in pairs]


def always(question, chunk_id):
    return True


def test_length_filter_boundaries():
    five = "What is a CAPA here?"  # 5 words
    six = "What is a CAPA in Acme?"  # 6 words
    forty = " ".join(["word"] * MAX_WORDS) + "?"
    forty_one = " ".join(["word"] * (MAX_WORDS + 1)) + "?"
    pairs, stats = filter_questions(rows(("c1", [five, six, forty, forty_one])), always)
    assert [q for q, _ in pairs] == [six, forty]
    assert (stats.too_short, stats.too_long, stats.kept, stats.raw) == (1, 1, 2, 4)


def test_duplicates_are_removed_across_chunks_after_normalising():
    a = "What must be done after an OOS result is confirmed?"
    b = "what must be done after an OOS result is confirmed"  # same once normalised
    pairs, stats = filter_questions(rows(("c1", [a]), ("c2", [b, a.upper()])), always)
    assert pairs == [(a, "c1")] and stats.duplicate == 2


def test_round_trip_failure_is_counted_and_dropped():
    def top10(question, chunk_id):
        return chunk_id == "c1"

    pairs, stats = filter_questions(rows(
        ("c1", ["Who must approve the corrective action plan here?"]),
        ("c2", ["Which records need to be kept for six years?"])), top10)
    assert [c for _, c in pairs] == ["c1"] and stats.round_trip_failed == 1
    assert stats.per_chunk_kept == {"c1": 1}


def test_a_dropped_question_does_not_block_a_later_valid_one():
    short = "Too short?"
    ok = "How long must the investigation records be retained?"
    pairs, _ = filter_questions(rows(("c1", [short]), ("c2", [ok])), always)
    assert pairs == [(ok, "c2")]


def test_normalise():
    assert normalise("  What  is X-Y?? ") == "what is x y"


def test_read_raw_roundtrip_and_missing_file(tmp_path):
    assert read_raw(tmp_path / "none.jsonl") == []
    path = tmp_path / "raw.jsonl"
    path.write_text(json.dumps({"chunk_id": "c", "questions": ["Q here is fine to ask?"]}) + "\n\n")
    assert read_raw(path)[0]["chunk_id"] == "c"


def test_trial_subsets_are_deterministic_and_keep_document_order():
    ids = [f"c{i}" for i in range(50)]
    assert pick_chunks(ids) == ids
    assert pick_chunks(ids, limit=3) == ["c0", "c1", "c2"]
    sample = pick_chunks(ids, sample=8)
    assert len(sample) == 8 and sample == pick_chunks(ids, sample=8)
    assert sample == sorted(sample, key=lambda c: int(c[1:]))
    assert len(pick_chunks(ids, sample=999)) == 50


# ── retries ──────────────────────────────────────────────────────────────────────────────

SETTINGS = Settings(_env_file=None, jwt_secret_key="x" * 64)


def small_client(fake):
    return OllamaClient(SETTINGS, transport=fake.transport(), model="llama3.2:3b")


async def test_a_transient_http_500_is_retried_and_then_succeeds():
    fake = FakeOllama(answer="Q one here is a fine question?")
    fake.fail_times = 2
    pauses = []

    async def fake_sleep(seconds):
        pauses.append(seconds)

    reply = await chat_with_retry(small_client(fake), "s", "u", wait=20, sleep=fake_sleep)
    assert reply == "Q one here is a fine question?"
    assert len(fake.requests) == 3 and pauses == [20, 20]
    assert all(r["model"] == "llama3.2:3b" and r["options"]["temperature"] == 0.7
               for r in fake.requests)


async def test_a_permanent_failure_is_raised_after_the_retries():
    fake = FakeOllama()
    fake.fail = httpx.ConnectError("down")

    async def no_sleep(seconds):
        pass

    with pytest.raises(LLMUnavailable):
        await chat_with_retry(small_client(fake), "s", "u", retries=2, sleep=no_sleep)
    assert len(fake.paths) == 3  # the first try and two retries
    assert issubclass(LLMUnavailable, OllamaError)


async def test_the_model_is_unloaded_every_n_chunks_to_bound_ollamas_memory(tmp_path):
    chunks = pd.DataFrame({"chunk_id": [f"c{i}" for i in range(7)],
                           "embed_text": [f"text {i}" for i in range(7)]})
    big_fake = FakeOllama()
    small_fake = FakeOllama(answer="What does this chunk say about records?\n"
                                   "How long are records kept in the archive?")
    raw = tmp_path / "raw.jsonl"
    done = await generate(SETTINGS, chunks, list(chunks["chunk_id"]), raw,
                          big=OllamaClient(SETTINGS, transport=big_fake.transport()),
                          small=small_client(small_fake), recycle_every=3)
    assert done == 7 and len(read_raw(raw)) == 7
    unloads = [c for c in small_fake.generate_calls if c["keep_alive"] == 0]
    assert len(unloads) == 3  # after chunk 3, after chunk 6, and once more at the end
    assert [c["keep_alive"] for c in big_fake.generate_calls] == [0]  # answer model freed first
    # resuming skips finished chunks and does not touch Ollama when nothing is left
    again = await generate(SETTINGS, chunks, list(chunks["chunk_id"]), raw,
                           big=OllamaClient(SETTINGS, transport=big_fake.transport()),
                           small=small_client(small_fake), recycle_every=3)
    assert again == 0 and len(small_fake.requests) == 7
