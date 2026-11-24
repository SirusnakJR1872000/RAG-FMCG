"""Where the dense index of each embedding model lives, and whether it is usable (§8.1).

indexes/<model-slug>/{index.faiss, chunk_ids.json, build_info.json}
"""

import json
from pathlib import Path

from config import Settings
from src.ingestion.manifest import sha256_of


class IndexNotReady(Exception):
    """No index, or one built from different chunks (§15.6: query returns 503 INDEX_NOT_READY)."""

    code = "INDEX_NOT_READY"


def model_slug(model_name: str) -> str:
    return model_name.strip("/").replace("/", "__")


def index_dir(settings: Settings, model_name: str) -> Path:
    return settings.index_dir / model_slug(model_name)


def chunks_path(settings: Settings) -> Path:
    return settings.data_dir / "chunks.parquet"


def load_build_info(settings: Settings, model_name: str) -> dict:
    """build_info.json of the index, checked against the current chunks.parquet."""
    chunks = chunks_path(settings)
    if not chunks.is_file():
        raise IndexNotReady(f"{chunks} is missing. Run: python -m scripts.build_chunks")
    info_path = index_dir(settings, model_name) / "build_info.json"
    if not info_path.is_file():
        raise IndexNotReady(
            f"No index for {model_name}. Run: python -m scripts.build_index --model {model_name}")
    info = json.loads(info_path.read_text(encoding="utf-8"))
    if info["chunks_sha256"] != sha256_of(chunks):
        raise IndexNotReady(
            "The index was built from different chunks than data/chunks.parquet. "
            f"Rebuild it: python -m scripts.build_index --model {model_name}")
    return info
