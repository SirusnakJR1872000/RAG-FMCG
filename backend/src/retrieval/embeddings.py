"""Sentence-transformers embeddings with model-specific prefixes (PROJECT_SPEC §8.1, §8.3).

Vectors are L2-normalised, so inner product (FAISS IndexFlatIP) equals cosine similarity.

Prefixes are chosen by model *family*, so a fine-tuned variant such as
"models/pharma-bge-small-en-v1.5-v1" (M6) keeps the input format its base model was trained on.
"""

from collections.abc import Sequence
from functools import cached_property

import numpy as np

# family marker in the model name → (query prefix, passage prefix), PROJECT_SPEC §8.3
PREFIXES: dict[str, tuple[str, str]] = {
    "bge-": ("Represent this sentence for searching relevant passages: ", ""),
    "e5-": ("query: ", "passage: "),
}


def prefixes_for(model_name: str) -> tuple[str, str]:
    """(query prefix, passage prefix) for a model name; ('', '') for e.g. all-MiniLM-L6-v2."""
    name = model_name.lower()
    for marker, pair in PREFIXES.items():
        if marker in name:
            return pair
    return "", ""


class Embedder:
    def __init__(self, model_name: str, batch_size: int = 32, model=None):
        self.model_name = model_name
        self.batch_size = batch_size
        self.query_prefix, self.passage_prefix = prefixes_for(model_name)
        self._injected = model  # tests pass a fake model; real runs load lazily

    @cached_property
    def model(self):
        if self._injected is not None:
            return self._injected
        from sentence_transformers import SentenceTransformer  # heavy: torch

        return SentenceTransformer(self.model_name, device="cpu")

    @property
    def dim(self) -> int:
        return int(self.model.get_sentence_embedding_dimension())

    def _encode(self, texts: Sequence[str], show_progress: bool = False) -> np.ndarray:
        vectors = self.model.encode(
            list(texts), batch_size=self.batch_size, normalize_embeddings=True,
            convert_to_numpy=True, show_progress_bar=show_progress,
        )
        return np.ascontiguousarray(vectors, dtype=np.float32)

    def embed_passages(self, texts: Sequence[str], show_progress: bool = False) -> np.ndarray:
        return self._encode([self.passage_prefix + t for t in texts], show_progress)

    def embed_query(self, text: str) -> np.ndarray:
        """Shape (1, dim)."""
        return self._encode([self.query_prefix + text])
