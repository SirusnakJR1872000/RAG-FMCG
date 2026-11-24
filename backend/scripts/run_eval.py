"""Retrieval evaluation on the golden set (PROJECT_SPEC §11.2, §11.3; START_HERE M3, M4).

Usage (from backend/):
  python -m scripts.run_eval --split dev --retriever hybrid            # EMBEDDING_MODEL from .env
  python -m scripts.run_eval --split dev --retriever hybrid --rerank   # + RERANKER_MODEL
  python -m scripts.run_eval --split dev --benchmark                   # D-11 → model_benchmark.md
  python -m scripts.run_eval --split dev --rerank-benchmark     # D-13 → reranker_benchmark.md

Reports go to reports/eval_<config>_<split>_<date>.{json,md}. Every report records the git
commit, the index build_info and the model names. Latencies are measured after one warm-up
query (§20). The test split is for final numbers only (§11.1): it needs --allow-test.
"""

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from config import PROJECT_ROOT, Settings, get_settings
from scripts.build_index import build, git_commit
from src.evaluation.golden import GoldenItem, load_golden, load_section_trees
from src.evaluation.metrics import QuestionResult, first_hit_rank, score
from src.ingestion.manifest import sha256_of
from src.retrieval.bm25_store import BM25Store
from src.retrieval.embeddings import Embedder
from src.retrieval.faiss_store import FaissStore
from src.retrieval.hybrid import HybridRetriever
from src.retrieval.indexes import index_dir, model_slug
from src.retrieval.reranker import Reranker

GOLDEN = PROJECT_ROOT / "backend/tests/golden/golden_set.jsonl"
CANDIDATE_MODELS = [  # PROJECT_SPEC §10.1 (D-11), smallest first for the final tie-break
    "sentence-transformers/all-MiniLM-L6-v2",
    "BAAI/bge-small-en-v1.5",
    "intfloat/e5-small-v2",
]
CANDIDATE_RERANKERS = [  # PROJECT_SPEC §5.4 (D-13)
    "cross-encoder/ms-marco-MiniLM-L-6-v2",
    "BAAI/bge-reranker-base",
]
TIE_POINTS = 0.02  # §10.1 / D-13: a Hit@5 difference < 2 points is a tie
RERANK_BUDGET_MS = 2000  # §20 / D-13: p50 reranking of 20 candidates ≤ 2 s


def short(model: str) -> str:
    return model_slug(model).split("__")[-1]


def percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p50": 0.0, "p90": 0.0}
    return {"p50": round(float(np.percentile(values, 50)), 1),
            "p90": round(float(np.percentile(values, 90)), 1)}


