"""Section-level retrieval metrics: Hit@1, Hit@5, MRR@10 (PROJECT_SPEC §11.2).

Computed over answerable questions only (unanswerable ones are measured by refusal accuracy
once the relevance threshold exists, §8.5). A retrieved chunk is a hit when its section
equals or is a subsection of an expected section (golden.is_hit).
"""

from dataclasses import dataclass

from src.evaluation.golden import GoldenItem, SectionTree, is_hit


@dataclass(frozen=True)
class QuestionResult:
    id: str
    question: str
    first_hit_rank: int | None  # 1-based rank of the first hit in the top 10, None if no hit
    top_sections: list[str]  # "doc_code §section" of the top 5, for reading failures


def first_hit_rank(item: GoldenItem, ranked: list[tuple[str, str]],
                   trees: dict[str, SectionTree], depth: int = 10) -> int | None:
    """ranked: (doc_code, section) of retrieved chunks, best first."""
    for rank, (doc_code, section) in enumerate(ranked[:depth], start=1):
        if is_hit(trees, doc_code, section, item.expected):
            return rank
    return None


def score(results: list[QuestionResult]) -> dict[str, float | int]:
    n = len(results)
    if n == 0:
        return {"n": 0, "hit@1": 0.0, "hit@5": 0.0, "mrr@10": 0.0}
    ranks = [r.first_hit_rank for r in results]
    return {
        "n": n,
        "hit@1": sum(1 for r in ranks if r == 1) / n,
        "hit@5": sum(1 for r in ranks if r is not None and r <= 5) / n,
        "mrr@10": sum(1 / r for r in ranks if r is not None) / n,
    }
