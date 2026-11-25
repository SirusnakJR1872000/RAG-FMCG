"""Fine-tune the embedding model on the synthetic pairs (PROJECT_SPEC §10.3).

Usage (from backend/):  python -m src.finetuning.train_embeddings

Settings exactly as §10.3: start from the D-11 winner, MultipleNegativesRankingLoss, batch 32,
2 epochs, learning rate 2e-5 with 10 % warm-up, 10 % held out for validation, best checkpoint
by validation loss, seed 42. Output: models/pharma-<base>-v1/ + training_config.json +
training_log.json.

How MultipleNegativesRankingLoss learns: in a batch of 32 (question, passage) pairs, question i
must score passage i higher than the other 31 passages — those 31 are free "negatives". So
a bigger batch means harder questions, and the same passage must never appear twice in one batch
(it would be both the right answer and a "negative" for its twin question).

This is a plain PyTorch loop around sentence-transformers' own loss class: the Trainer API would
need two extra packages (`datasets`, `accelerate`) that are not in spec §5.
No pickle anywhere: weights are saved as safetensors, no optimizer state is written.
"""

import argparse
import datetime as dt
import json
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import sentence_transformers
import torch
import transformers
from sentence_transformers import SentenceTransformer
from sentence_transformers.sentence_transformer.losses import MultipleNegativesRankingLoss
from transformers import get_linear_schedule_with_warmup

from config import Settings, get_settings
from scripts.build_index import git_commit
from src.ingestion.manifest import sha256_of
from src.retrieval.embeddings import prefixes_for

# §10.3
BATCH_SIZE = 32
EPOCHS = 2
LEARNING_RATE = 2e-5
WARMUP_RATIO = 0.1
VAL_FRACTION = 0.1
SEED = 42
# not fixed by §10.3 — the library's usual values
SCALE = 20.0  # cosine scores are multiplied by this before the softmax
WEIGHT_DECAY = 0.01
MAX_GRAD_NORM = 1.0
EVALS_PER_EPOCH = 2  # validation loss twice per epoch → 4 candidate checkpoints + the start
MIN_BATCH = 8  # a leftover batch smaller than this gives meaningless negatives and is skipped


@dataclass(frozen=True)
class Pair:
    question: str
    chunk_id: str
    positive_text: str


def load_pairs(path: Path) -> list[Pair]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    return [Pair(r["question"], r["chunk_id"], r["positive_text"]) for r in rows]


def split_by_chunk(pairs: list[Pair], val_fraction: float, seed: int,
                   ) -> tuple[list[Pair], list[Pair]]:
    """Hold out whole chunks (~val_fraction of them) so validation measures how well the model
    handles passages it has never seen, not whether it remembers a chunk's other questions."""
    chunk_ids = sorted({p.chunk_id for p in pairs})
    order = np.random.default_rng(seed).permutation(len(chunk_ids))
    n_val = max(1, round(len(chunk_ids) * val_fraction))
    val_ids = {chunk_ids[i] for i in order[:n_val]}
    return ([p for p in pairs if p.chunk_id not in val_ids],
            [p for p in pairs if p.chunk_id in val_ids])


def make_batches(pairs: list[Pair], batch_size: int, rng: np.random.Generator) -> list[list[int]]:
    """Batches of pair indexes in which no chunk appears twice (no false negatives).

    Shuffle, then fill batches greedily; a pair whose chunk is already in the current batch is
    deferred to a later one. Batches smaller than MIN_BATCH are dropped; the shuffle is
    different every epoch, so no pair is systematically skipped.
    """
    pending = [int(i) for i in rng.permutation(len(pairs))]
    batches = []
    while pending:
        batch, seen, deferred = [], set(), []
        for index in pending:
            chunk_id = pairs[index].chunk_id
            if len(batch) < batch_size and chunk_id not in seen:
                batch.append(index)
                seen.add(chunk_id)
            else:
                deferred.append(index)
        batches.append(batch)
        pending = deferred
    full = [b for b in batches if len(b) >= MIN_BATCH]
    order = rng.permutation(len(full))
    return [full[i] for i in order]


def batch_loss(model: SentenceTransformer, loss_fn: MultipleNegativesRankingLoss,
               batch: list[Pair], query_prefix: str, passage_prefix: str) -> torch.Tensor:
    queries = model.tokenize([query_prefix + p.question for p in batch])
    passages = model.tokenize([passage_prefix + p.positive_text for p in batch])
    return loss_fn([queries, passages], None)


@torch.no_grad()
def validation_loss(model: SentenceTransformer, loss_fn: MultipleNegativesRankingLoss,
                    pairs: list[Pair], batch_size: int, seed: int, prefixes: tuple[str, str],
                    ) -> float:
    """Mean loss over fixed, repeatable batches of held-out pairs."""
    model.eval()
    batches = make_batches(pairs, batch_size, np.random.default_rng(seed))
    if not batches:
        return float("nan")
    total = sum(float(batch_loss(model, loss_fn, [pairs[i] for i in b], *prefixes)) * len(b)
                for b in batches)
    return total / sum(len(b) for b in batches)


@dataclass
class TrainResult:
    best_val_loss: float
    best_step: int
    start_val_loss: float
    steps: int
    log: list[dict]


