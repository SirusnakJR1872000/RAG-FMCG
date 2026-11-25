"""Fine-tuning loop on a tiny random model (PROJECT_SPEC §10.3). No download, runs in seconds."""

import numpy as np
import pytest
import torch
from sentence_transformers import SentenceTransformer
from sentence_transformers.sentence_transformer.losses import MultipleNegativesRankingLoss
from transformers import BertConfig, BertModel, BertTokenizerFast

from src.finetuning.train_embeddings import (
    MIN_BATCH,
    Pair,
    make_batches,
    split_by_chunk,
    train,
    validation_loss,
)

WORDS = [f"w{i}" for i in range(60)]


def tiny_model(tmp_path, seed=0, name="tiny"):
    """A 1-layer BERT with a 65-word vocabulary, wrapped as a SentenceTransformer."""
    vocab = tmp_path / "vocab.txt"
    vocab.write_text("\n".join(["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]", *WORDS]))
    torch.manual_seed(seed)
    model_dir = tmp_path / name
    config = BertConfig(vocab_size=65, hidden_size=32, num_hidden_layers=1, num_attention_heads=2,
                        intermediate_size=64, max_position_embeddings=64)
    BertModel(config).save_pretrained(model_dir)
    BertTokenizerFast(vocab_file=str(vocab)).save_pretrained(model_dir)
    return SentenceTransformer(str(model_dir), device="cpu")


def make_pairs(n_chunks=24, per_chunk=2, seed=1):
    """Each chunk is a few words; its questions reuse some of them, so the task is learnable."""
    rng = np.random.default_rng(seed)
    pairs = []
    for c in range(n_chunks):
        words = [str(w) for w in rng.choice(WORDS, size=8, replace=False)]
        for _ in range(per_chunk):
            q = " ".join(str(w) for w in rng.choice(words, size=4, replace=False))
            pairs.append(Pair(q, f"chunk{c}", " ".join(words)))
    return pairs


# ── splitting and batching ───────────────────────────────────────────────────────────────

def test_validation_split_holds_out_whole_chunks_and_is_repeatable():
    pairs = make_pairs(n_chunks=40, per_chunk=3)
    train_pairs, val_pairs = split_by_chunk(pairs, 0.1, seed=42)
    assert {p.chunk_id for p in train_pairs}.isdisjoint({p.chunk_id for p in val_pairs})
    assert len({p.chunk_id for p in val_pairs}) == 4  # 10 % of 40 chunks
    assert len(train_pairs) + len(val_pairs) == len(pairs)
    assert split_by_chunk(pairs, 0.1, seed=42) == (train_pairs, val_pairs)
    assert split_by_chunk(pairs, 0.1, seed=7)[1] != val_pairs


def test_no_chunk_appears_twice_in_a_batch_and_every_pair_is_used_at_most_once():
    pairs = make_pairs(n_chunks=50, per_chunk=3)
    batches = make_batches(pairs, 32, np.random.default_rng(0))
    used = [i for b in batches for i in b]
    assert len(used) == len(set(used))
    for batch in batches:
        chunks = [pairs[i].chunk_id for i in batch]
        assert len(chunks) == len(set(chunks)) and MIN_BATCH <= len(batch) <= 32
    assert len(used) >= len(pairs) - MIN_BATCH  # at most one small leftover batch dropped


def test_batches_differ_between_epochs_but_not_between_runs():
    pairs = make_pairs(n_chunks=50, per_chunk=3)
    rng = np.random.default_rng(5)
    first, second = make_batches(pairs, 32, rng), make_batches(pairs, 32, rng)
    assert first != second
    assert make_batches(pairs, 32, np.random.default_rng(5)) == first


def test_a_pair_set_that_cannot_fill_a_batch_is_refused(tmp_path):
    same_chunk = [Pair(f"q{i}", "chunk0", "text") for i in range(30)]  # all share one chunk
    with pytest.raises(ValueError, match="no full batch"):
        train(tiny_model(tmp_path), same_chunk, same_chunk, prefixes=("", ""))


# ── the loop ─────────────────────────────────────────────────────────────────────────────

def test_training_lowers_the_training_loss_and_restores_the_best_checkpoint(tmp_path):
    pairs = make_pairs(n_chunks=100, per_chunk=3)
    train_pairs, val_pairs = split_by_chunk(pairs, 0.1, seed=42)
    model = tiny_model(tmp_path)
    result = train(model, train_pairs, val_pairs, prefixes=("", ""), epochs=3, batch_size=16,
                   lr=3e-3)
    losses = [e["train_loss"] for e in result.log if "train_loss" in e]
    assert np.mean(losses[-4:]) < np.mean(losses[:4])
    assert result.log[0] == {"step": 0, "epoch": 0.0, "val_loss": round(result.start_val_loss, 5)}
    assert result.best_val_loss <= result.start_val_loss
    # the model that is left behind really is the best checkpoint, not the last step
    loss_fn = MultipleNegativesRankingLoss(model, scale=20.0)
    again = validation_loss(model, loss_fn, val_pairs, 16, 42, ("", ""))
    assert again == pytest.approx(result.best_val_loss, abs=1e-4)


def test_training_is_repeatable_with_the_same_seed(tmp_path):
    pairs = make_pairs(n_chunks=100, per_chunk=3)
    train_pairs, val_pairs = split_by_chunk(pairs, 0.1, seed=42)
    runs = []
    for i in range(2):  # the same random weights both times (seed 0), the same training seed
        model = tiny_model(tmp_path, seed=0, name=f"run{i}")
        runs.append(train(model, train_pairs, val_pairs, prefixes=("", ""), epochs=2,
                          batch_size=16, lr=1e-3).log)
    assert runs[0] == runs[1]


def test_the_model_saves_as_safetensors_without_pickle_files(tmp_path):
    model = tiny_model(tmp_path)
    out = tmp_path / "saved"
    model.save(str(out))
    suffixes = {p.suffix for p in out.rglob("*") if p.is_file()}
    assert ".safetensors" in suffixes
    assert not suffixes & {".pt", ".pth", ".bin", ".pkl", ".pickle", ".joblib"}
    assert SentenceTransformer(str(out), device="cpu") is not None


def test_a_validation_set_too_small_for_one_batch_fails_loudly(tmp_path):
    pairs = make_pairs(n_chunks=60, per_chunk=3)  # 10 % = 6 chunks: fewer than MIN_BATCH
    train_pairs, val_pairs = split_by_chunk(pairs, 0.1, seed=42)
    with pytest.raises(ValueError, match="validation set is too small"):
        train(tiny_model(tmp_path), train_pairs, val_pairs, prefixes=("", ""), batch_size=16)
