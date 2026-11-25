"""A scripted RagPipeline for API tests: the same events and Result as the real one, no models.

Use `FakePipeline(answer_type=..., answer=..., fail=...)`; `calls` records what the API asked.
"""

import asyncio

import pandas as pd

from config import Settings
from src.generation.citation_check import CitationCheck
from src.generation.pipeline import (
    NOT_COVERED_MESSAGE,
    Done,
    Result,
    SourceInfo,
    SourcesReady,
    Status,
    Token,
)


class FakeLLMClient:
    def __init__(self):
        self.reachable = True
        self.loaded = [{"name": "llama3.1:8b"}]

    async def ping(self) -> bool:
        return self.reachable

    async def loaded_models(self) -> list[dict]:
        return self.loaded if self.reachable else []

    async def aclose(self) -> None:
        pass


def source(n: int, doc_code: str = "ICH-Q7", fictional: bool = False) -> SourceInfo:
    return SourceInfo(
        n=n, chunk_id=f"{doc_code}:v1:11.{n}:000", doc_code=doc_code, title=f"{doc_code} title",
        version="3.0" if fictional else "Step 4, 10 Nov 2000", section=f"11.{n}",
        section_title="General Controls", page=None if fictional else 28 + n,
        page_end=None if fictional else 28 + n, text=f"Passage {n} text.",
        is_fictional=fictional, sha256="ab" * 32, score=5.0 - n)


class FakePipeline:
    def __init__(self, settings: Settings, *, answer_type: str = "answered",
                 answer: str = "OOS results must be investigated [1]. A CAPA follows [2].",
                 fail: Exception | None = None, delay: float = 0.0):
        self.settings = settings
        self.answer_type, self.answer_text, self.fail, self.delay = answer_type, answer, fail, delay
        self.client = FakeLLMClient()
        self.index_info = {"build_id": "build-test-1", "created_at": "2026-11-25T08:00:00+00:00",
                           "chunk_count": 681, "embedding_model": settings.embedding_model}
        self.chunks = pd.DataFrame([  # what the history detail looks passages up in
            {"chunk_id": s.chunk_id, "doc_title": s.title, "section_title": s.section_title,
             "text": s.text} for s in (source(1), source(2, "ACME-SOP-QC-007", True))
        ]).set_index("chunk_id")
        self.calls: list[tuple[str, list]] = []
        self.active = 0
        self.max_active = 0

    async def warm_up(self, llm: bool = True) -> None:
        pass

    async def aclose(self) -> None:
        pass

    async def answer(self, question, history=()) -> Result:
        """Like RagPipeline.answer(): run the stream, return the final Result."""
        result = None
        async for event in self.stream(question, history):
            if isinstance(event, Done):
                result = event.result
        return result

    async def stream(self, question, history=()):
        self.calls.append((question, list(history)))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if history:
                yield Status("rewriting")
            yield Status("retrieving")
            yield Status("reranking")
            if self.answer_type == "retrieval_refusal":
                yield SourcesReady([])
                yield Done(self._result([], None))
                return
            sources = [source(1), source(2, "ACME-SOP-QC-007", fictional=True)]
            yield SourcesReady(sources)
            yield Status("generating")
            if self.fail:
                raise self.fail
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.answer_type == "answered":
                for word in self.answer_text.split(" "):
                    yield Token(word + " ")
            check = CitationCheck("ok", [1, 2]) if self.answer_type == "answered" else None
            yield Done(self._result(sources, check))
        finally:
            self.active -= 1

    def _result(self, sources, check) -> Result:
        text = self.answer_text if self.answer_type == "answered" else NOT_COVERED_MESSAGE
        return Result(
            self.answer_type, text, f"standalone: {self.calls[-1][0]}", sources, check,
            top_score=4.2, latency_ms={"rewrite": 0, "retrieval": 12, "rerank": 800, "ttft": 9000,
                                       "generation": 20000, "total": 30000},
            llm={"prompt_tokens": 900, "completion_tokens": 40, "tokens_per_second": 5.0,
                 "load_ms": 0, "done_reason": "stop"})
