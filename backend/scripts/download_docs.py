"""Download the public guidance PDFs listed in corpus/manifest.yaml (PROJECT_SPEC §6.1).

Usage (from backend/):  python -m scripts.download_docs [--force]

URLs come from each entry's `source_url`; nothing is hardcoded here. Files already present
and valid are skipped. If a publisher blocks automated downloads, the script prints where to
save the file by hand, as START_HERE M1 allows. Public PDFs are gitignored, never committed.
"""

import argparse
import sys
from pathlib import Path

import requests

from config import get_settings
from src.ingestion.manifest import ManifestEntry, load_manifest, sha256_of

USER_AGENT = "pharma-gmp-rag/0.1 (corpus downloader)"
PDF_MAGIC = b"%PDF-"


def is_pdf(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    with path.open("rb") as fh:
        return fh.read(len(PDF_MAGIC)) == PDF_MAGIC


def download(entry: ManifestEntry, dest: Path, timeout: int) -> None:
    """Stream to a .part file, verify it is a PDF, then move it into place."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with requests.get(
            str(entry.source_url), headers={"User-Agent": USER_AGENT},
            stream=True, timeout=timeout,
        ) as resp:
            resp.raise_for_status()
            with tmp.open("wb") as fh:
                for block in resp.iter_content(chunk_size=1 << 16):
                    fh.write(block)
        if not is_pdf(tmp):
            raise ValueError("response is not a PDF (the site may block automated downloads)")
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="re-download files already present")
    parser.add_argument("--timeout", type=int, default=60, help="seconds per request")
    args = parser.parse_args()

    settings = get_settings()
    entries = [e for e in load_manifest(settings.manifest_path) if e.is_public]
    if not entries:
        print("No public documents in the manifest.")
        return 0

    missing: list[tuple[ManifestEntry, Path, str]] = []
    for entry in entries:
        dest = settings.corpus_dir / entry.file
        dest.parent.mkdir(parents=True, exist_ok=True)
        if is_pdf(dest) and not args.force:
            print(f"  present     {entry.doc_code:14} {sha256_of(dest)[:12]}  {entry.file}")
            continue
        try:
            download(entry, dest, args.timeout)
            print(f"  downloaded  {entry.doc_code:14} {sha256_of(dest)[:12]}  {entry.file}")
        except (requests.RequestException, ValueError) as exc:
            print(f"  FAILED      {entry.doc_code:14} {exc}")
            missing.append((entry, dest, str(exc)))

    if missing:
        print("\nDownload these by hand in a browser and save them at the exact path shown:")
        for entry, dest, _ in missing:
            print(f"  {entry.doc_code}\n    from: {entry.source_url}\n    save: {dest}")
        return 1
    print(f"\nAll {len(entries)} public documents present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
