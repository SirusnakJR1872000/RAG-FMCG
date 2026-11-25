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
