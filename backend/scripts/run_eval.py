"""Retrieval evaluation on the golden set (PROJECT_SPEC §11.2, §11.3; START_HERE M3).

Usage (from backend/):
  python -m scripts.run_eval --split dev --retriever hybrid --model BAAI/bge-small-en-v1.5
  python -m scripts.run_eval --split dev --benchmark        # D-11: all models → model_benchmark.md

Reports go to reports/eval_<config>_<split>_<date>.{json,md}. Every report records the git
commit, the index build_info and the model names. The test split is for final numbers only
(§11.1): it needs --allow-test, so it can't be run by accident while tuning.
"""

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import pandas as pd

from config import PROJECT_ROOT, Settings, get_settings
from scripts.build_index import build, git_commit, index_dir, model_slug
from src.evaluation.golden import GoldenItem, load_golden, load_section_trees
from src.evaluation.metrics import QuestionResult, first_hit_rank, score
from src.retrieval.bm25_store import BM25Store
from src.retrieval.embeddings import Embedder
from src.retrieval.faiss_store import FaissStore
from src.retrieval.hybrid import HybridRetriever

GOLDEN = PROJECT_ROOT / "backend/tests/golden/golden_set.jsonl"
CANDIDATE_MODELS = [  # PROJECT_SPEC §10.1 (D-11), smallest first for the final tie-break
    "sentence-transformers/all-MiniLM-L6-v2",
    "BAAI/bge-small-en-v1.5",
    "intfloat/e5-small-v2",
]
TIE_POINTS = 0.02  # §10.1: Hit@5 difference < 2 points is a tie


class Evaluator:
    def __init__(self, settings: Settings, split: str):
        self.settings = settings
        self.split = split
        self.chunks = pd.read_parquet(settings.data_dir / "chunks.parquet")
        self.where = dict(zip(self.chunks["chunk_id"],
                              zip(self.chunks["doc_code"], self.chunks["section"], strict=True),
                              strict=True))
        self.items = [g for g in load_golden(GOLDEN) if g.split == split and g.answerable]
        self.trees = load_section_trees(settings)
        self.bm25 = BM25Store(self.chunks["chunk_id"].tolist(), self.chunks["embed_text"].tolist())

    def retriever(self, model: str | None) -> tuple[HybridRetriever, dict | None]:
        if model is None:  # BM25 only
            return HybridRetriever(None, None, self.bm25, self.settings.candidates_per_retriever,
                                   self.settings.rrf_k), None
        directory = index_dir(self.settings, model)
        info_path = directory / "build_info.json"
        info = json.loads(info_path.read_text()) if info_path.is_file() else None
        if info is None or info["chunks_sha256"] != self._chunks_sha():
            print(f"  building index for {model} …")
            info = build(self.settings, model)
        retriever = HybridRetriever(Embedder(model), FaissStore.load(directory), self.bm25,
                                    self.settings.candidates_per_retriever, self.settings.rrf_k)
        return retriever, info

    def _chunks_sha(self) -> str:
        from src.ingestion.manifest import sha256_of

        return sha256_of(self.settings.data_dir / "chunks.parquet")

    def run(self, mode: str, model: str | None) -> dict:
        retriever, info = self.retriever(model)
        results, start = [], time.perf_counter()
        for item in self.items:
            ranked = [self.where[cid] for cid in retriever.search(item.question, mode)]
            results.append(self._result(item, ranked))
        seconds = time.perf_counter() - start
        return {
            "config": config_name(mode, model),
            "split": self.split,
            "retriever": mode,
            "embedding_model": model,
            "metrics": score(results),
            "seconds_per_query": round(seconds / max(len(results), 1), 3),
            "git_commit": git_commit(),
            "build_info": info,
            "settings": {"candidates_per_retriever": self.settings.candidates_per_retriever,
                         "rrf_k": self.settings.rrf_k,
                         "chunk_max_tokens": self.settings.chunk_max_tokens},
            "questions": [r.__dict__ for r in results],
        }

    def _result(self, item: GoldenItem, ranked: list[tuple[str, str]]) -> QuestionResult:
        return QuestionResult(item.id, item.question, first_hit_rank(item, ranked, self.trees),
                              [f"{d} §{s}" for d, s in ranked[:5]])


def config_name(mode: str, model: str | None) -> str:
    return mode if model is None else f"{mode}-{model_slug(model).split('__')[-1]}"


def metrics_row(report: dict) -> str:
    m = report["metrics"]
    return (f"| {report['retriever']} | {report['embedding_model'] or '—'} | {m['hit@1']:.2f} | "
            f"{m['hit@5']:.2f} | {m['mrr@10']:.2f} | {report['seconds_per_query']:.2f} |")


TABLE_HEAD = ["| Retriever | Embedding model | Hit@1 | Hit@5 | MRR@10 | s/query |",
              "|---|---|---|---|---|---|"]


def write_report(report: dict, reports_dir: Path) -> Path:
    stem = f"eval_{report['config']}_{report['split']}_{dt.date.today().isoformat()}"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"{stem}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    misses = [q for q in report["questions"] if q["first_hit_rank"] is None
              or q["first_hit_rank"] > 5]
    lines = [f"# Evaluation: {report['config']} ({report['split']})", "",
             f"Git commit `{report['git_commit']}` · {report['metrics']['n']} answerable "
             f"questions (one question = {100 / report['metrics']['n']:.1f} points)", "",
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


def benchmark(ev: Evaluator, reports_dir: Path) -> Path:
    reports = [ev.run("bm25", None)]
    for model in CANDIDATE_MODELS:
        reports += [ev.run("dense", model), ev.run("hybrid", model)]
    for r in reports:
        write_report(r, reports_dir)
        print(metrics_row(r))
    winner, reason = pick_model([r for r in reports if r["retriever"] == "hybrid"])
    n = reports[0]["metrics"]["n"]
    lines = [
        "# Embedding model benchmark (D-11)", "",
        f"Generated by `python -m scripts.run_eval --split {ev.split} --benchmark` on "
        f"{dt.date.today().isoformat()}, git commit `{reports[0]['git_commit']}`.",
        f"Split: **{ev.split}**, {n} answerable questions — one question = {100 / n:.1f} points.",
        f"Chunks: {len(ev.chunks)}; candidates per retriever: "
        f"{ev.settings.candidates_per_retriever}; RRF k = {ev.settings.rrf_k}; no reranker.",
        "", *TABLE_HEAD, *(metrics_row(r) for r in reports), "",
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--retriever", choices=["bm25", "dense", "hybrid"], default="hybrid")
    parser.add_argument("--model", default=None, help="default: EMBEDDING_MODEL from .env")
    parser.add_argument("--benchmark", action="store_true", help="D-11 model benchmark")
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
    model = None if args.retriever == "bm25" else (args.model or settings.embedding_model)
    report = ev.run(args.retriever, model)
    print("\n".join([*TABLE_HEAD, metrics_row(report)]))
    print(f"\nwrote {write_report(report, settings.reports_dir)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
