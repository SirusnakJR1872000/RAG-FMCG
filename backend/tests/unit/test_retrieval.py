"""Embeddings prefixes, FAISS store, BM25, RRF and metrics (PROJECT_SPEC §8, §11.2).

A fake embedding model (bag of words hashed into 64 dimensions) keeps these tests offline.
"""

import json
import zlib

import numpy as np
import pytest

from src.evaluation.golden import Expected, GoldenItem, SectionTree
from src.evaluation.metrics import QuestionResult, first_hit_rank, score
from src.ingestion.sections import Section
from src.retrieval.bm25_store import BM25Store, tokenize
from src.retrieval.embeddings import Embedder, prefixes_for
from src.retrieval.faiss_store import FaissStore
from src.retrieval.hybrid import HybridRetriever, rrf


class FakeModel:
    """Deterministic bag-of-words vectors; records what it was asked to encode."""

    dim = 64

    def __init__(self):
        self.seen: list[str] = []

    def get_embedding_dimension(self):
        return self.dim

    def encode(self, texts, batch_size, normalize_embeddings, convert_to_numpy,
               show_progress_bar):
        self.seen += texts
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            for word in tokenize(text):
                out[i, zlib.crc32(word.encode()) % self.dim] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.where(norms == 0, 1, norms)


DOCS = {
    "Q7:11.15": "out of specification results must be investigated and documented",
    "Q7:13": "change control system evaluates all changes to production",
    "A11:9": "audit trails record changes and deletions of gmp data",
    "A11:12": "access to computerised systems restricted to authorised persons",
}


# ── prefixes (§8.3) ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(("name", "query", "passage"), [
    ("sentence-transformers/all-MiniLM-L6-v2", "", ""),
    ("BAAI/bge-small-en-v1.5", "Represent this sentence for searching relevant passages: ", ""),
    ("intfloat/e5-small-v2", "query: ", "passage: "),
    ("models/pharma-e5-small-v2-v1", "query: ", "passage: "),  # fine-tuned keeps its family
])
def test_model_specific_prefixes(name, query, passage):
    assert prefixes_for(name) == (query, passage)


def test_embedder_applies_prefixes_and_normalises():
    model = FakeModel()
    emb = Embedder("intfloat/e5-small-v2", model=model)
    vectors = emb.embed_passages(["audit trail text"])
    emb.embed_query("audit trail?")
    assert model.seen == ["passage: audit trail text", "query: audit trail?"]
    assert vectors.dtype == np.float32
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0)


# ── FAISS store (§8.1, §15.4) ─────────────────────────────────────────────────

def build_store():
    emb = Embedder("all-MiniLM-L6-v2", model=FakeModel())
    return emb, FaissStore.build(emb.embed_passages(list(DOCS.values())), list(DOCS))


def test_faiss_finds_most_similar_chunk():
    emb, store = build_store()
    hits = store.search(emb.embed_query("who may access computerised systems"), k=2)
    assert hits[0][0] == "A11:12"
    assert hits[0][1] >= hits[1][1]


def test_faiss_round_trip_uses_native_format_and_json(tmp_path):
    emb, store = build_store()
    store.save(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["chunk_ids.json", "index.faiss"]
    assert json.loads((tmp_path / "chunk_ids.json").read_text()) == list(DOCS)
    loaded = FaissStore.load(tmp_path)
    query = emb.embed_query("audit trails")
    assert loaded.search(query, 4) == store.search(query, 4)


def test_faiss_rejects_unnormalised_vectors_and_id_mismatch():
    with pytest.raises(ValueError, match="normalised"):
        FaissStore.build(np.ones((2, 4), dtype=np.float32), ["a", "b"])
    with pytest.raises(ValueError, match="chunk ids"):
        FaissStore.build(np.eye(2, dtype=np.float32), ["a"])


# ── BM25 (§8.1) ───────────────────────────────────────────────────────────────

def test_tokenize_keeps_section_numbers():
    assert tokenize("ICH Q7 §11.15: OOS, a b") == ["ich", "q7", "11", "15", "oos"]


def test_bm25_ranks_term_overlap_and_skips_zero_scores():
    store = BM25Store(list(DOCS), list(DOCS.values()))
    hits = store.search("audit trails deletions", k=10)
    assert hits[0][0] == "A11:9"
    assert all(s > 0 for _, s in hits) and len(hits) < len(DOCS)


# ── RRF (§8.4) ────────────────────────────────────────────────────────────────

def test_rrf_scores_match_the_formula():
    fused = {f.chunk_id: f for f in rrf(["a", "b", "c"], ["c", "a"], k=60, top=10)}
    assert fused["a"].score == pytest.approx(1 / 61 + 1 / 62)
    assert fused["c"].score == pytest.approx(1 / 63 + 1 / 61)
    assert fused["b"].score == pytest.approx(1 / 62)  # missing from sparse: adds nothing


def test_rrf_order_and_tie_break_by_dense_rank():
    # x: dense 1 only; y: sparse 1 only → equal scores, x wins on dense rank
    assert [f.chunk_id for f in rrf(["x", "z"], ["y", "z"], k=60, top=3)] == ["z", "x", "y"]


def test_rrf_truncates_to_top():
    assert len(rrf(list("abcdef"), list("ghij"), k=60, top=4)) == 4


def test_hybrid_retriever_modes():
    emb, store = build_store()
    retriever = HybridRetriever(emb, store, BM25Store(list(DOCS), list(DOCS.values())),
                                candidates=3, rrf_k=60)
    for mode in ("dense", "bm25", "hybrid"):
        assert retriever.search("audit trail deletions", mode)[0] == "A11:9"
    with pytest.raises(ValueError):
        retriever.search("x", "magic")


# ── metrics (§11.2) ───────────────────────────────────────────────────────────

TREES = {"ICH-Q7": SectionTree.from_sections([
    Section("11", "", None, True), Section("11.1", "", "11", True),
    Section("11.14", "", "11.1", False), Section("11.15", "", "11.1", False),
    Section("13", "", None, True)])}
ITEM = GoldenItem(id="G-001", split="dev", answerable=True, question="What about OOS results?",
                  expected=[Expected(doc_code="ICH-Q7", section="11.15")], key_facts=["x"])


def test_first_hit_rank_uses_section_tree_and_ranges():
    ranked = [("ICH-Q7", "13"), ("WHO-GMP-MAIN", "11.15"), ("ICH-Q7", "11.14–11.15")]
    assert first_hit_rank(ITEM, ranked, TREES) == 3
    assert first_hit_rank(ITEM, ranked[:2], TREES) is None


def test_scores():
    results = [QuestionResult(f"G-{i}", "q", rank, []) for i, rank in
               enumerate([1, 2, 6, None])]
    s = score(results)
    assert s["n"] == 4
    assert s["hit@1"] == pytest.approx(1 / 4)
    assert s["hit@5"] == pytest.approx(2 / 4)
    assert s["mrr@10"] == pytest.approx((1 + 1 / 2 + 1 / 6) / 4)
