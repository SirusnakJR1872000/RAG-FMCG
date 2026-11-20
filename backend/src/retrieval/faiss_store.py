"""Dense index: FAISS IndexFlatIP over normalised vectors (PROJECT_SPEC §8.1, §15.4).

Stored in FAISS's native format plus JSON; never pickle (SEC-11).
Row i of the index ↔ chunk_ids[i] in chunk_ids.json.
"""

import json
from pathlib import Path

import faiss
import numpy as np

INDEX_FILE = "index.faiss"
IDS_FILE = "chunk_ids.json"


class FaissStore:
    def __init__(self, index: faiss.Index, chunk_ids: list[str]):
        if index.ntotal != len(chunk_ids):
            raise ValueError(f"index has {index.ntotal} vectors but {len(chunk_ids)} chunk ids")
        self.index = index
        self.chunk_ids = chunk_ids

    @classmethod
    def build(cls, vectors: np.ndarray, chunk_ids: list[str]) -> "FaissStore":
        vectors = np.ascontiguousarray(vectors, dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1)
        if not np.allclose(norms, 1.0, atol=1e-3):
            raise ValueError("vectors must be L2-normalised (inner product = cosine)")
        index = faiss.IndexFlatIP(vectors.shape[1])  # exact search, no training needed
        index.add(vectors)
        return cls(index, list(chunk_ids))

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, str(directory / INDEX_FILE))
        (directory / IDS_FILE).write_text(json.dumps(self.chunk_ids), encoding="utf-8")

    @classmethod
    def load(cls, directory: Path) -> "FaissStore":
        index = faiss.read_index(str(directory / INDEX_FILE))
        chunk_ids = json.loads((directory / IDS_FILE).read_text(encoding="utf-8"))
        return cls(index, chunk_ids)

    def search(self, query: np.ndarray, k: int) -> list[tuple[str, float]]:
        """Top-k (chunk_id, cosine similarity), best first."""
        scores, rows = self.index.search(np.ascontiguousarray(query, dtype=np.float32), k)
        return [(self.chunk_ids[r], float(s)) for r, s in zip(rows[0], scores[0], strict=True)
                if r != -1]
