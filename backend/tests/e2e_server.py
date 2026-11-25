"""Backend for the frontend's Playwright test (START_HERE M8): the real API with the fake
pipeline, so no Ollama and no models are needed. Temporary database, seeded users and documents.

Usage (from backend/):  python -m tests.e2e_server --port 8765 --origin http://localhost:5174
Every user's password is tests.conftest.PASSWORD. Not for production: it prints nothing secret
because nothing here is secret.
"""

import argparse
import datetime as dt
import tempfile
from pathlib import Path

import pandas as pd
import uvicorn
from argon2 import PasswordHasher
from sqlalchemy import update

from api import create_app
from audit.writer import Actor
from auth import passwords, service
from config import Settings
from database.init_db import SYSTEM_USER_ID, init_db
from database.models import users
from database.session import Database
from services.document_registry import sync_registry
from src.ingestion.manifest import ManifestEntry
from tests.fakes.fake_pipeline import FakePipeline

PASSWORD = "violet-lantern-orbit-42"  # = tests.conftest.PASSWORD (not imported: pytest fixtures)
USERS = [("e2e_viewer", "viewer", "Vera Viewer"), ("e2e_qa", "qa_user", "Quinn QA"),
         ("e2e_auditor", "auditor", "Aud Itor"), ("e2e_admin", "admin", "Ada Admin")]
SYSTEM = Actor(SYSTEM_USER_ID, "system", "system")


def seed(db: Database) -> None:
    init_db(db)
    with db.write() as conn:
        for username, role, name in USERS:
            user = service.create_user(conn, username=username, full_name=name, role=role,
                                       password=PASSWORD, created_by=None, actor=SYSTEM,
                                       now=dt.datetime.now(dt.UTC))
            conn.execute(update(users).where(users.c.id == user["id"]).values(
                must_change_password=0))
        entries = [ManifestEntry.model_validate(e) for e in (
            {"doc_code": "ICH-Q7", "title": "ICH-Q7 title", "version": "Step 4, 10 Nov 2000",
             "effective_date": "2000-11-10", "file": "public/ICH_Q7.pdf", "publisher": "ICH",
             "source_url": "https://www.ich.org/page/quality-guidelines", "status": "active"},
            {"doc_code": "ACME-SOP-QC-007", "title": "ACME-SOP-QC-007 title", "version": "3.0",
             "effective_date": "2026-01-15", "file": "sops/SOP-QC-007.md",
             "publisher": "Acme Pharma Ltd. (fictional)", "status": "active"})]
        chunks = pd.DataFrame([{"doc_code": e.doc_code, "version": e.version,
                                "doc_sha256": "ab" * 32, "page_end": None} for e in entries])
        sync_registry(conn, entries, chunks, SYSTEM)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--origin", default="http://localhost:5174")
    args = parser.parse_args()
    passwords.configure_hasher(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
    tmp = Path(tempfile.mkdtemp(prefix="gmp_e2e_"))
    settings = Settings(_env_file=None, jwt_secret_key="e2e-" + "k" * 60,
                        sqlite_path=tmp / "app.db", data_dir=tmp, site_origin=args.origin,
                        rate_limit_login="1000/minute", rate_limit_query="1000/minute")
    db = Database(settings.sqlite_path)
    seed(db)
    app = create_app(settings, pipeline=FakePipeline(settings, delay=0.5), db=db)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
