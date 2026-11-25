"""Access to the shared objects created at start-up (database, settings, queue, index)."""

from fastapi import Request

from audit.writer import Actor
from auth.service import RequestInfo
from config import Settings
from database.session import Database
from services.index_manager import IndexManager
from services.llm_queue import LLMQueue


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_settings_from(request: Request) -> Settings:
    return request.app.state.settings


def get_queue(request: Request) -> LLMQueue:
    return request.app.state.queue


def get_index(request: Request) -> IndexManager:
    return request.app.state.index


def request_info(request: Request) -> RequestInfo:
    client = request.client.host if request.client else None
    return RequestInfo(client, getattr(request.state, "request_id", None))


def anonymous_actor(request: Request, username: str = "anonymous") -> Actor:
    info = request_info(request)
    return Actor(None, username, None, info.client_ip, info.request_id)
