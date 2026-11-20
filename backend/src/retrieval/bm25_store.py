"""Sparse retrieval: BM25Okapi, rebuilt in memory from chunks.parquet (PROJECT_SPEC §8.1).

Never serialised: building it for ~700 chunks takes milliseconds, and loading a pickled
index would be a code-execution risk (SEC-11).
"""

import re

import numpy as np
from rank_bm25 import BM25Okapi

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumerics, keep tokens ≥ 2 chars and all-digit tokens.

    Digits are kept even when short so section numbers survive: "11.15" → ["11", "15"].
    """
    return [t for t in _TOKEN.findall(text.lower()) if len(t) >= 2 or t.isdigit()]


class BM25Store:
    def __init__(self, chunk_ids: list[str], texts: list[str]):
        if len(chunk_ids) != len(texts):
            raise ValueError("chunk_ids and texts must have the same length")
        self.chunk_ids = list(chunk_ids)
        self.bm25 = BM25Okapi([tokenize(t) for t in texts])

    def search(self, query: str, k: int) -> list[tuple[str, float]]:
        """Top-k (chunk_id, BM25 score), best first; chunks sharing no term are left out."""
        scores = self.bm25.get_scores(tokenize(query))
        order = np.argsort(-scores, kind="stable")[:k]
        return [(self.chunk_ids[i], float(scores[i])) for i in order if scores[i] > 0]