def train(model: SentenceTransformer, train_pairs: list[Pair], val_pairs: list[Pair], *,
          prefixes: tuple[str, str], epochs: int = EPOCHS, batch_size: int = BATCH_SIZE,
          lr: float = LEARNING_RATE, warmup_ratio: float = WARMUP_RATIO, seed: int = SEED,
          ) -> TrainResult:
    """Train, validate during training, and leave the model on its best checkpoint."""
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    loss_fn = MultipleNegativesRankingLoss(model, scale=SCALE)
    plan = [make_batches(train_pairs, batch_size, rng) for _ in range(epochs)]
    total_steps = sum(len(p) for p in plan)
    if total_steps == 0:
        raise ValueError("no full batch can be made from the training pairs")
    eval_every = max(1, min(len(p) for p in plan) // EVALS_PER_EPOCH)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=WEIGHT_DECAY)
    scheduler = get_linear_schedule_with_warmup(optimizer, math.ceil(total_steps * warmup_ratio),
                                                total_steps)

    def evaluate() -> float:
        return validation_loss(model, loss_fn, val_pairs, batch_size, seed, prefixes)

    start_loss = evaluate()
    if math.isnan(start_loss):  # nan < x is always False: training would silently keep the base
        raise ValueError(f"the validation set is too small: it cannot form one batch of "
                         f"{MIN_BATCH} pairs from {MIN_BATCH} different chunks")
    best = {"loss": start_loss, "step": 0,
            "state": {k: v.detach().clone() for k, v in model.state_dict().items()}}
    log: list[dict] = [{"step": 0, "epoch": 0.0, "val_loss": round(start_loss, 5)}]
    started, step, running = time.perf_counter(), 0, []
    for epoch, batches in enumerate(plan, start=1):
        for position, indexes in enumerate(batches, start=1):
            model.train()
            loss = batch_loss(model, loss_fn, [train_pairs[i] for i in indexes], *prefixes)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), MAX_GRAD_NORM)
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad()
            step += 1
            value = loss.item()
            running.append(value)
            entry = {"step": step, "epoch": round(epoch - 1 + position / len(batches), 2),
                     "train_loss": round(value, 5), "lr": scheduler.get_last_lr()[0]}
            if step % eval_every == 0 or step == total_steps:
                entry["val_loss"] = round(evaluate(), 5)
                entry["train_loss_avg"] = round(sum(running) / len(running), 5)
                running = []
                if entry["val_loss"] < best["loss"]:
                    best = {"loss": entry["val_loss"], "step": step,
                            "state": {k: v.detach().clone() for k, v in model.state_dict().items()}}
                print(f"  step {step}/{total_steps}  epoch {entry['epoch']}  "
                      f"train {entry['train_loss_avg']:.4f}  val {entry['val_loss']:.4f}  "
                      f"({(time.perf_counter() - started) / 60:.1f} min)", flush=True)
            log.append(entry)
    model.load_state_dict(best["state"])
    model.eval()
    return TrainResult(best["loss"], best["step"], start_loss, total_steps, log)


# ── command line ─────────────────────────────────────────────────────────────────────────

def output_dir(settings: Settings, base_model: str) -> Path:
    return settings.model_dir / f"pharma-{Path(base_model).name}-v1"


def main() -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pairs", default=str(settings.data_dir / "train_pairs.jsonl"))
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE,
                        help="§10.3: 32, or 16 if memory requires")
    parser.add_argument("--epochs", type=int, default=EPOCHS)
    parser.add_argument("--out", default=None, help="default: models/pharma-<base>-v1")
    args = parser.parse_args()

    base = settings.embedding_model
    pairs_path = Path(args.pairs)
    pairs = load_pairs(pairs_path)
    train_pairs, val_pairs = split_by_chunk(pairs, VAL_FRACTION, SEED)
    print(f"{len(pairs)} pairs → {len(train_pairs)} train / {len(val_pairs)} validation "
          f"(whole chunks held out); base model {base}", flush=True)

    torch.manual_seed(SEED)
    model = SentenceTransformer(base, device="cpu")
    prefixes = prefixes_for(base)
    result = train(model, train_pairs, val_pairs, prefixes=prefixes, epochs=args.epochs,
                   batch_size=args.batch_size)

    out = Path(args.out) if args.out else output_dir(settings, base)
    out.mkdir(parents=True, exist_ok=True)
    model.save(str(out))  # safetensors + tokenizer + config; no pickle, no optimizer state
    config = {
        "base_model": base, "loss": "MultipleNegativesRankingLoss", "scale": SCALE,
        "batch_size": args.batch_size, "epochs": args.epochs, "learning_rate": LEARNING_RATE,
        "warmup_ratio": WARMUP_RATIO, "weight_decay": WEIGHT_DECAY, "val_fraction": VAL_FRACTION,
        "seed": SEED, "query_prefix": prefixes[0], "passage_prefix": prefixes[1],
        "train_pairs": len(train_pairs), "val_pairs": len(val_pairs),
        "total_steps": result.steps, "start_val_loss": round(result.start_val_loss, 5),
        "best_val_loss": round(result.best_val_loss, 5), "best_step": result.best_step,
        "kept_base_weights": result.best_step == 0,
        "pairs_sha256": sha256_of(pairs_path),
        "chunks_sha256": sha256_of(settings.data_dir / "chunks.parquet"),
        "git_commit": git_commit(), "date": dt.date.today().isoformat(), "device": "cpu",
        "torch": torch.__version__, "transformers": transformers.__version__,
        "sentence_transformers": sentence_transformers.__version__,
    }
    (out / "training_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    (out / "training_log.json").write_text(json.dumps(result.log, indent=2), encoding="utf-8")
    verdict = ("validation loss never improved: the base weights were kept"
               if result.best_step == 0 else f"best checkpoint at step {result.best_step}")
    print(f"\nval loss {result.start_val_loss:.4f} → {result.best_val_loss:.4f} ({verdict})\n"
          f"saved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
