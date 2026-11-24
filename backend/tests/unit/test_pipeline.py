"""RagPipeline with a fake retriever, fake reranker and fake Ollama (PROJECT_SPEC §8.2, §9, §17)."""

import httpx
import pandas as pd
import pytest

from config import Settings
from src.generation.ollama_client import LLMUnavailable, OllamaClient
from src.generation.pipeline import (
    NOT_COVERED_MESSAGE,
    Done,
    QuestionError,
    RagPipeline,
    SourcesReady,
    Status,
    Token,
    validate_question,
)
from src.generation.prompts import Exchange
from src.retrieval.indexes import IndexNotReady
from src.retrieval.reranker import Scored
from tests.fakes.fake_ollama import FakeOllama

ROWS = [  # (chunk_id, doc_code, section, title, version, page, text)
    ("ICH-Q7:v1:11.15:000", "ICH-Q7", "11.14–11.16", "General Controls", "Step 4, 10 Nov 2000", 29,
     "11.15 Any out-of-specification result obtained should be investigated."),
    ("ACME-SOP-QC-007:v1:5.2:000", "ACME-SOP-QC-007", "5.2", "Phase I", "3.0", None,
     "Phase I must be completed within 5 working days."),
    ("ACME-SOP-QA-008:v1:5.1:000", "ACME-SOP-QA-008", "5.1", "CAPA initiation", "3.2", None,
     "QA shall initiate a CAPA when a cause is confirmed."),
    ("ICH-Q10:v1:3.2.2:000", "ICH-Q10", "3.2.2", "CAPA System", "Step 4, 4 Jun 2008", 13,
     "The pharmaceutical company should have a CAPA system."),
    ("WHO-GMP-MAIN:v1:8:000", "WHO-GMP-MAIN", "8", "Self-inspection", "TRS 986, Annex 2 (2014)", 21,
     "Self-inspections should be performed routinely."),
    ("EU-ANNEX11:v1:9:000", "EU-ANNEX11", "9", "Audit Trails", "Rev. 1, 2011", 4,
     "Audit trails should be regularly reviewed."),
]
CHUNKS = pd.DataFrame(
    [{"chunk_id": r[0], "doc_code": r[1], "doc_title": f"{r[1]} title", "version": r[4],
      "doc_sha256": "ab" * 32, "section": r[2], "section_title": r[3],
      "page_start": r[5], "page_end": r[5], "text": r[6], "embed_text": f"{r[1]} | {r[6]}"}
     for r in ROWS]).astype({"page_start": "Int64", "page_end": "Int64"})
IDS = [r[0] for r in ROWS]
SCORES = dict(zip(IDS, [6.0, 4.0, 2.0, 1.0, -1.0, -3.0], strict=True))  # the reranker's view


class FakeRetriever:
    def __init__(self):
        self.questions: list[str] = []

    def search(self, question: str, mode: str) -> list[str]:
        assert mode == "hybrid"
        self.questions.append(question)
        return list(reversed(IDS))  # deliberately NOT in reranker order


class FakeReranker:
    def __init__(self, scores=None):
        self.scores = scores or SCORES
        self.calls: list[tuple[str, int]] = []

    def rerank(self, question, candidates):
        self.calls.append((question, len(candidates)))
        return sorted((Scored(cid, self.scores[cid]) for cid, _ in candidates),
                      key=lambda s: -s.score)


def build(fake=None, *, threshold=0.0, scores=None, **settings):
    fake = fake or FakeOllama()
    cfg = Settings(_env_file=None, jwt_secret_key="x" * 64, relevance_threshold=threshold,
                   **settings)
    pipeline = RagPipeline(cfg, chunks=CHUNKS, retriever=FakeRetriever(),
                           reranker=FakeReranker(scores),
                           client=OllamaClient(cfg, transport=fake.transport()))
    return pipeline, fake


async def collect(pipeline, question="What must happen after an OOS result?", history=()):
    return [e async for e in pipeline.stream(question, history)]


# ── answered ──────────────────────────────────────────────────────────────────────────────

async def test_answered_flow_events_in_protocol_order():
    pipeline, fake = build(FakeOllama(answer="OOS results must be investigated [1]. A CAPA "
                                             "follows [2]."))
    events = await collect(pipeline)
    kinds = [type(e).__name__ for e in events]
    assert kinds[:5] == ["Status", "Status", "SourcesReady", "Status", "Token"]
    assert [e.stage for e in events if isinstance(e, Status)] == [
        "retrieving", "reranking", "generating"]
    assert kinds[-1] == "Done" and kinds.count("Done") == 1
    result = events[-1].result
    assert result.answer_type == "answered"
    assert "".join(e.text for e in events if isinstance(e, Token)).strip() == result.answer
    assert result.citation_check.status == "ok" and result.citation_check.cited == [1, 2]
    assert len(fake.answer_calls) == 1 and fake.rewrite_calls == []


