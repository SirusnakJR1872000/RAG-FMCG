"""Reciprocal Rank Fusion of dense and sparse results (PROJECT_SPEC §8.2, §8.4).

score(c) = Σ_r 1 / (k + rank_r(c)), ranks starting at 1; a chunk missing from a list adds
nothing for that list. Ties are broken by better dense rank. RRF scores depend only on rank
positions, so they are never used as a relevance threshold (that is the reranker's job, §8.5).
"""

from dataclasses import dataclass

from src.retrieval.bm25_store import BM25Store
from src.retrieval.embeddings import Embedder
from src.retrieval.faiss_store import FaissStore

_MISSING = float("inf")


@dataclass(frozen=True)
class Fused:
    chunk_id: str
    score: float
    dense_rank: int | None
    sparse_rank: int | None


def rrf(dense: list[str], sparse: list[str], k: int, top: int) -> list[Fused]:
    """Fuse two ranked lists of chunk ids (best first)."""
    d_rank = {cid: i for i, cid in enumerate(dense, start=1)}
    s_rank = {cid: i for i, cid in enumerate(sparse, start=1)}
    fused = []
    for cid in dict.fromkeys([*dense, *sparse]):  # unique, order-preserving
        score = sum(1.0 / (k + r[cid]) for r in (d_rank, s_rank) if cid in r)
        fused.append(Fused(cid, score, d_rank.get(cid), s_rank.get(cid)))
    fused.sort(key=lambda f: (-f.score, f.dense_rank or _MISSING, f.sparse_rank or _MISSING))
    return fused[:top]


class HybridRetriever:
    """Dense, sparse or hybrid ranking of chunk ids for a question."""

    def __init__(self, embedder: Embedder | None, dense: FaissStore | None,
                 sparse: BM25Store | None, candidates: int, rrf_k: int):
        self.embedder, self.dense, self.sparse = embedder, dense, sparse
        self.candidates, self.rrf_k = candidates, rrf_k

    def dense_ids(self, question: str) -> list[str]:
        query = self.embedder.embed_query(question)
        return [cid for cid, _ in self.dense.search(query, self.candidates)]

    def sparse_ids(self, question: str) -> list[str]:
        return [cid for cid, _ in self.sparse.search(question, self.candidates)]

    def search(self, question: str, mode: str = "hybrid") -> list[str]:
        if mode == "dense":
            return self.dense_ids(question)
        if mode == "bm25":
            return self.sparse_ids(question)
        if mode == "hybrid":
            fused = rrf(self.dense_ids(question), self.sparse_ids(question),
                        self.rrf_k, self.candidates)
            return [f.chunk_id for f in fused]
        raise ValueError(f"unknown retrieval mode: {mode}")
