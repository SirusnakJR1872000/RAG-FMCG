"""The loaded search index and what the health endpoints report about it (PROJECT_SPEC §19.3).

Tier 1 holds one pipeline (embedding model, reranker, FAISS, BM25, chunk table) built once at
start-up. `index.swap()` is where Tier 2's rebuild-and-activate will replace it under a lock;
queries that started on the old pipeline finish on it.
"""

import threading


class IndexManager:
    def __init__(self, pipeline=None, error: str | None = None):
        self._lock = threading.Lock()
        self._pipeline = pipeline
        self.error = error  # why there is no index (shown to admins, never to the public)

    @property
    def pipeline(self):
        with self._lock:
            return self._pipeline

    @property
    def ready(self) -> bool:
        return self.pipeline is not None

    def swap(self, pipeline) -> None:
        with self._lock:
            self._pipeline = pipeline
            self.error = None

    @property
    def build_id(self) -> str | None:
        pipeline = self.pipeline
        return pipeline.index_info.get("build_id") if pipeline else None

    def describe(self) -> dict:
        pipeline = self.pipeline
        if pipeline is None:
            return {"ready": False, "error": self.error}
        info = pipeline.index_info
        return {"ready": True, "build_id": info.get("build_id"),
                "built_at": info.get("created_at"), "chunk_count": info.get("chunk_count"),
                "embedding_model": info.get("embedding_model"),
                "reranker_model": pipeline.settings.reranker_model}
