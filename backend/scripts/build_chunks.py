"""Build data/chunks.parquet from every active document in the manifest (PROJECT_SPEC §7).

Usage (from backend/):  python -m scripts.build_chunks

Only files listed in corpus/manifest.yaml are ingested; any other file found under corpus/
is reported and refused. Chunk length is measured with the tokenizer of EMBEDDING_MODEL.
"""

import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

from config import Settings, get_settings
from src.ingestion.chunker import Chunker, DocInfo, TokenCounter
from src.ingestion.manifest import ManifestEntry, load_manifest, sha256_of
from src.ingestion.md_loader import load_markdown
from src.ingestion.pdf_loader import load_pdf
from src.ingestion.sections import detect_sections

CORPUS_SUBDIRS = ("public", "sops")


def unlisted_files(corpus_dir: Path, entries: list[ManifestEntry]) -> list[Path]:
    listed = {(corpus_dir / e.file).resolve() for e in entries}
    found = [p for d in CORPUS_SUBDIRS for p in (corpus_dir / d).glob("*") if p.is_file()]
    return sorted(p for p in found if p.suffix in {".pdf", ".md"} and p.resolve() not in listed)


def version_indexes(entries: list[ManifestEntry]) -> dict[tuple[str, str], int]:
    """1-based version number per doc_code, ordered by effective date (stable chunk ids)."""
    by_code: dict[str, list[ManifestEntry]] = defaultdict(list)
    for e in entries:
        by_code[e.doc_code].append(e)
    return {
        (e.doc_code, e.version): i
        for versions in by_code.values()
        for i, e in enumerate(sorted(versions, key=lambda x: x.effective_date), start=1)
    }


def build_chunk_table(settings: Settings, verbose: bool = False) -> pd.DataFrame:
    """Load, section and chunk every active manifest document. Returns the §7.4 table."""
    entries = load_manifest(settings.manifest_path)
    counter = TokenCounter(settings.embedding_model)
    chunker = Chunker(counter.count, counter.special, settings.chunk_max_tokens,
                      settings.chunk_overlap_tokens)
    versions = version_indexes(entries)
    records: list[dict] = []
    for e in (x for x in entries if x.status == "active"):  # §6.4: only active is searchable
        path = settings.corpus_dir / e.file
        markdown = path.suffix == ".md"
        loaded = load_markdown(path) if markdown else load_pdf(path)
        info = DocInfo(e.doc_code, e.title, e.version, versions[(e.doc_code, e.version)],
                       sha256_of(path), markdown)
        chunks = chunker.chunk(detect_sections(loaded, markdown), info)
        records += chunks
        if verbose:
            tokens = [c["n_tokens"] for c in chunks]
            print(f"  {e.doc_code:16} {len(chunks):4} chunks  tokens min/avg/max "
                  f"{min(tokens):3}/{sum(tokens) // len(tokens):3}/{max(tokens):3}")
    df = pd.DataFrame.from_records(records).astype({"page_start": "Int64", "page_end": "Int64"})
    if df["chunk_id"].duplicated().any():
        raise RuntimeError("duplicate chunk_id values — chunk ids must be unique")
    return df


def main() -> int:
    settings = get_settings()
    entries = load_manifest(settings.manifest_path)
    for path in unlisted_files(settings.corpus_dir, entries):
        print(f"  REFUSED     {path.relative_to(settings.corpus_dir)} (not in manifest)")
    missing = [e for e in entries if not (settings.corpus_dir / e.file).is_file()]
    if missing:
        for e in missing:
            print(f"  MISSING     {e.doc_code}: {e.file}")
        print("Run `python -m scripts.download_docs` first.")
        return 1

    df = build_chunk_table(settings, verbose=True)
    out = settings.data_dir / "chunks.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    print(f"\n{len(df)} chunks from {df['doc_code'].nunique()} documents → {out}")
    print(f"max n_tokens = {df['n_tokens'].max()} (limit {settings.chunk_max_tokens})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
