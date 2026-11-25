"""The FastAPI application (PROJECT_SPEC §4, §15, §16, §19).

`create_app()` builds it; `api.app` (built on first access) is what uvicorn runs:
    uvicorn api:app --host 127.0.0.1 --port 8000

Start-up (lifespan): open the database, load the search index and models ONCE, verify the
audit chain, and record SYSTEM_START. Without an index the API still starts: /health says
`not_ready` and questions get 503 INDEX_NOT_READY.
"""

import asyncio
import getpass
import hashlib
import json
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

import ratelimit
from audit.chain import verify
from audit.writer import Actor, log
from config import Settings, get_settings
from database.init_db import SYSTEM_USER_ID, init_db, utc_now
from database.session import Database
from errors import ApiError, error_body, new_request_id
from routers import auth as auth_router
from routers import conversations as conversations_router
from routers import feedback as feedback_router
from routers import health as health_router
from routers import history as history_router
from routers import me as me_router
from routers import query as query_router
from services.index_manager import IndexManager
from services.llm_queue import LLMQueue
from version import APP_VERSION, git_commit

log_ = structlog.get_logger(__name__)
SYSTEM_ACTOR = Actor(SYSTEM_USER_ID, "system", "system")
ROUTERS = [auth_router.router, me_router.router, health_router.router,
           conversations_router.router, query_router.router, feedback_router.router,
           history_router.router]


class RequestIdMiddleware:
    """Give every request an id (req_xxxxxx): in error bodies, the audit trail and the
    X-Request-ID header. A plain ASGI middleware, so streaming responses are not buffered."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = new_request_id()
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_id(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append((b"x-request-id", request_id.encode()))
            await send(message)

        await self.app(scope, receive, send_with_id)


def config_hash(settings: Settings) -> str:
    """Fingerprint of the configuration for SYSTEM_START — never including the secret."""
    public = settings.model_dump(exclude={"jwt_secret_key"}, mode="json")
    return hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest()[:16]


def _install_error_handlers(app: FastAPI) -> None:
    def respond(request: Request, status: int, code: str, message: str, headers=None,
                details=None) -> JSONResponse:
        rid = getattr(request.state, "request_id", new_request_id())
        return JSONResponse(error_body(code, message, rid, details), status_code=status,
                            headers=headers)

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return respond(request, exc.status, exc.code, exc.message, exc.headers, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # never echo the submitted values back: they may be passwords
        details = [{"field": ".".join(str(p) for p in e["loc"] if p != "body"),
                    "message": e["msg"]} for e in exc.errors()]
        return respond(request, 422, "VALIDATION_ERROR", "The request is not valid.",
                       details=details)

    @app.exception_handler(RateLimitExceeded)
    async def rate_limited(request: Request, exc: RateLimitExceeded):
        return respond(request, 429, "RATE_LIMITED", "Too many attempts. Wait a minute and try "
                       "again.", headers={"Retry-After": "60"})

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
        return respond(request, exc.status_code, codes.get(exc.status_code, "HTTP_ERROR"),
                       "Not found." if exc.status_code == 404 else str(exc.detail))

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):  # SEC-12: no stack trace to the client
        rid = getattr(request.state, "request_id", "?")
        log_.error("unhandled_error", request_id=rid, error=type(exc).__name__, exc_info=exc)
        return respond(request, 500, "INTERNAL_ERROR", "Something went wrong on the server.")


async def _load_index(settings: Settings) -> IndexManager:
    from src.generation.pipeline import RagPipeline
    from src.retrieval.indexes import IndexNotReady

    try:
        pipeline = await asyncio.to_thread(RagPipeline, settings)  # loads FAISS, BM25, chunks
        await pipeline.warm_up(llm=False)  # embedding model + reranker into memory
        return IndexManager(pipeline)
    except IndexNotReady as exc:
        log_.error("index_not_ready", error=str(exc))
        return IndexManager(None, str(exc))


def create_app(settings: Settings | None = None, *, pipeline=None,
               db: Database | None = None) -> FastAPI:
    """Build the application. Tests pass a fake `pipeline` and a temporary `db`."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        ratelimit.configure(settings.rate_limit_login, settings.rate_limit_query)
        database = db or Database(settings.sqlite_path)
        init_db(database)
        app.state.settings, app.state.db = settings, database
        app.state.queue = LLMQueue(settings.llm_queue_max)
        app.state.index = IndexManager(pipeline) if pipeline is not None \
            else await _load_index(settings)
        app.state.health_client, app.state.llm_health = None, {}
        with database.write() as conn:  # verify the chain, then record the start (§14.4)
            result = verify(conn)
            log(conn, "SYSTEM_START", SYSTEM_ACTOR, {
                "app_version": APP_VERSION, "git_commit": git_commit(),
                "config_hash": config_hash(settings), "os_user": getpass.getuser(),
                "models": {"llm": settings.llm_model, "embedding": settings.embedding_model,
                           "reranker": settings.reranker_model},
                "index_build_id": app.state.index.build_id, "audit_verify": result.as_dict()})
        app.state.audit = {**result.as_dict(), "verified_at": utc_now()}
        if not result.ok:
            log_.error("audit_chain_broken", first_bad_seq=result.first_bad_seq)
        yield
        if pipeline is None and app.state.index.pipeline is not None:
            await app.state.index.pipeline.aclose()
        database.dispose()

    app = FastAPI(title="Pharma GMP SOP Assistant", version=APP_VERSION, lifespan=lifespan,
                  description="On-premise RAG assistant. Every call needs a bearer token except "
                              "login, refresh and /health.")
    app.state.limiter = ratelimit.limiter
    app.add_middleware(RequestIdMiddleware)
    _install_error_handlers(app)
    for router in ROUTERS:
        app.include_router(router)
    return app


_app: FastAPI | None = None


def __getattr__(name: str):
    """`uvicorn api:app` finds `app` here, built on first access. Importing this module (as the
    tests do) does not read .env or build anything."""
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(name)
