"""Who is calling, and may they? Enforced on every request (PROJECT_SPEC §13; SEC-01, SEC-02).

`current_user`   : a valid, unexpired access token of an active user who has no pending
                   password change (first login / expired password block everything except
                   /me and change-password).
`require(perm)`  : also checks the permission; a refusal is audited as ACCESS_DENIED (AUD-05).
The role is read from the database on every call, not from the token, so deactivating a user
or changing a role takes effect at once rather than when the 15-minute token runs out.
"""

from dataclasses import dataclass

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from audit.writer import Actor, log
from auth import service, tokens
from auth.permissions import has_permission, permissions_for
from deps import get_db, get_settings_from, request_info
from errors import ApiError

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    user: dict
    actor: Actor
    must_change_password: bool

    @property
    def permissions(self) -> list[str]:
        return permissions_for(self.user["role"])


def _authenticate(request: Request, credentials: HTTPAuthorizationCredentials | None,
                  allow_pending_change: bool) -> AuthContext:
    if credentials is None:
        raise ApiError(401, "NOT_AUTHENTICATED", "Sign in to continue.")
    settings = get_settings_from(request)
    try:
        claims = tokens.decode_access_token(credentials.credentials, settings.jwt_secret_key)
    except tokens.TokenError as exc:
        raise ApiError(401, exc.code, str(exc)) from exc
    with get_db(request).read() as conn:
        user = service.get_user(conn, claims["sub"])
    if user is None or not user["is_active"] or not user["can_login"]:
        raise ApiError(401, "INVALID_TOKEN", "The access token is not valid.")
    pending = service.must_change_password(user, settings, service.now_utc())
    if pending and not allow_pending_change:
        raise ApiError(403, "PASSWORD_CHANGE_REQUIRED", "Change your password to continue.")
    info = request_info(request)
    request.state.user_id = user["id"]  # the per-user rate limit reads this
    return AuthContext(user, service.actor_for(user, info), pending)


def current_user(request: Request,
                 credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
                 ) -> AuthContext:
    return _authenticate(request, credentials, allow_pending_change=False)


def current_user_even_if_password_change_pending(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> AuthContext:
    return _authenticate(request, credentials, allow_pending_change=True)


def deny(request: Request, ctx: AuthContext, needed: str) -> ApiError:
    with get_db(request).write() as conn:
        log(conn, "ACCESS_DENIED", ctx.actor, {
            "endpoint": f"{request.method} {request.url.path}", "permission": needed})
    return ApiError(403, "FORBIDDEN", "Your role is not allowed to do this.")


def require(permission: str):
    """A FastAPI dependency: the caller must hold `permission`."""

    def dependency(request: Request, ctx: AuthContext = Depends(current_user)) -> AuthContext:
        if not has_permission(ctx.user["role"], permission):
            raise deny(request, ctx, permission)
        return ctx

    return dependency


def require_any(*permissions: str):
    """A FastAPI dependency: the caller must hold at least one of the permissions."""

    def dependency(request: Request, ctx: AuthContext = Depends(current_user)) -> AuthContext:
        if not any(has_permission(ctx.user["role"], p) for p in permissions):
            raise deny(request, ctx, " or ".join(permissions))
        return ctx

    return dependency
