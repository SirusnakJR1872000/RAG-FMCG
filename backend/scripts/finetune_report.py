"""Adopt the fine-tuned model or not (D-12, PROJECT_SPEC §10.4) → reports/finetune_results.md.

Usage (from backend/):
  python -m scripts.finetune_report --dev-only     # preview: dev numbers and the decision
  python -m scripts.finetune_report                # final: decision on dev, test reported ONCE

The decision uses the DEV split only, with the full pipeline (hybrid + reranker). The test split
is run once, after the decision, and only reported (§11.1): to stop test numbers from steering
decisions, the script refuses to overwrite an existing report unless --force is given.
"""

import argparse
import datetime as dt
import json
import sys
from dataclasses import dataclass

from config import Settings, get_settings
from scripts.build_index import git_commit
from scripts.run_eval import Evaluator
from src.finetuning.train_embeddings import output_dir
from src.retrieval.reranker import Reranker

# §10.4
MIN_HIT5_GAIN = 0.02  # 2 points
MIN_MRR_GAIN = 0.02
MAX_DROP = 0.01  # no drop larger than 1 point in either metric
EPS = 1e-9  # floating point: 0.0556 - 0.0357 must not fall a hair short of 0.02


@dataclass(frozen=True)
class Decision:
    adopt: bool
    delta_hit5: float
    delta_mrr: float
    reasons: list[str]


def decide(base: dict, tuned: dict) -> Decision:
    """The §10.4 rule on two metric dicts (keys hit@5 and mrr@10)."""
    d5 = tuned["hit@5"] - base["hit@5"]
    dm = tuned["mrr@10"] - base["mrr@10"]
    improved = d5 >= MIN_HIT5_GAIN - EPS or dm >= MIN_MRR_GAIN - EPS
    no_drop = d5 >= -MAX_DROP - EPS and dm >= -MAX_DROP - EPS
    reasons = [
        f"Hit@5 {d5 * 100:+.1f} points (needs ≥ +{MIN_HIT5_GAIN * 100:.0f}) "
        f"or MRR@10 {dm:+.3f} (needs ≥ +{MIN_MRR_GAIN:.2f}): "
        f"{'improved' if improved else 'no sufficient improvement'}",
        f"no drop larger than {MAX_DROP * 100:.0f} point in either metric: "
        f"{'true' if no_drop else 'false'}"]
    return Decision(improved and no_drop, d5, dm, reasons)


def _rank(rank: int | None) -> str:
    return "not in top 10" if rank is None else f"rank {rank}"


def rank_changes(base: list[dict], tuned: list[dict]) -> list[str]:
    """One line per question whose first-hit rank changed."""
    after = {q["id"]: q["first_hit_rank"] for q in tuned}
    lines = []
    for q in base:
        before, now = q["first_hit_rank"], after[q["id"]]
        if before != now:
            lines.append(f"- {q['id']} {q['question'][:70]}: {_rank(before)} → {_rank(now)}")
    return lines or ["- no question changed rank"]


def table(rows: list[tuple[str, dict]]) -> list[str]:
    lines = ["| Configuration | Hit@1 | Hit@5 | MRR@10 |", "|---|---|---|---|"]
    for name, m in rows:
        lines.append(f"| {name} | {m['hit@1']:.3f} | {m['hit@5']:.3f} | {m['mrr@10']:.3f} |")
    return lines


def run_split(settings: Settings, split: str, base: str, tuned: str, reranker: Reranker) -> dict:
    ev = Evaluator(settings, split)
    runs = {}
    for label, model in (("base", base), ("tuned", tuned)):
        runs[label] = {"full": ev.run("hybrid", model, reranker),
                       "retrieval": ev.run("hybrid", model)}
    return {"n": len(ev.items), "runs": runs}


