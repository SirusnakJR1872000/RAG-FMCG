"""Health (PROJECT_SPEC §16, §20; design brief §4.2 status pill).

/health is public and reveals only a status word. /health/details (admin) has the models,
index build, documents, audit-verification result and free disk space. Neither ever shows a
secret (§15.3).
"""

import shutil
import time

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from auth.dependencies import AuthContext, require
from database.models import documents
from deps import get_db, get_index, get_settings_from
from schemas import HealthResponse
from services.llm_client import health_client
from version import APP_VERSION, git_commit

router = APIRouter(prefix="/api/health", tags=["health"])
LLM_CHECK_SECONDS = 10  # /health is polled by every open browser: cache the Ollama ping
ADMIN_ONLY = Depends(require("health:details"))


async def llm_state(request: Request) -> dict:
    cache = request.app.state.llm_health
    if time.monotonic() - cache.get("at", -1e9) > LLM_CHECK_SECONDS:
        client = health_client(request)
        reachable = await client.ping()
        loaded = [m.get("name") for m in await client.loaded_models()] if reachable else []
        cache.update(at=time.monotonic(), reachable=reachable, loaded=loaded)
    return cache


def audit_ok(request: Request) -> bool:
    return bool(request.app.state.audit.get("ok"))


@router.get("", response_model=HealthResponse)
async def health(request: Request):
    if not get_index(request).ready:
        return HealthResponse(status="not_ready")
    state = await llm_state(request)
    return HealthResponse(status="ready" if state["reachable"] and audit_ok(request)
                          else "degraded")


@router.get("/details")
async def health_details(request: Request, _: AuthContext = ADMIN_ONLY):
    settings = get_settings_from(request)
    state = await llm_state(request)
    with get_db(request).read() as conn:
        active = [dict(r) for r in conn.execute(select(documents.c.doc_code, documents.c.version)
                  .where(documents.c.status == "active").order_by(documents.c.doc_code)).mappings()]
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return {
        "llm": {"reachable": state["reachable"], "model": settings.llm_model,
                "loaded": settings.llm_model in state["loaded"]},
        "index": get_index(request).describe(),
        "documents": {"active_count": len(active), "active_versions": active},
        "audit": request.app.state.audit,
        "disk": {"free_gb": round(shutil.disk_usage(settings.data_dir).free / 2**30, 1)},
        "version": {"app": APP_VERSION, "git_commit": git_commit()},
    }