async def test_context_is_the_top_4_by_reranker_score_numbered_from_1():
    pipeline, fake = build()
    result = (await collect(pipeline))[-1].result
    assert [s.chunk_id for s in result.sources] == IDS[:4]
    assert [s.n for s in result.sources] == [1, 2, 3, 4]
    assert [s.score for s in result.sources] == [6.0, 4.0, 2.0, 1.0]
    user = fake.answer_calls[0]["messages"][1]["content"]
    assert "[1] ICH-Q7 §11.14–11.16 General Controls (Step 4, 10 Nov 2000), p. 29" in user
    assert "[2] ACME-SOP-QC-007 §5.2 Phase I (v3.0)\n" in user  # SOP: no page
    assert "[5]" not in user and "Self-inspections should be performed" not in user
    assert pipeline.reranker.calls == [("What must happen after an OOS result?", 6)]


async def test_source_info_carries_what_the_ui_and_audit_need():
    pipeline, _ = build()
    first, second = (await collect(pipeline))[-1].result.sources[:2]
    assert (first.doc_code, first.page, first.is_fictional, first.sha256) == (
        "ICH-Q7", 29, False, "ab" * 32)
    assert (second.page, second.is_fictional) == (None, True)


async def test_result_has_latencies_and_llm_stats():
    pipeline, _ = build()
    result = (await collect(pipeline))[-1].result
    assert set(result.latency_ms) == {"rewrite", "retrieval", "rerank", "ttft", "generation",
                                      "total"}
    assert result.latency_ms["total"] >= result.latency_ms["ttft"] > 0
    assert result.llm["prompt_tokens"] == 1200 and result.llm["tokens_per_second"] == 4.0
    assert not result.truncated


async def test_answer_returns_only_the_final_result():
    pipeline, _ = build()
    result = await pipeline.answer("What must happen after an OOS result?")
    assert result.answer_type == "answered" and result.as_dict()["sources"][0]["n"] == 1


async def test_a_cut_off_answer_is_flagged():
    fake = FakeOllama(answer="A long answer [1]")
    fake.done_reason = "length"
    result = (await collect(build(fake)[0]))[-1].result
    assert result.truncated is True


# ── refusals ──────────────────────────────────────────────────────────────────────────────

async def test_retrieval_refusal_never_calls_the_llm():
    pipeline, fake = build(threshold=7.0)  # best score is 6.0
    events = await collect(pipeline)
    result = events[-1].result
    assert (result.answer_type, result.answer) == ("retrieval_refusal", NOT_COVERED_MESSAGE)
    assert result.sources == [] and result.top_score == 6.0 and result.citation_check is None
    assert fake.requests == [] and fake.paths == []  # no LLM traffic at all
    assert not any(isinstance(e, Token) for e in events)
    assert [type(e).__name__ for e in events[-2:]] == ["SourcesReady", "Done"]
    assert events[-2].sources == []


async def test_a_score_exactly_at_the_threshold_is_not_refused():
    pipeline, fake = build(threshold=6.0)
    assert (await collect(pipeline))[-1].result.answer_type == "answered"
    assert len(fake.answer_calls) == 1


async def test_model_refusal_shows_no_tokens_and_the_standard_message():
    pipeline, fake = build(FakeOllama(answer="NOT_COVERED"))
    events = await collect(pipeline)
    result = events[-1].result
    assert (result.answer_type, result.answer) == ("model_refusal", NOT_COVERED_MESSAGE)
    assert not any(isinstance(e, Token) for e in events)  # no flash of "NOT_COVERED"
    assert result.citation_check is None and len(result.sources) == 4


@pytest.mark.parametrize("pieces", [["NOT_", "COVE", "RED"], ["not_covered."], [" NOT_COVERED\n"]])
async def test_model_refusal_is_recognised_even_when_split_across_tokens(pieces):
    fake = FakeOllama()
    fake.pieces = pieces
    events = await collect(build(fake)[0])
    assert events[-1].result.answer_type == "model_refusal"
    assert not any(isinstance(e, Token) for e in events)


async def test_text_that_only_starts_like_a_refusal_is_still_shown_whole():
    fake = FakeOllama()
    fake.pieces = ["No", "t covered by ICH ", "[1]."]
    events = await collect(build(fake)[0])
    assert events[-1].result.answer_type == "answered"
    assert "".join(e.text for e in events if isinstance(e, Token)) == "Not covered by ICH [1]."


