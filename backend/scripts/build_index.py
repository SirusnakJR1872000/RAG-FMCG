"""Build the dense index for one embedding model (PROJECT_SPEC §8.1).

Usage (from backend/):  python -m scripts.build_index --model BAAI/bge-small-en-v1.5

Writes indexes/<model-slug>/{index.faiss, chunk_ids.json, build_info.json}. BM25 is not
stored: it is rebuilt in memory from chunks.parquet whenever it is needed.
"""

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import time
import uuid
from pathlib import Path

import pandas as pd

from config import PROJECT_ROOT, Settings, get_settings
from src.ingestion.manifest import sha256_of
from src.model_paths import resolve_model
from src.retrieval.embeddings import Embedder
from src.retrieval.faiss_store import FaissStore
from src.retrieval.indexes import index_dir


def git_commit() -> str:
    def run(*args: str) -> str:
        return subprocess.run(  # noqa: S603 — fixed git arguments, no user input
            ["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, check=False,  # noqa: S607
        ).stdout.strip()

    commit = run("rev-parse", "--short", "HEAD") or "unknown"
    return f"{commit}-dirty" if run("status", "--porcelain") else commit


def model_hash(embedder: Embedder) -> str:
    """SHA-256 of a local model folder's files (our fine-tuned model), or the Hugging Face
    commit of a downloaded model."""
    local = Path(resolve_model(embedder.model_name))
    if local.is_dir():
        digest = hashlib.sha256()
        for path in sorted(p for p in local.rglob("*") if p.is_file()):
            digest.update(path.relative_to(local).as_posix().encode())
            digest.update(sha256_of(path).encode())
        return f"sha256:{digest.hexdigest()}"
    revision = getattr(embedder.model.model_card_data, "base_model_revision", None)
    return f"hf:{revision}" if revision else "unknown"


def build(settings: Settings, model_name: str) -> dict:
    chunks_path = settings.data_dir / "chunks.parquet"
    chunks = pd.read_parquet(chunks_path)
    embedder = Embedder(model_name)
    start = time.perf_counter()
    vectors = embedder.embed_passages(chunks["embed_text"].tolist(), show_progress=True)
    seconds = time.perf_counter() - start

    out = index_dir(settings, model_name)
    FaissStore.build(vectors, chunks["chunk_id"].tolist()).save(out)
    docs = chunks[["doc_code", "version", "doc_sha256"]].drop_duplicates()
    info = {
        "build_id": str(uuid.uuid4()),
        "created_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "embedding_model": model_name,
        "embedding_model_hash": model_hash(embedder),
        "dimension": embedder.dim,
        "chunk_count": len(chunks),
        "chunks_sha256": sha256_of(chunks_path),
        "embed_seconds": round(seconds, 1),
        "documents": docs.to_dict(orient="records"),
    }
    (out / "build_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    return info


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default=None, help="default: EMBEDDING_MODEL from .env")
    args = parser.parse_args()
    settings = get_settings()
    info = build(settings, args.model or settings.embedding_model)
    print(f"{info['embedding_model']}: {info['chunk_count']} chunks, dim {info['dimension']}, "
          f"{info['embed_seconds']} s → {index_dir(settings, info['embedding_model'])}")


if __name__ == "__main__":
    main()
