"""Corpus manifest: the single source of document metadata (PROJECT_SPEC §6.2, §6.4).

Ingestion refuses any file that is not listed here. The YAML is read with `yaml.safe_load`
only, so a manifest can never execute code.
"""

import datetime as dt
import hashlib
from collections import Counter
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError, field_validator


class ManifestError(ValueError):
    """The manifest is missing, malformed, or breaks a lifecycle rule."""


FICTIONAL_PREFIX = "ACME-"  # every internal SOP of the fictional company (§1.4)


def is_fictional_code(doc_code: str) -> bool:
    return doc_code.startswith(FICTIONAL_PREFIX)


class ManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_code: str = Field(pattern=r"^[A-Z0-9][A-Z0-9-]*[A-Z0-9]$")
    title: str = Field(min_length=1)
    version: str = Field(min_length=1)
    effective_date: dt.date
    file: str = Field(min_length=1)
    publisher: str = Field(min_length=1)
    source_url: HttpUrl | None = None
    status: Literal["active", "superseded", "withdrawn"]
    superseded_by: str | None = None
    withdrawn_reason: str | None = None

    @field_validator("file")
    @classmethod
    def _relative_inside_corpus(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("file must be a relative path inside corpus/")
        if path.suffix.lower() not in {".pdf", ".md"}:
            raise ValueError("file must be a .pdf or .md")
        return value

    @property
    def is_public(self) -> bool:
        return self.file.startswith("public/")

    @property
    def is_fictional(self) -> bool:
        return is_fictional_code(self.doc_code)


def load_manifest(path: Path) -> list[ManifestEntry]:
    """Read and validate the manifest. Raises ManifestError with a readable message."""
    if not path.is_file():
        raise ManifestError(f"manifest not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise ManifestError("manifest must be a YAML list of documents")

    entries: list[ManifestEntry] = []
    for i, item in enumerate(raw):
        try:
            entries.append(ManifestEntry.model_validate(item))
        except ValidationError as exc:
            code = item.get("doc_code", "?") if isinstance(item, dict) else "?"
            raise ManifestError(f"entry {i} ({code}) is invalid:\n{exc}") from exc

    _check_rules(entries)
    return entries


def _check_rules(entries: list[ManifestEntry]) -> None:
    keys = Counter((e.doc_code, e.version) for e in entries)
    dupes = [f"{c} v{v}" for (c, v), n in keys.items() if n > 1]
    if dupes:
        raise ManifestError(f"duplicate doc_code + version: {', '.join(dupes)}")

    active = Counter(e.doc_code for e in entries if e.status == "active")
    multi = [c for c, n in active.items() if n > 1]
    if multi:
        raise ManifestError(f"more than one active version: {', '.join(multi)}")

    files = Counter(e.file for e in entries)
    shared = [f for f, n in files.items() if n > 1]
    if shared:
        raise ManifestError(f"same file listed twice: {', '.join(shared)}")

    for e in entries:
        if e.is_public and e.source_url is None:
            raise ManifestError(f"{e.doc_code}: public documents need a source_url")
        if e.status == "withdrawn" and not e.withdrawn_reason:
            raise ManifestError(f"{e.doc_code}: withdrawn documents need a withdrawn_reason")
        if e.status == "superseded" and not e.superseded_by:
            raise ManifestError(f"{e.doc_code}: superseded documents need superseded_by")


def sha256_of(path: Path) -> str:
    """SHA-256 of a file, read in blocks (used for document fingerprints, §6.2)."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()