async def test_a_very_short_answer_is_not_lost():
    fake = FakeOllama()
    fake.pieces = ["NOT"]
    events = await collect(build(fake)[0])
    assert [e.text for e in events if isinstance(e, Token)] == ["NOT"]


# ── citation check ────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("answer", "status"), [
    ("It is required [9].", "invalid_citation"),
    ("It is required [5].", "invalid_citation"),  # only 4 sources were given
    ("It is required.", "uncited_answer"),
])
async def test_bad_citations_are_flagged_but_the_answer_is_still_returned(answer, status):
    result = (await collect(build(FakeOllama(answer=answer))[0]))[-1].result
    assert result.answer_type == "answered" and result.citation_check.status == status


# ── follow-ups ────────────────────────────────────────────────────────────────────────────

HISTORY = [Exchange("What is a CAPA?", "A corrective and preventive action [1]."),
           Exchange("When is it raised?", "After a confirmed cause, SECRET-MARKER [2].")]


async def test_rewrite_runs_only_when_there_is_history():
    pipeline, fake = build()
    events = await collect(pipeline)
    assert fake.rewrite_calls == [] and events[0] == Status("retrieving")
    assert (events[-1].result.latency_ms["rewrite"], events[-1].result.standalone_question) == (
        0, "What must happen after an OOS result?")


async def test_follow_up_is_rewritten_and_the_rewrite_is_what_gets_searched():
    pipeline, fake = build(FakeOllama(rewrite="Who approves a CAPA at Acme?"))
    events = await collect(pipeline, "who approves it?", HISTORY)
    assert events[0] == Status("rewriting")
    assert len(fake.rewrite_calls) == 1 and len(fake.answer_calls) == 1
    assert events[-1].result.standalone_question == "Who approves a CAPA at Acme?"
    assert pipeline.retriever.questions == ["Who approves a CAPA at Acme?"]
    assert pipeline.reranker.calls[0][0] == "Who approves a CAPA at Acme?"


async def test_history_never_reaches_the_answer_prompt():
    pipeline, fake = build(FakeOllama(rewrite="Who approves a CAPA at Acme?"))
    await collect(pipeline, "who approves it?", HISTORY)
    sent = fake.answer_calls[0]["messages"]
    text = sent[0]["content"] + sent[1]["content"]
    assert "SECRET-MARKER" not in text and "When is it raised?" not in text  # §9.2
    assert text.endswith("Question: Who approves a CAPA at Acme?")


async def test_rewrite_failure_uses_the_original_question_and_still_answers():
    fake = FakeOllama()
    fake.fail_rewrite = httpx.ReadTimeout("slow")
    pipeline, _ = build(fake)
    result = (await collect(pipeline, "who approves it?", HISTORY))[-1].result
    assert result.standalone_question == "who approves it?" and result.rewrite_failed
    assert result.answer_type == "answered"


# ── failures ──────────────────────────────────────────────────────────────────────────────

async def test_ollama_down_raises_after_the_sources_were_found():
    fake = FakeOllama()
    fake.fail = httpx.ConnectError("refused")
    pipeline, _ = build(fake)
    seen = []
    with pytest.raises(LLMUnavailable):
        async for event in pipeline.stream("What must happen after an OOS result?"):
            seen.append(event)
    assert isinstance(seen[-1], Status) and seen[-1].stage == "generating"
    assert any(isinstance(e, SourcesReady) for e in seen)
    assert not any(isinstance(e, Done) for e in seen)


def test_question_validation():
    cfg = Settings(_env_file=None, jwt_secret_key="x" * 64)
    assert validate_question("  What   is  a CAPA? ", cfg) == "What is a CAPA?"
    for bad in ("", "  ", "ab", "x" * 1001):
        with pytest.raises(QuestionError):
            validate_question(bad, cfg)


async def test_empty_question_is_rejected_before_any_work():
    pipeline, fake = build()
    with pytest.raises(QuestionError):
        await pipeline.answer("   ")
    assert pipeline.retriever.questions == [] and fake.requests == []


def test_missing_index_gives_an_actionable_error(tmp_path):
    cfg = Settings(_env_file=None, jwt_secret_key="x" * 64, data_dir=tmp_path, index_dir=tmp_path)
    with pytest.raises(IndexNotReady, match="build_chunks"):
        RagPipeline(cfg)
    CHUNKS.to_parquet(tmp_path / "chunks.parquet")
    with pytest.raises(IndexNotReady, match="build_index"):
        RagPipeline(cfg)
