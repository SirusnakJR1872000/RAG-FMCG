"""Sign in, refresh, sign out, change password (PROJECT_SPEC §13, §16).

The access token goes to the page's memory (JSON); the refresh token only ever travels in an
HttpOnly, Secure, SameSite=Strict cookie scoped to /api/auth, so page scripts cannot read it.
The cookie endpoints (/refresh, /logout) also check the Origin header against the configured
site (CSRF protection on top of SameSite).
"""

import datetime as dt

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from auth import service, tokens
from auth.dependencies import AuthContext, current_user_even_if_password_change_pending
from config import Settings
from database.session import Database
from deps import get_db, get_settings_from, request_info
from errors import ApiError, error_body
from ratelimit import limiter, login_limit
from schemas import ChangePasswordRequest, LoginRequest, TokenResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])
COOKIE_NAME = "refresh_token"
COOKIE_PATH = "/api/auth"


def _set_cookie(response: Response, session: tokens.Session, now: dt.datetime) -> None:
    max_age = max(0, int((session.expires_at - now).total_seconds()))
    response.set_cookie(COOKIE_NAME, session.token, max_age=max_age, path=COOKIE_PATH,
                        httponly=True, secure=True, samesite="strict")


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path=COOKIE_PATH, httponly=True, secure=True,
                           samesite="strict")


def _token_response(settings: Settings, user: dict, session: tokens.Session, must_change: bool,
                    now: dt.datetime) -> JSONResponse:
    access = tokens.create_access_token(user["id"], user["role"], settings.jwt_secret_key,
                                        settings.access_token_ttl_minutes, now)
    body = TokenResponse(access_token=access, expires_in=settings.access_token_ttl_minutes * 60,
                         must_change_password=must_change)
    response = JSONResponse(body.model_dump(), headers={"Cache-Control": "no-store"})
    _set_cookie(response, session, now)
    return response


def check_origin(request: Request, settings: Settings) -> None:
    """CSRF: a cookie-authenticated request must come from our own site."""
    if request.headers.get("origin") != settings.site_origin:
        raise ApiError(403, "ORIGIN_NOT_ALLOWED", "This request did not come from the application.")


@router.post("/login", response_model=TokenResponse)
@limiter.limit(login_limit)
def login(request: Request, body: LoginRequest, db: Database = Depends(get_db)):
    settings = get_settings_from(request)
    now = service.now_utc()
    with db.write() as conn:
        result = service.login(conn, settings, body.username, body.password,
                               request_info(request), now)
    if result.status == "locked":
        raise ApiError(423, "ACCOUNT_LOCKED",
                       "Account locked after too many attempts. Try again in "
                       f"{settings.lockout_minutes} minutes or contact your administrator.",
                       headers={"Retry-After": str(settings.lockout_minutes * 60)})
    if result.status != "ok":  # unknown user, wrong password and deactivated look identical
        raise ApiError(401, "INVALID_CREDENTIALS", "Username or password is incorrect.")
    return _token_response(settings, result.user, result.session, result.must_change_password, now)


@router.post("/refresh", response_model=TokenResponse)
def refresh(request: Request, db: Database = Depends(get_db)):
    settings = get_settings_from(request)
    check_origin(request, settings)
    token = request.cookies.get(COOKIE_NAME)
    now = service.now_utc()
    result = None
    if token:
        with db.write() as conn:
            result = service.refresh(conn, settings, token, request_info(request), now)
    if result is None or result.status != "ok":
        response = JSONResponse(
            error_body("SESSION_INVALID", "Your session has ended. Sign in again.",
                       request.state.request_id), status_code=401)
        _clear_cookie(response)  # a dead cookie must not be sent again
        return response
    must_change = service.must_change_password(result.user, settings, now)
    return _token_response(settings, result.user, result.session, must_change, now)


@router.post("/logout", status_code=204)
def logout(request: Request, db: Database = Depends(get_db)):
    check_origin(request, get_settings_from(request))
    token = request.cookies.get(COOKIE_NAME)
    if token:
        with db.write() as conn:
            service.logout(conn, token, request_info(request))
    response = Response(status_code=204)
    _clear_cookie(response)
    return response


@router.post("/change-password", response_model=TokenResponse)
def change_password(request: Request, body: ChangePasswordRequest,
                    ctx: AuthContext = Depends(current_user_even_if_password_change_pending),
                    db: Database = Depends(get_db)):
    settings = get_settings_from(request)
    now = service.now_utc()
    with db.write() as conn:
        result = service.change_password(conn, settings, ctx.user, body.current_password,
                                         body.new_password, request_info(request), now)
    if result.status == "locked":
        raise ApiError(423, "ACCOUNT_LOCKED", "Account locked after too many attempts. Try "
                       f"again in {settings.lockout_minutes} minutes.",
                       headers={"Retry-After": str(settings.lockout_minutes * 60)})
    if result.status == "wrong_current":
        raise ApiError(400, "WRONG_CURRENT_PASSWORD", "The current password is incorrect.")
    if result.status == "policy":
        raise ApiError(422, "PASSWORD_POLICY", "The new password does not meet the rules.",
                       details=[{"rule": rule} for rule in result.violations])
    user = {**ctx.user}
    return _token_response(settings, user, result.session, False, now)
