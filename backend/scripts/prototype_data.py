"""Export real data for the UI prototype: docs/prototype/data.js.

Usage (from backend/):  python -m scripts.prototype_data

The prototype (docs/prototype/index.html) is a design preview, not the M8 app. Everything it
shows comes from here: the document registry, all chunks (for in-browser keyword search),
measured benchmark numbers, and the full pipeline output — hybrid retrieval with
EMBEDDING_MODEL + reranking with RERANKER_MODEL — for a few example questions.
Only dev-split golden questions are used, so the test split stays unseen (§11.1).
"""

import json
import time

import pandas as pd

from config import PROJECT_ROOT, get_settings
from scripts.run_eval import GOLDEN, Evaluator
from src.evaluation.golden import load_golden
from src.ingestion.manifest import load_manifest
from src.retrieval.reranker import Reranker

EXAMPLE_IDS = ["G-001", "G-002", "G-008", "G-011", "G-013", "G-016", "G-019", "G-006"]
TOP_SOURCES = 4  # CONTEXT_CHUNKS: what generation will receive (§8.2 step 7)
EXCERPT_CHARS = 700


def main() -> None:
    settings = get_settings()
    chunks = pd.read_parquet(settings.data_dir / "chunks.parquet")
    by_id = chunks.set_index("chunk_id")
    entries = {e.doc_code: e for e in load_manifest(settings.manifest_path)}

    ev = Evaluator(settings, "dev")
    retriever, _ = ev.retriever(settings.embedding_model)
    reranker = Reranker(settings.reranker_model)
    golden = {g.id: g for g in load_golden(GOLDEN)}

    def source(n: int, chunk_id: str, score: float) -> dict:
        row = by_id.loc[chunk_id]
        e = entries[row.doc_code]
        return {
            "n": n, "chunk_id": chunk_id, "doc_code": row.doc_code, "doc_title": row.doc_title,
            "version": row.version, "section": row.section, "section_title": row.section_title,
            "page_start": None if pd.isna(row.page_start) else int(row.page_start),
            "page_end": None if pd.isna(row.page_end) else int(row.page_end),
            "fictional": e.is_fictional, "score": round(score, 2),
            "excerpt": row.text[:EXCERPT_CHARS],
        }

    warm = golden[EXAMPLE_IDS[0]].question  # warm-up both models before timing (§20)
    reranker.rerank(warm, [(c, by_id.loc[c].embed_text) for c in retriever.search(warm, "hybrid")])
    examples = []
    for gid in EXAMPLE_IDS:
        g = golden[gid]
        assert g.split == "dev", f"{gid} is not a dev question"
        t0 = time.perf_counter()
        ids = retriever.search(g.question, "hybrid")
        t1 = time.perf_counter()
        ranked = reranker.rerank(g.question, [(c, by_id.loc[c].embed_text) for c in ids])
        t2 = time.perf_counter()
        examples.append({
            "id": gid, "question": g.question,
            "sources": [source(i, s.chunk_id, s.score) for i, s in
                        enumerate(ranked[:TOP_SOURCES], start=1)],
            "latency_ms": {"retrieval": round((t1 - t0) * 1000), "rerank": round((t2 - t1) * 1000)},
        })
        print(f"  {gid}: {[s['doc_code'] + ' §' + s['section'] for s in examples[-1]['sources']]}")

    counts = chunks.groupby("doc_code").size().to_dict()
    documents = [{
        "doc_code": e.doc_code, "title": e.title, "version": e.version,
        "effective_date": e.effective_date.isoformat(), "publisher": e.publisher,
        "status": e.status, "passages": int(counts.get(e.doc_code, 0)),
        "fictional": e.is_fictional, "public": e.is_public,
    } for e in entries.values()]

    reports = settings.reports_dir
    rerank_report = json.loads(next(reports.glob(
        "eval_hybrid-e5-small-v2+rerank-ms-marco-MiniLM-L-6-v2_dev_*.json")).read_text())
    base_report = json.loads(next(reports.glob("eval_hybrid-e5-small-v2_dev_*.json")).read_text())
    data = {
        "generated_with": {"embedding_model": settings.embedding_model,
                           "reranker_model": settings.reranker_model,
                           "git_commit": rerank_report["git_commit"]},
        "stats": {
            "documents": len(documents), "public": sum(d["public"] for d in documents),
            "sops": sum(d["fictional"] for d in documents), "passages": len(chunks),
            "dev_questions": rerank_report["metrics"]["n"],
            "hybrid": base_report["metrics"], "reranked": rerank_report["metrics"],
            "rerank_p50_ms": rerank_report["latency_ms"]["rerank"]["p50"],
            "retrieval_p50_ms": rerank_report["latency_ms"]["retrieval"]["p50"],
        },
        "documents": documents,
        "examples": examples,
        "chunks": [{
            "id": r.chunk_id, "doc_code": r.doc_code, "doc_title": r.doc_title,
            "version": r.version, "section": r.section, "section_title": r.section_title,
            "page_start": None if pd.isna(r.page_start) else int(r.page_start),
            "page_end": None if pd.isna(r.page_end) else int(r.page_end),
            "fictional": entries[r.doc_code].is_fictional,
            "embed_text": r.embed_text, "text": r.text,
        } for r in chunks.itertuples()],
    }
    out = PROJECT_ROOT / "docs/prototype/data.js"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("// Generated by backend/scripts/prototype_data.py — do not edit.\n"
                   f"window.PROTO_DATA = {json.dumps(data, ensure_ascii=False)};\n",
                   encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
