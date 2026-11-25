"""The document registry: which versions of which documents are in the index (§6.2, §12).

`sync_registry` copies the manifest into the `documents` table, using chunks.parquet for the
fingerprints and chunk counts. It records one DOCUMENT_* event for every change and nothing
for a re-run that changes nothing. A file whose hash differs from the registered hash for the
same doc_code + version is refused: a changed file needs a new version (§6.2).
"""

from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import Connection, insert, select, update

from audit.writer import Actor, log
from database.init_db import new_id, utc_now
from database.models import documents
from src.ingestion.manifest import ManifestEntry


class RegistryConflict(ValueError):
    """A registered document's content changed without a new version."""


@dataclass
class SyncResult:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # in the manifest, but no chunks (no file)

    def as_dict(self) -> dict:
        return {"added": self.added, "updated": self.updated, "skipped": self.skipped}


def _label(entry: ManifestEntry) -> str:
    return f"{entry.doc_code} {entry.version}"


def _fingerprints(chunks: pd.DataFrame) -> dict[tuple[str, str], tuple[str, int, int | None]]:
    """(doc_code, version) → (sha256, chunk count, page count)."""
    out = {}
    for (code, version), group in chunks.groupby(["doc_code", "version"]):
        pages = group["page_end"].dropna()
        out[(code, version)] = (group["doc_sha256"].iloc[0], len(group),
                                int(pages.max()) if len(pages) else None)
    return out


def sync_registry(conn: Connection, entries: list[ManifestEntry], chunks: pd.DataFrame,
                  actor: Actor) -> SyncResult:
    """Make the `documents` table match the manifest. Runs inside db.write()."""
    result = SyncResult()
    prints = _fingerprints(chunks)
    existing = {(r.doc_code, r.version): r for r in conn.execute(select(documents))}

    # superseded rows first: the unique index allows one ACTIVE version per code at a time
    for entry in sorted(entries, key=lambda e: e.status == "active"):
        key = (entry.doc_code, entry.version)
        if key not in prints:
            result.skipped.append(_label(entry))
            continue
        sha256, count, pages = prints[key]
        row = existing.get(key)
        if row is None:
            conn.execute(insert(documents).values(
                id=new_id("d"), doc_code=entry.doc_code, title=entry.title,
                version=entry.version, effective_date=entry.effective_date.isoformat(),
                publisher=entry.publisher, file_path=entry.file, sha256=sha256,
                page_count=pages, chunk_count=count, status=entry.status,
                status_reason=entry.withdrawn_reason, ingested_at=utc_now(),
                ingested_by=actor.user_id))
            log(conn, "DOCUMENT_INGESTED", actor, {
                "doc_code": entry.doc_code, "version": entry.version, "sha256": sha256,
                "chunk_count": count})
            result.added.append(_label(entry))
            continue
        if row.sha256 != sha256:
            raise RegistryConflict(
                f"{_label(entry)}: the file changed but the version did not. "
                "A changed document needs a new version in the manifest (§6.2).")
        if row.status != entry.status:
            conn.execute(update(documents).where(documents.c.id == row.id).values(
                status=entry.status, status_reason=entry.withdrawn_reason))
            event = {"superseded": "DOCUMENT_SUPERSEDED",
                     "withdrawn": "DOCUMENT_WITHDRAWN"}.get(entry.status)
            if event:
                log(conn, event, actor, {
                    "doc_code": entry.doc_code, "version": entry.version, "sha256": sha256,
                    "chunk_count": count, "reason": entry.withdrawn_reason})
            result.updated.append(_label(entry))

    _link_superseded(conn, entries)
    return result


def _link_superseded(conn: Connection, entries: list[ManifestEntry]) -> None:
    """superseded_by points at the registry row of the replacing version (when registered)."""
    for entry in entries:
        if entry.status != "superseded" or not entry.superseded_by:
            continue
        replacement = conn.execute(select(documents.c.id).where(
            documents.c.doc_code == entry.doc_code,
            documents.c.status == "active")).scalar()
        if replacement:
            conn.execute(update(documents).where(
                documents.c.doc_code == entry.doc_code,
                documents.c.version == entry.version).values(superseded_by=replacement))
