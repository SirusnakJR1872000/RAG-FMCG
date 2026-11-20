"""Application settings, loaded from `.env` (PROJECT_SPEC §26).

Every tunable value lives here. Code imports `get_settings()` instead of hardcoding numbers.
Relative paths in `.env` (e.g. `CORPUS_DIR=corpus`) are resolved against the project root,
so scripts behave the same whether they are run from the repo root or from `backend/`.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="forbid",  # a typo in .env is an error, not a silently ignored setting
    )

    # ── Site ──
    site_origin: str = "https://localhost"
    app_env: Literal["development", "production"] = "development"

    # ── Security ──
    jwt_secret_key: str = Field(min_length=32)
    access_token_ttl_minutes: int = Field(15, gt=0)
    refresh_idle_minutes: int = Field(30, gt=0)
    refresh_absolute_hours: int = Field(8, gt=0)
    max_failed_logins: int = Field(5, gt=0)
    lockout_minutes: int = Field(30, gt=0)
    password_min_length: int = Field(12, ge=12)
    password_history_count: int = Field(5, ge=0)
    password_expiry_days: int = Field(90, gt=0)
    rate_limit_query: str = "10/minute"
    rate_limit_login: str = "5/minute"

    # ── LLM ──
    ollama_base_url: str = "http://127.0.0.1:11434"
    llm_model: str = "llama3.1:8b"
    question_gen_model: str = "llama3.2:3b"
    llm_num_ctx: int = Field(4096, gt=0)
    llm_temperature: float = Field(0.1, ge=0)
    llm_top_p: float = Field(0.9, gt=0, le=1)
    llm_repeat_penalty: float = Field(1.1, gt=0)
    llm_max_tokens_answer: int = Field(400, gt=0)
    llm_max_tokens_rewrite: int = Field(64, gt=0)
    llm_keep_alive: str = "30m"
    llm_timeout_seconds: int = Field(180, gt=0)
    llm_queue_max: int = Field(10, gt=0)

    # ── Retrieval ──
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    chunk_max_tokens: int = Field(256, gt=0, le=256)  # §7.3: 256 = smallest candidate max length
    chunk_overlap_tokens: int = Field(48, ge=0)
    candidates_per_retriever: int = Field(20, gt=0)
    rrf_k: int = Field(60, gt=0)
    context_chunks: int = Field(4, gt=0)
    relevance_threshold: float = 0.0
    query_expansion: bool = False
    history_turns: int = Field(2, ge=0)

    # ── Limits ──
    question_min_chars: int = Field(3, gt=0)
    question_max_chars: int = Field(1000, gt=0)

    # ── Paths (relative values are resolved against PROJECT_ROOT) ──
    corpus_dir: Path = Path("corpus")
    data_dir: Path = Path("data")
    index_dir: Path = Path("indexes")
    model_dir: Path = Path("models")
    reports_dir: Path = Path("reports")
    sqlite_path: Path = Path("data/app.db")
    backup_dir: Path = Path("backups")

    # ── Logging ──
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator(
        "corpus_dir", "data_dir", "index_dir", "model_dir", "reports_dir", "sqlite_path",
        "backup_dir",
    )
    @classmethod
    def _resolve_path(cls, value: Path) -> Path:
        return value if value.is_absolute() else (PROJECT_ROOT / value).resolve()

    @model_validator(mode="after")
    def _check_consistency(self) -> "Settings":
        if self.chunk_overlap_tokens >= self.chunk_max_tokens:
            raise ValueError("CHUNK_OVERLAP_TOKENS must be smaller than CHUNK_MAX_TOKENS")
        if self.question_min_chars >= self.question_max_chars:
            raise ValueError("QUESTION_MIN_CHARS must be smaller than QUESTION_MAX_CHARS")
        if self.app_env == "production" and self.jwt_secret_key.startswith("change-me"):
            raise ValueError("JWT_SECRET_KEY still has the placeholder value")
        return self

    @property
    def manifest_path(self) -> Path:
        return self.corpus_dir / "manifest.yaml"


@lru_cache
def get_settings() -> Settings:
    """Load settings once per process."""
    return Settings()
