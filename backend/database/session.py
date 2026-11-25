"""The database connection: SQLite in WAL mode with explicit transactions (PROJECT_SPEC §12, §14.3).

`db.read()`  → a normal (deferred) transaction; many can run at once.
`db.write()` → `BEGIN IMMEDIATE`: the write lock is taken at the start, so the audit chain
               (read the last row, then append) can never fork, even with several workers.
Everything in one `write()` block commits together or not at all — a change and the audit
event that records it are one transaction.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Connection, create_engine, event

from database.models import metadata

BUSY_TIMEOUT_MS = 5000  # wait this long for another writer instead of failing at once


class Database:
    def __init__(self, path: Path | str):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.engine = create_engine(f"sqlite:///{path}")

        @event.listens_for(self.engine, "connect")
        def _configure(dbapi_connection, _record):
            dbapi_connection.isolation_level = None  # we send BEGIN ourselves (see below)
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
            cursor.close()

        @event.listens_for(self.engine, "begin")
        def _begin(conn):
            conn.exec_driver_sql("BEGIN IMMEDIATE" if conn.info.get("write") else "BEGIN")

    def create_all(self) -> None:
        metadata.create_all(self.engine)

    def dispose(self) -> None:
        self.engine.dispose()

    @contextmanager
    def read(self) -> Iterator[Connection]:
        with self.engine.connect() as conn:
            yield conn

    @contextmanager
    def write(self) -> Iterator[Connection]:
        """A write transaction: commits on success, rolls back on any exception."""
        with self.engine.connect() as conn:
            conn.info["write"] = True
            try:
                conn.exec_driver_sql("SELECT 1")  # starts the transaction: BEGIN IMMEDIATE
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                conn.info["write"] = False
