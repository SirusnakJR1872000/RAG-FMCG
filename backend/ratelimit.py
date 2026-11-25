"""Rate limits (PROJECT_SPEC §5.3, SEC-10): 5 logins/min per IP, 10 questions/min per user.

slowapi decorators need their limit at import time, but the limits come from settings, so the
decorators call these functions when a request arrives. Buckets are in memory (one worker).
"""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

_limits = {"login": "5/minute", "query": "10/minute"}


def configure(login: str, query: str) -> None:
    _limits.update(login=login, query=query)
    limiter.reset()  # a new app starts with empty buckets


def login_limit() -> str:
    return _limits["login"]


def query_limit() -> str:
    return _limits["query"]


def user_key(request: Request) -> str:
    """Per user (set by the auth dependency), falling back to the address."""
    return getattr(request.state, "user_id", None) or get_remote_address(request)


limiter = Limiter(key_func=get_remote_address)