class Evaluator:
    def __init__(self, settings: Settings, split: str):
        self.settings = settings
        self.split = split
        self.chunks = pd.read_parquet(settings.data_dir / "chunks.parquet")
        self.where = dict(zip(self.chunks["chunk_id"],
                              zip(self.chunks["doc_code"], self.chunks["section"], strict=True),
                              strict=True))
        self.text = dict(zip(self.chunks["chunk_id"], self.chunks["embed_text"], strict=True))
        self.items = [g for g in load_golden(GOLDEN) if g.split == split and g.answerable]
        self.trees = load_section_trees(settings)
        self.bm25 = BM25Store(self.chunks["chunk_id"].tolist(), self.chunks["embed_text"].tolist())
        self.chunks_sha = sha256_of(settings.data_dir / "chunks.parquet")

    def retriever(self, model: str | None) -> tuple[HybridRetriever, dict | None]:
        s = self.settings
        if model is None:  # BM25 only
            return HybridRetriever(None, None, self.bm25, s.candidates_per_retriever, s.rrf_k), None
        directory = index_dir(s, model)
        info_path = directory / "build_info.json"
        info = json.loads(info_path.read_text()) if info_path.is_file() else None
        if info is None or info["chunks_sha256"] != self.chunks_sha:
            print(f"  building index for {model} …")
            info = build(s, model)
        retriever = HybridRetriever(Embedder(model), FaissStore.load(directory), self.bm25,
                                    s.candidates_per_retriever, s.rrf_k)
        return retriever, info

    def run(self, mode: str, model: str | None, reranker: Reranker | None = None) -> dict:
        retriever, info = self.retriever(model)
        if self.items:  # warm-up: load models and caches before timing (§20)
            self._rank(retriever, mode, reranker, self.items[0].question)
        results, retrieval_ms, rerank_ms = [], [], []
        for item in self.items:
            ids, t_retrieval, t_rerank = self._rank(retriever, mode, reranker, item.question)
            retrieval_ms.append(t_retrieval)
            if reranker:
                rerank_ms.append(t_rerank)
            results.append(self._result(item, [self.where[c] for c in ids]))
        return {
            "config": config_name(mode, model, reranker),
            "split": self.split,
            "retriever": mode,
            "embedding_model": model,
            "reranker_model": reranker.model_name if reranker else None,
            "metrics": score(results),
            "latency_ms": {"retrieval": percentiles(retrieval_ms),
                           "rerank": percentiles(rerank_ms) if reranker else None},
            "git_commit": git_commit(),
            "build_info": info,
            "settings": {"candidates_per_retriever": self.settings.candidates_per_retriever,
                         "rrf_k": self.settings.rrf_k,
                         "chunk_max_tokens": self.settings.chunk_max_tokens},
            "questions": [r.__dict__ for r in results],
        }

    def _rank(self, retriever: HybridRetriever, mode: str, reranker: Reranker | None,
              question: str) -> tuple[list[str], float, float]:
        start = time.perf_counter()
        ids = retriever.search(question, mode)
        mid = time.perf_counter()
        if reranker:
            ids = [s.chunk_id for s in reranker.rerank(question, [(c, self.text[c]) for c in ids])]
        end = time.perf_counter()
        return ids, (mid - start) * 1000, (end - mid) * 1000

    def _result(self, item: GoldenItem, ranked: list[tuple[str, str]]) -> QuestionResult:
        return QuestionResult(item.id, item.question, first_hit_rank(item, ranked, self.trees),
                              [f"{d} §{s}" for d, s in ranked[:5]])


def config_name(mode: str, model: str | None, reranker: Reranker | None = None) -> str:
    name = mode if model is None else f"{mode}-{short(model)}"
    return f"{name}+rerank-{short(reranker.model_name)}" if reranker else name


TABLE_HEAD = ["| Retriever | Embedding model | Reranker | Hit@1 | Hit@5 | MRR@10 "
              "| retrieval p50 ms | rerank p50 / p90 ms |",
              "|---|---|---|---|---|---|---|---|"]


def metrics_row(report: dict) -> str:
    m, lat = report["metrics"], report["latency_ms"]
    rerank = f"{lat['rerank']['p50']:.0f} / {lat['rerank']['p90']:.0f}" if lat["rerank"] else "—"
    return (f"| {report['retriever']} | {short(report['embedding_model'] or '—')} | "
            f"{short(report['reranker_model'] or '—')} | {m['hit@1']:.2f} | {m['hit@5']:.2f} | "
            f"{m['mrr@10']:.2f} | {lat['retrieval']['p50']:.0f} | {rerank} |")


