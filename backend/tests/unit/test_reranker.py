"""Cross-encoder reranking and the D-13 selection rule (PROJECT_SPEC §8.2, §29)."""

from scripts.run_eval import pick_reranker
from src.retrieval.reranker import Reranker


class FakeCrossEncoder:
    """Scores a pair by how many question words appear in the passage."""

    def __init__(self):
        self.calls = 0

    def predict(self, pairs, batch_size, show_progress_bar):
        self.calls += 1
        return [sum(w in p.lower() for w in q.lower().split()) for q, p in pairs]


CANDIDATES = [("c1", "change control system"), ("c2", "audit trail review of changes"),
              ("c3", "audit trail retention"), ("c4", "unrelated text")]


def test_rerank_sorts_by_score_and_keeps_all_candidates():
    model = FakeCrossEncoder()
    out = Reranker("x", model=model).rerank("audit trail review", CANDIDATES)
    assert [s.chunk_id for s in out] == ["c2", "c3", "c1", "c4"]
    assert [s.score for s in out] == [3.0, 2.0, 0.0, 0.0]
    assert model.calls == 1  # one batched pass for all pairs


def test_ties_keep_retrieval_order():
    out = Reranker("x", model=FakeCrossEncoder()).rerank("zzz", CANDIDATES)
    assert [s.chunk_id for s in out] == ["c1", "c2", "c3", "c4"]


def test_empty_candidates():
    assert Reranker("x", model=FakeCrossEncoder()).rerank("q", []) == []


def report(name, hit5, p50):
    return {"reranker_model": name, "metrics": {"hit@5": hit5},
            "latency_ms": {"rerank": {"p50": p50, "p90": p50 * 1.5}}}


def test_d13_best_hit5_within_budget():
    winner, _ = pick_reranker([report("fast", 0.80, 300), report("slow", 0.90, 1500)])
    assert winner["reranker_model"] == "slow"


def test_d13_within_two_points_prefers_faster():
    winner, reason = pick_reranker([report("fast", 0.89, 300), report("slow", 0.90, 1500)])
    assert winner["reranker_model"] == "fast" and "faster" in reason


def test_d13_excludes_models_over_the_latency_budget():
    winner, _ = pick_reranker([report("fast", 0.80, 300), report("too-slow", 0.99, 2500)])
    assert winner["reranker_model"] == "fast"
    none, reason = pick_reranker([report("too-slow", 0.99, 2500)])
    assert none is None and "budget" in reason
