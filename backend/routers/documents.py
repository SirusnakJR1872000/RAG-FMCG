"""The document registry (PROJECT_SPEC §16 GET /documents; FR-11 "what is in the index").

Read-only in Tier 1. Uploading and withdrawing are Tier 2 (§16).
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select

from auth.dependencies import AuthContext, require
from database.models import documents
from deps import get_db
from src.ingestion.manifest import is_fictional_code

router = APIRouter(prefix="/api/documents", tags=["documents"])
CAN_READ = Depends(require("docs:read"))


@router.get("")
def list_documents(request: Request,
                   status: Literal["active", "superseded", "withdrawn"] | None = Query(None),
                   _: AuthContext = CAN_READ):
    query = select(documents).order_by(documents.c.doc_code, documents.c.ingested_at.desc())
    if status:
        query = query.where(documents.c.status == status)
    with get_db(request).read() as conn:
        rows = [dict(r) for r in conn.execute(query).mappings()]
        # the replacing version may be outside the filter (e.g. status=superseded)
        codes = dict(conn.execute(select(documents.c.id, documents.c.version)).all())
    items = [{"id": r["id"], "doc_code": r["doc_code"], "title": r["title"],
              "version": r["version"], "effective_date": r["effective_date"],
              "publisher": r["publisher"], "status": r["status"],
              "status_reason": r["status_reason"], "chunk_count": r["chunk_count"],
              "page_count": r["page_count"], "sha256": r["sha256"],
              "ingested_at": r["ingested_at"], "is_fictional": is_fictional_code(r["doc_code"]),
              "superseded_by_version": codes.get(r["superseded_by"])} for r in rows]
    return {"items": items, "total": len(items)}
