"""Settings load from .env, resolve paths, and reject inconsistent values (PROJECT_SPEC §26)."""

import pytest
from pydantic import ValidationError

from config import PROJECT_ROOT, Settings

SECRET = "x" * 64


def make(**overrides) -> Settings:
    # _env_file=None: tests never depend on the developer's real .env
    return Settings(_env_file=None, jwt_secret_key=SECRET, **overrides)


def test_defaults_match_env_example():
    s = make()
    assert s.chunk_max_tokens == 256
    assert s.chunk_overlap_tokens == 48
    assert s.llm_num_ctx == 4096
    assert s.llm_model == "llama3.1:8b"


def test_relative_paths_resolve_against_project_root():
    s = make()
    assert s.corpus_dir == PROJECT_ROOT / "corpus"
    assert s.manifest_path == PROJECT_ROOT / "corpus" / "manifest.yaml"


def test_real_env_example_parses_including_inline_comments():
    s = Settings(_env_file=PROJECT_ROOT / ".env.example")
    assert s.app_env == "development"  # value has a trailing "# development | production"
    assert s.query_expansion is False


def test_short_jwt_secret_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret_key="short")  # noqa: S106 (test value)


def test_overlap_must_be_smaller_than_chunk_size():
    with pytest.raises(ValidationError):
        make(chunk_max_tokens=48, chunk_overlap_tokens=48)


def test_chunk_size_cannot_exceed_256():
    with pytest.raises(ValidationError):
        make(chunk_max_tokens=512)


def test_placeholder_secret_rejected_in_production():
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None, app_env="production",
            jwt_secret_key="change-me-run-openssl-rand-hex-32",  # noqa: S106 (test value)
        )


def test_unknown_setting_rejected():
    with pytest.raises(ValidationError):
        make(not_a_real_setting=1)
