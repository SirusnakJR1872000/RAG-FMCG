"""RagPipeline: question → retrieval → reranking → refusal check → cited answer (§8.2, §9, §17).

Created ONCE (models and indexes are loaded in __init__), then used for every question.
`stream()` yields the events of the streaming protocol (§17) as they happen; `answer()` runs
the same flow and returns only the final Result.

Flow for one question:
  [1] rewrite as a standalone question — only if there is history
  [3] dense (FAISS) + sparse (BM25) top-20
  [4] RRF fusion
  [5] cross-encoder rerank of the 20 candidates
  [6] top reranker score < τ → "not covered", the LLM is never called   (retrieval_refusal)
  [7] top 4 chunks → llama3.1:8b with the grounded prompt; NOT_COVERED → model_refusal
      then the citation check (§9.4)
"""

import asyncio
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Literal

import pandas as pd
import structlog

from config import Settings
from src.generation.citation_check import CitationCheck, check_citations
from src.generation.ollama_client import CallStats, OllamaClient
from src.generation.prompts import NOT_COVERED, Exchange, PromptSource, build_answer_prompt
from src.generation.rewriter import rewrite_question
from src.ingestion.manifest import is_fictional_code
from src.retrieval.bm25_store import BM25Store
from src.retrieval.embeddings import Embedder
from src.retrieval.faiss_store import FaissStore
from src.retrieval.hybrid import HybridRetriever
from src.retrieval.indexes import IndexNotReady, chunks_path, index_dir, load_build_info
from src.retrieval.reranker import Reranker, Scored

log = structlog.get_logger(__name__)

NOT_COVERED_MESSAGE = "The approved documents don't cover this question."
AnswerType = Literal["answered", "retrieval_refusal", "model_refusal"]
WARMUP_QUESTION = "What does the guidance require for out-of-specification results?"


class QuestionError(ValueError):
    """The question is empty, too short or too long (§26 QUESTION_MIN/MAX_CHARS)."""


def validate_question(question: str, settings: Settings) -> str:
    question = " ".join(question.split())
    if not settings.question_min_chars <= len(question) <= settings.question_max_chars:
        raise QuestionError(f"The question must be {settings.question_min_chars}–"
                            f"{settings.question_max_chars} characters long.")
    return question


# ── what the pipeline returns ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SourceInfo:
    """One retrieved passage, in the shape of `sources[]` in §16."""

    n: int
    chunk_id: str
    doc_code: str
    title: str
    version: str
    section: str
    section_title: str
    page: int | None
    page_end: int | None
    text: str
    is_fictional: bool
    sha256: str
    score: float  # reranker score

    def as_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class Result:
    answer_type: AnswerType
    answer: str  # the cited answer, or the standard "not covered" message
    standalone_question: str
    sources: list[SourceInfo]  # what the LLM was given; empty on retrieval_refusal
    citation_check: CitationCheck | None  # None for refusals
    top_score: float | None  # best reranker score (for τ and the audit record)
    latency_ms: dict[str, int]
    llm: dict = field(default_factory=dict)  # prompt/completion tokens, tokens/s, done_reason
    truncated: bool = False  # the answer hit the token cap
    rewrite_failed: bool = False

    def as_dict(self) -> dict:
        return {
            "answer_type": self.answer_type, "answer": self.answer,
            "standalone_question": self.standalone_question,
            "sources": [s.as_dict() for s in self.sources],
            "citation_check": self.citation_check.as_dict() if self.citation_check else None,
            "top_score": self.top_score, "latency_ms": self.latency_ms, "llm": self.llm,
            "truncated": self.truncated, "rewrite_failed": self.rewrite_failed,
        }


@dataclass(frozen=True)
class Status:
    stage: Literal["rewriting", "retrieving", "reranking", "generating"]


@dataclass(frozen=True)
class SourcesReady:
    sources: list[SourceInfo]


@dataclass(frozen=True)
class Token:
    text: str


