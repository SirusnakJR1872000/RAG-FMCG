"""Fixtures shared by the backend tests."""

import pytest

from audit.writer import Actor
from database.init_db import init_db
from database.session import Database


@pytest.fixture
def db(tmp_path):
    """A fresh SQLite database file (WAL mode needs a real file) with the schema."""
    database = Database(tmp_path / "app.db")
    init_db(database)
    yield database
    database.dispose()


@pytest.fixture
def actor():
    return Actor(user_id=None, username="tester", role="admin", client_ip="10.0.0.5",
                 request_id="req_abc123")


# ── API fixtures ─────────────────────────────────────────────────────────────────────────

import datetime as dt  # noqa: E402

from argon2 import PasswordHasher  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import update  # noqa: E402

from api import create_app  # noqa: E402
from auth import passwords, service  # noqa: E402
from config import Settings  # noqa: E402
from database.models import users  # noqa: E402
from tests.fakes.fake_pipeline import FakePipeline  # noqa: E402

ORIGIN = "https://app.test"
PASSWORD = "violet-lantern-orbit-42"


@pytest.fixture(autouse=True)
def fast_password_hashing():
    """Argon2 at production strength takes ~0.1 s per hash; tests create many users."""
    passwords.configure_hasher(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
    yield
    passwords.configure_hasher(PasswordHasher())


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, jwt_secret_key="k" * 64, sqlite_path=tmp_path / "api.db",
                    data_dir=tmp_path, site_origin=ORIGIN, rate_limit_login="1000/minute",
                    rate_limit_query="1000/minute")


@pytest.fixture
def pipeline(settings):
    return FakePipeline(settings)


@pytest.fixture
def make_client(settings, pipeline):
    """Build apps on demand: `make_client()` or `make_client(settings=..., pipeline=None)`."""
    opened = []

    def build(settings_=None, pipeline_=pipeline):
        client = TestClient(create_app(settings_ or settings, pipeline=pipeline_),
                            base_url=ORIGIN, raise_server_exceptions=False)
        client.__enter__()  # runs start-up
        opened.append(client)
        return client

    yield build
    for client in opened:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client):
    return make_client()


def add_user(client, username, role="viewer", password=PASSWORD, must_change=False):
    """Create a user directly in the app's database (as `create_admin.py` would)."""
    from audit.writer import Actor

    with client.app.state.db.write() as conn:
        user = service.create_user(conn, username=username, full_name=username.title(),
                                   role=role, password=password, created_by=None,
                                   actor=Actor(None, "test-setup"),
                                   now=dt.datetime.now(dt.UTC))
        if not must_change:
            conn.execute(update(users).where(users.c.id == user["id"]).values(
                must_change_password=0))
    return user


def sign_in(client, username, password=PASSWORD):
    """Log in through the API; returns the Authorization header for later calls."""
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def make_headers(client):
    """`make_headers("viewer")` → a signed-in user of that role (created once per name)."""
    cache = {}

    def build(role):
        if role not in cache:
            add_user(client, f"{role}_user", role)
            cache[role] = sign_in(client, f"{role}_user")
        return cache[role]

    return build