def write_report(report: dict, reports_dir: Path) -> Path:
    stem = f"eval_{report['config']}_{report['split']}_{dt.date.today().isoformat()}"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"{stem}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    misses = [q for q in report["questions"] if q["first_hit_rank"] is None
              or q["first_hit_rank"] > 5]
    n = report["metrics"]["n"]
    lines = [f"# Evaluation: {report['config']} ({report['split']})", "",
             f"Git commit `{report['git_commit']}` · {n} answerable questions "
             f"(one question = {100 / n:.1f} points)", "",
             *TABLE_HEAD, metrics_row(report), "", "## Questions not hit in the top 5", ""]
    lines += [f"- {q['id']} {q['question']} → top: {', '.join(q['top_sections'][:3])}"
              for q in misses] or ["- none"]
    path = reports_dir / f"{stem}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def pick_model(hybrid: list[dict]) -> tuple[dict, str]:
    """PROJECT_SPEC §10.1: best Hit@5; within 2 points → best MRR@10; still tied → smaller."""
    best = max(r["metrics"]["hit@5"] for r in hybrid)
    tied = [r for r in hybrid if best - r["metrics"]["hit@5"] < TIE_POINTS]
    if len(tied) == 1:
        return tied[0], "highest dev Hit@5"
    best_mrr = max(r["metrics"]["mrr@10"] for r in tied)
    still = [r for r in tied if best_mrr - r["metrics"]["mrr@10"] < 1e-9]
    if len(still) == 1:
        return still[0], "Hit@5 within 2 points; highest MRR@10"
    order = {m: i for i, m in enumerate(CANDIDATE_MODELS)}
    return min(still, key=lambda r: order[r["embedding_model"]]), "tied; smaller model"


def pick_reranker(reranked: list[dict]) -> tuple[dict | None, str]:
    """D-13: best Hit@5 among rerankers with p50 ≤ 2 s; within 2 points → the faster one."""
    def p50(r: dict) -> float:
        return r["latency_ms"]["rerank"]["p50"]

    eligible = [r for r in reranked if p50(r) <= RERANK_BUDGET_MS]
    if not eligible:
        return None, f"no reranker meets the p50 ≤ {RERANK_BUDGET_MS} ms budget"
    best = max(r["metrics"]["hit@5"] for r in eligible)
    tied = [r for r in eligible if best - r["metrics"]["hit@5"] < TIE_POINTS]
    winner = min(tied, key=p50)
    reason = ("highest dev Hit@5 within the latency budget" if len(tied) == 1
              else "Hit@5 within 2 points; faster p50")
    return winner, reason


def header(ev: Evaluator, reports: list[dict], title: str, command: str) -> list[str]:
    n = reports[0]["metrics"]["n"]
    return [
        f"# {title}", "",
        f"Generated by `python -m scripts.run_eval --split {ev.split} {command}` on "
        f"{dt.date.today().isoformat()}, git commit `{reports[0]['git_commit']}`.",
        f"Split: **{ev.split}**, {n} answerable questions — one question = {100 / n:.1f} points.",
        f"Chunks: {len(ev.chunks)}; candidates per retriever: "
        f"{ev.settings.candidates_per_retriever}; RRF k = {ev.settings.rrf_k}. Latencies on this "
        "machine (CPU), after one warm-up query.", "",
        *TABLE_HEAD, *(metrics_row(r) for r in reports), "",
    ]