def section(title: str, result: dict) -> list[str]:
    runs, n = result["runs"], result["n"]
    full_b, full_t = runs["base"]["full"], runs["tuned"]["full"]
    ret_b, ret_t = runs["base"]["retrieval"], runs["tuned"]["retrieval"]
    return [
        f"## {title}", "",
        f"{n} answerable questions: one question = {100 / n:.1f} points.", "",
        *table([("Base, full pipeline (hybrid + reranker)", full_b["metrics"]),
                ("**Fine-tuned**, full pipeline", full_t["metrics"]),
                ("Base, retrieval only (hybrid, no reranker)", ret_b["metrics"]),
                ("Fine-tuned, retrieval only", ret_t["metrics"])]),
        "", "Questions whose result changed (full pipeline):", "",
        *rank_changes(full_b["questions"], full_t["questions"]), ""]


def main() -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dev-only", action="store_true", help="preview, writes nothing")
    parser.add_argument("--force", action="store_true", help="overwrite an existing report")
    args = parser.parse_args()

    tuned_dir = output_dir(settings, settings.embedding_model)
    if not tuned_dir.is_dir():
        print(f"{tuned_dir} not found. Train first: python -m src.finetuning.train_embeddings")
        return 1
    tuned = f"models/{tuned_dir.name}"
    report_path = settings.reports_dir / "finetune_results.md"
    if not args.dev_only and report_path.exists() and not args.force:
        print(f"{report_path} exists. The test split is reported once (§11.1); "
              "use --force only if the model was retrained on purpose.")
        return 1

    reranker = Reranker(settings.reranker_model)
    dev = run_split(settings, "dev", settings.embedding_model, tuned, reranker)
    full = {k: dev["runs"][k]["full"]["metrics"] for k in ("base", "tuned")}
    decision = decide(full["base"], full["tuned"])
    print(f"dev  base {full['base']}\n     tuned {full['tuned']}")
    verdict = "ADOPT" if decision.adopt else "DO NOT ADOPT"
    print(f"decision: {verdict}  " + "; ".join(decision.reasons))
    if args.dev_only:
        return 0

    test = run_split(settings, "test", settings.embedding_model, tuned, reranker)  # once
    config = json.loads((tuned_dir / "training_config.json").read_text())
    lines = [
        "# Fine-tuning results (D-12)", "",
        f"Generated by `python -m scripts.finetune_report` on {dt.date.today().isoformat()}, git "
        f"commit `{git_commit()}`.",
        f"Base `{settings.embedding_model}` vs fine-tuned `{tuned}`; reranker "
        f"`{settings.reranker_model}`; golden set split dev/test as in §11.1.", "",
        f"## Decision: {'ADOPT the fine-tuned model' if decision.adopt else 'DO NOT ADOPT'}", "",
        "Rule (§10.4, decided on the **dev** split with the full pipeline): adopt if dev Hit@5 "
        "improves by ≥ 2 points or MRR@10 by ≥ 0.02, with no drop larger than 1 point in either.",
        "", *(f"- {r}" for r in decision.reasons), "",
        "## Training", "",
        f"- {config['train_pairs']} training pairs, {config['val_pairs']} validation pairs "
        f"(whole chunks held out); {config['total_steps']} steps of batch "
        f"{config['batch_size']}, {config['epochs']} epochs, learning rate "
        f"{config['learning_rate']}, seed {config['seed']}.",
        f"- Validation loss {config['start_val_loss']} → {config['best_val_loss']} "
        f"(best checkpoint at step {config['best_step']}"
        f"{'; the base weights were kept' if config['kept_base_weights'] else ''}).",
        "- Questions were generated by llama3.2:3b; chunks answering test-split questions were "
        "excluded (`reports/train_data_stats.md`).", "",
        *section("Dev split (the decision)", dev),
        *section("Test split (reported once, not used for any decision)", test),
        "## Caveats", "",
        f"- Dev has {dev['n']} and test {test['n']} answerable questions: differences of one "
        "question are within noise, and the reranker already lifts both models close to the "
        "ceiling, so there is little room to gain.",
        "- Dev-split answer chunks were part of the training chunks (§10.2 excludes only test), so "
        "the dev comparison can be optimistic; the test split is the clean number.", ""]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    (settings.reports_dir / "finetune_results.json").write_text(
        json.dumps({"decision": decision.__dict__, "dev": dev, "test": test}, indent=2,
                   default=str), encoding="utf-8")
    print(f"wrote {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
