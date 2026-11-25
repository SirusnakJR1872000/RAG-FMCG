"""Request and response bodies (PROJECT_SPEC §15.2: unknown fields are rejected).

Declaring them here also makes /docs show every endpoint's exact shape.
"""

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class LoginRequest(Strict):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordRequest(Strict):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 — the OAuth token type, not a secret
    expires_in: int = Field(description="seconds until the access token expires")
    must_change_password: bool


class MeResponse(BaseModel):
    id: str
    username: str
    full_name: str
    role: str
    permissions: list[str]
    must_change_password: bool


class HealthResponse(BaseModel):
    status: str = Field(description="ready | degraded | not_ready")


class QueryRequest(Strict):
    question: str = Field(min_length=3, max_length=1000)
    conversation_id: str | None = Field(default=None, max_length=64)


class FeedbackRequest(Strict):
    query_event_id: str = Field(min_length=1, max_length=64)
    rating: int = Field(description="1 = helpful, -1 = not helpful")
    comment: str | None = Field(default=None, max_length=1000)