def benchmark(ev: Evaluator, reports_dir: Path) -> Path:
    reports = [ev.run("bm25", None)]
    for model in CANDIDATE_MODELS:
        reports += [ev.run("dense", model), ev.run("hybrid", model)]
    for r in reports:
        write_report(r, reports_dir)
        print(metrics_row(r))
    winner, reason = pick_model([r for r in reports if r["retriever"] == "hybrid"])
    lines = [
        *header(ev, reports, "Embedding model benchmark (D-11)", "--benchmark"),
        "No reranker.", "",
        "## Decision (rule from PROJECT_SPEC §10.1, applied by the script)", "",
        "Highest **hybrid** dev Hit@5; if within 2 points, higher MRR@10; if still tied, the "
        "smaller and faster model.", "",
        f"**Selected: `{winner['embedding_model']}`** — {reason} "
        f"(Hit@5 {winner['metrics']['hit@5']:.2f}, MRR@10 {winner['metrics']['mrr@10']:.2f}).",
        "", "Model versions:", "",
        *(f"- `{r['embedding_model']}` {r['build_info']['embedding_model_hash']}, "
          f"index built in {r['build_info']['embed_seconds']} s"
          for r in reports if r["retriever"] == "hybrid"),
        "", "## Why this model (owner's note)", "",
        "_To be written by the project owner (START_HERE M3: two sentences)._", "",
    ]
    path = reports_dir / "model_benchmark.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def rerank_benchmark(ev: Evaluator, reports_dir: Path) -> Path:
    model = ev.settings.embedding_model
    reports = [ev.run("hybrid", model)]
    for name in CANDIDATE_RERANKERS:
        reports.append(ev.run("hybrid", model, Reranker(name)))
    for r in reports:
        write_report(r, reports_dir)
        print(metrics_row(r))
    base = reports[0]["metrics"]
    winner, reason = pick_reranker(reports[1:])
    effect = [
        f"- `{short(r['reranker_model'])}`: Hit@1 {r['metrics']['hit@1'] - base['hit@1']:+.2f}, "
        f"Hit@5 {r['metrics']['hit@5'] - base['hit@5']:+.2f}, "
        f"MRR@10 {r['metrics']['mrr@10'] - base['mrr@10']:+.2f}; adds "
        f"{r['latency_ms']['rerank']['p50']:.0f} ms (p50) / {r['latency_ms']['rerank']['p90']:.0f}"
        f" ms (p90) per question" for r in reports[1:]
    ]
    lines = [
        *header(ev, reports, "Reranker benchmark (D-13)", "--rerank-benchmark"),
        f"Embedding model: `{model}` (D-11). Each reranker re-sorts the top "
        f"{ev.settings.candidates_per_retriever} hybrid candidates.", "",
        "## Effect of reranking (vs. hybrid without reranker)", "", *effect, "",
        "## Decision (rule D-13, applied by the script)", "",
        f"Best dev Hit@5 among rerankers with p50 ≤ {RERANK_BUDGET_MS} ms; within 2 points, "
        "the faster one.", "",
        (f"**Selected: `{winner['reranker_model']}`** — {reason} (Hit@5 "
         f"{winner['metrics']['hit@5']:.2f}, p50 {winner['latency_ms']['rerank']['p50']:.0f} ms)."
         if winner else f"**No reranker selected** — {reason}."),
        "", "Score scales differ (ms-marco: raw logits; bge-reranker: sigmoid 0–1), so the "
        "relevance threshold τ (§8.5) must be tuned for the selected reranker.", "",
    ]
    path = reports_dir / "reranker_benchmark.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--retriever", choices=["bm25", "dense", "hybrid"], default="hybrid")
    parser.add_argument("--model", default=None, help="default: EMBEDDING_MODEL from .env")
    parser.add_argument("--rerank", action="store_true", help="rerank with RERANKER_MODEL")
    parser.add_argument("--reranker", default=None, help="default: RERANKER_MODEL from .env")
    parser.add_argument("--benchmark", action="store_true", help="D-11 embedding benchmark")
    parser.add_argument("--rerank-benchmark", action="store_true", help="D-13 reranker benchmark")
    parser.add_argument("--allow-test", action="store_true",
                        help="required for --split test (final reporting only, §11.1)")
    args = parser.parse_args()
    if args.split == "test" and not args.allow_test:
        print("The test split is for final reporting only (§11.1). Use --allow-test to run it.")
        return 2
    settings = get_settings()
    ev = Evaluator(settings, args.split)
    if args.benchmark:
        print(f"\nwrote {benchmark(ev, settings.reports_dir)}")
        return 0
    if args.rerank_benchmark:
        print(f"\nwrote {rerank_benchmark(ev, settings.reports_dir)}")
        return 0
    model = None if args.retriever == "bm25" else (args.model or settings.embedding_model)
    reranker = Reranker(args.reranker or settings.reranker_model) if args.rerank else None
    report = ev.run(args.retriever, model, reranker)
    print("\n".join([*TABLE_HEAD, metrics_row(report)]))
    print(f"\nwrote {write_report(report, settings.reports_dir)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
