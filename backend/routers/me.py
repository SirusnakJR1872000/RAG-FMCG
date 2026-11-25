"""The signed-in user (PROJECT_SPEC §16 GET /me; design brief §7.1)."""

from fastapi import APIRouter, Depends

from auth.dependencies import AuthContext, current_user_even_if_password_change_pending
from schemas import MeResponse

router = APIRouter(prefix="/api", tags=["auth"])


@router.get("/me", response_model=MeResponse)
def me(ctx: AuthContext = Depends(current_user_even_if_password_change_pending)):
    u = ctx.user
    return MeResponse(id=u["id"], username=u["username"], full_name=u["full_name"],
                      role=u["role"], permissions=ctx.permissions,
                      must_change_password=ctx.must_change_password)