@dataclass(frozen=True)
class Done:
    result: Result


Event = Status | SourcesReady | Token | Done


def _ms(seconds: float) -> int:
    return round(seconds * 1000)


# ── the pipeline ─────────────────────────────────────────────────────────────────────────

class RagPipeline:
    def __init__(self, settings: Settings, *, chunks: pd.DataFrame | None = None,
                 retriever=None, reranker=None, client: OllamaClient | None = None):
        """Loads everything now. The keyword arguments let tests inject fakes."""
        self.settings = settings
        self.index_info: dict = {}
        if chunks is None:
            chunks, retriever, self.index_info = self._load_index(settings)
        self.chunks = chunks.set_index("chunk_id")
        self.retriever = retriever
        self.reranker = reranker or Reranker(settings.reranker_model)
        self.client = client or OllamaClient(settings)

    @staticmethod
    def _load_index(settings: Settings) -> tuple[pd.DataFrame, HybridRetriever, dict]:
        info = load_build_info(settings, settings.embedding_model)  # raises IndexNotReady
        chunks = pd.read_parquet(chunks_path(settings))
        store = FaissStore.load(index_dir(settings, settings.embedding_model))
        if store.chunk_ids != chunks["chunk_id"].tolist():
            raise IndexNotReady("The index and chunks.parquet disagree. Rebuild the index.")
        bm25 = BM25Store(chunks["chunk_id"].tolist(), chunks["embed_text"].tolist())
        retriever = HybridRetriever(Embedder(settings.embedding_model), store, bm25,
                                    settings.candidates_per_retriever, settings.rrf_k)
        return chunks, retriever, info

    async def warm_up(self, llm: bool = True) -> None:
        """Load the embedding model, the reranker and (optionally) the LLM into memory."""
        await asyncio.to_thread(self._rerank, WARMUP_QUESTION, self._retrieve(WARMUP_QUESTION))
        if llm:
            await self.client.preload()

    async def aclose(self) -> None:
        await self.client.aclose()

    # ── synchronous, CPU-bound steps (run in a worker thread) ──
    def _retrieve(self, question: str) -> list[str]:
        return self.retriever.search(question, "hybrid")

    def _rerank(self, question: str, chunk_ids: list[str]) -> list[Scored]:
        candidates = [(cid, self.chunks.at[cid, "embed_text"]) for cid in chunk_ids]
        return self.reranker.rerank(question, candidates)

    def _source(self, n: int, scored: Scored) -> SourceInfo:
        row = self.chunks.loc[scored.chunk_id]
        page = None if pd.isna(row["page_start"]) else int(row["page_start"])
        page_end = None if pd.isna(row["page_end"]) else int(row["page_end"])
        return SourceInfo(
            n=n, chunk_id=scored.chunk_id, doc_code=row["doc_code"], title=row["doc_title"],
            version=row["version"], section=row["section"], section_title=row["section_title"],
            page=page, page_end=page_end, text=row["text"],
            is_fictional=is_fictional_code(row["doc_code"]), sha256=row["doc_sha256"],
            score=round(scored.score, 4))

    def rank(self, question: str) -> list[Scored]:
        """Retrieval + reranking only (no LLM): all candidates, best reranker score first.

        Used by scripts that tune or measure the retrieval side (τ, latency).
        """
        return self._rerank(question, self._retrieve(question))

    # ── the flow ──
    async def answer(self, question: str, history: Sequence[Exchange] = ()) -> Result:
        result: Result | None = None
        async for event in self.stream(question, history):
            if isinstance(event, Done):
                result = event.result
        assert result is not None  # stream() always ends with Done or raises
        return result

    async def stream(self, question: str, history: Sequence[Exchange] = ()) -> AsyncIterator[Event]:
        s = self.settings
        question = validate_question(question, s)
        started = time.perf_counter()
        lat = {"rewrite": 0, "retrieval": 0, "rerank": 0, "ttft": 0, "generation": 0}

        standalone, rewrite_failed = question, False
        if history:
            yield Status("rewriting")
            t = time.perf_counter()
            rewrite = await rewrite_question(self.client, question, history, s.history_turns,
                                             s.llm_max_tokens_rewrite)
            lat["rewrite"] = _ms(time.perf_counter() - t)
            standalone, rewrite_failed = rewrite.question, rewrite.failed

        yield Status("retrieving")
        t = time.perf_counter()
        candidate_ids = await asyncio.to_thread(self._retrieve, standalone)
        lat["retrieval"] = _ms(time.perf_counter() - t)

        yield Status("reranking")
        t = time.perf_counter()
        ranked = await asyncio.to_thread(self._rerank, standalone, candidate_ids)
        lat["rerank"] = _ms(time.perf_counter() - t)

        top_score = ranked[0].score if ranked else None
        if top_score is None or top_score < s.relevance_threshold:  # §8.5: no LLM call
            lat["total"] = _ms(time.perf_counter() - started)
            result = Result("retrieval_refusal", NOT_COVERED_MESSAGE, standalone, [], None,
                            top_score, lat, rewrite_failed=rewrite_failed)
            log.info("query_done", answer_type=result.answer_type, top_score=top_score,
                     latency_ms=lat)
            yield SourcesReady([])
            yield Done(result)
            return

        sources = [self._source(n, sc) for n, sc in enumerate(ranked[:s.context_chunks], start=1)]
        yield SourcesReady(sources)

        yield Status("generating")
        system, user = build_answer_prompt(standalone, [
            PromptSource(x.n, x.doc_code, x.section, x.section_title, x.version, x.page, x.text)
            for x in sources])
        stats = CallStats()
        pieces: list[str] = []
        shown = False  # have tokens been sent to the caller yet?
        t_llm = time.perf_counter()
        async for piece in self.client.chat_stream(system, user, s.llm_max_tokens_answer, stats):
            if not lat["ttft"]:
                lat["ttft"] = _ms(time.perf_counter() - started)
            pieces.append(piece)
            text = "".join(pieces)
            if shown:
                yield Token(piece)
            elif not _could_be_refusal(text):
                shown = True  # decided: this is a real answer; release what was held back
                yield Token(text)
        full = "".join(pieces).strip()
        lat["generation"] = _ms(time.perf_counter() - t_llm)

        if _is_refusal(full):
            answer_type: AnswerType = "model_refusal"
            answer, check = NOT_COVERED_MESSAGE, None
        else:
            answer_type, answer = "answered", full
            check = check_citations(full, len(sources))
            if not shown and full:  # a very short answer that stayed in the hold-back buffer
                yield Token(full)
        lat["total"] = _ms(time.perf_counter() - started)
        result = Result(
            answer_type, answer, standalone, sources, check, top_score, lat,
            llm={"prompt_tokens": stats.prompt_tokens, "completion_tokens": stats.completion_tokens,
                 "tokens_per_second": round(stats.tokens_per_second, 2),
                 "load_ms": round(stats.load_ms), "done_reason": stats.done_reason},
            truncated=stats.done_reason == "length", rewrite_failed=rewrite_failed)
        log.info("query_done", answer_type=answer_type, top_score=top_score, latency_ms=lat,
                 citation=check.status if check else None, truncated=result.truncated,
                 prompt_tokens=stats.prompt_tokens)
        yield Done(result)


def _is_refusal(text: str) -> bool:
    return text.strip().upper().startswith(NOT_COVERED)


def _could_be_refusal(text: str) -> bool:
    """True while the text so far could still turn out to be 'NOT_COVERED…'.

    The model's refusal is a single word at the very start; holding back the first few
    characters means the user never sees a flash of "NOT_COVERED" in the answer area.
    """
    head = text.lstrip().upper()
    return NOT_COVERED.startswith(head) or head.startswith(NOT_COVERED)
