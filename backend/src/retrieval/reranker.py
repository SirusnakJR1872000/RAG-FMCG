"""Cross-encoder reranking of the hybrid candidates (PROJECT_SPEC §8.2 step 5, D-13).

A bi-encoder (the embedding model) encodes question and chunk separately, so chunk vectors can
be precomputed and searched in milliseconds. A cross-encoder reads question and chunk
*together* and scores the pair, which is more accurate but costs one model pass per pair —
so it only re-sorts the ~20 candidates that retrieval already found.

Scores are on the model's own scale (ms-marco: raw logits; bge-reranker: sigmoid 0–1).
The relevance threshold τ (§8.5) is therefore tuned per reranker model.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property

MAX_LENGTH = 512  # question + chunk (≤ 256 tokens) always fits; both candidates support 512


@dataclass(frozen=True)
class Scored:
    chunk_id: str
    score: float


class Reranker:
    def __init__(self, model_name: str, batch_size: int = 32, model=None):
        self.model_name = model_name
        self.batch_size = batch_size
        self._injected = model  # tests pass a fake model; real runs load lazily

    @cached_property
    def model(self):
        if self._injected is not None:
            return self._injected
        from sentence_transformers import CrossEncoder  # heavy: torch

        return CrossEncoder(self.model_name, device="cpu", max_length=MAX_LENGTH)

    def rerank(self, question: str, candidates: Sequence[tuple[str, str]]) -> list[Scored]:
        """candidates: (chunk_id, text). Returns all candidates, best score first.

        Ties keep the incoming (retrieval) order, so the result is deterministic.
        """
        if not candidates:
            return []
        scores = self.model.predict([(question, text) for _, text in candidates],
                                    batch_size=self.batch_size, show_progress_bar=False)
        ranked = sorted(enumerate(candidates), key=lambda x: (-float(scores[x[0]]), x[0]))
        return [Scored(cid, float(scores[i])) for i, (cid, _) in ranked]
