"""Latency summary maths (the measurement itself needs the real model)."""

from scripts.measure_latency import STAGE_LABEL, TARGETS_MS, render, stage_values, summarise
from src.generation.pipeline import Result


def run(answer_type="answered", **lat):
    base = {"rewrite": 0, "retrieval": 20, "rerank": 800, "ttft": 9000, "generation": 40000,
            "total": 50000}
    return ("q", Result(answer_type, "a", "q", [], None, 1.0, {**base, **lat}))


def test_summarise_percentiles():
    s = summarise([100, 200, 300, 400, 1000])
    assert (s["n"], s["p50"], s["p90"]) == (5, 300, 760)
    assert summarise([]) == {"n": 0, "p50": 0.0, "p90": 0.0}


def test_rewrite_only_counts_turns_that_had_one():
    runs = [run(), run(rewrite=4000), run(rewrite=6000)]
    assert stage_values(runs, "rewrite") == [4000, 6000]


def test_refusals_have_no_first_token_time():
    runs = [run(), run("retrieval_refusal", ttft=0, total=900)]
    assert stage_values(runs, "ttft") == [9000]
    assert stage_values(runs, "retrieval") == [20, 20]  # they still did retrieval


def test_render_marks_met_and_missed_targets_and_lists_the_remedies():
    fast = {"n": 3, "p50": 10, "p90": 20}
    stages = {k: dict(fast) for k in STAGE_LABEL}
    stages["ttft"] = {"n": 3, "p50": 41_000, "p90": 55_000}  # target is 30 s
    report = {
        "date": "2026-11-24", "git_commit": "abc", "llm_model": "llama3.1:8b", "num_ctx": 4096,
        "embedding_model": "e", "reranker_model": "r", "cpus": 12, "n_single": 1,
        "n_conversation": 3, "stages": stages,
        "llm": {"tokens_per_second_p50": 3.1, "completion_tokens_p50": 120,
                "prompt_tokens_p50": 1500, "prompt_tokens_max": 1700, "answers": 4,
                "truncated": 0, "citation_ok": 4, "citation_invalid": 0, "citation_uncited": 0,
                "retrieval_refusals": 0, "model_refusals": 0},
        "memory": {"backend_peak_rss_mb": 2100, "ollama_resident_mb": 5900},
        "mem_before": {"MemAvailable": 6000, "MemTotal": 15657, "SwapUsed": 3000,
                       "SwapTotal": 4095},
        "mem_after": {"MemAvailable": 5000, "SwapUsed": 3100},
        "questions": [{"question": "q", "answer_type": "answered", "rewrite": 0, "retrieval": 20,
                       "rerank": 800, "ttft": 9000, "total": 50000, "completion_tokens": 100}]}
    md = render(report)
    assert md.count("✅ met") == 4 and md.count("❌ missed") == 1
    assert "Time to first token (from request) | ≤ 30,000 | 41,000" in md
    assert "None has been applied yet" in md and "context 4 → 3 chunks" in md
    assert TARGETS_MS["total"] == 90_000
