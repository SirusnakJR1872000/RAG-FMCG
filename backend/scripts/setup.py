"""One-time setup (PROJECT_SPEC §24.1): database, first admin, document registry.

Usage (from backend/):  python -m scripts.setup

Safe to run again: it never changes what exists. Steps:
  1. create the database and the system account;
  2. create the first admin (hidden password prompt) if there is none;
  3. copy the corpus manifest into the document registry, using data/chunks.parquet.

Pulling the LLM (`ollama pull llama3.1:8b`) and building chunks and indexes are separate,
already existing commands (download_docs, build_chunks, build_index); this script tells you
which are still missing. Wiring them into one Docker command is M9.
"""

import argparse
import getpass
import sys
from collections.abc import Callable

import pandas as pd
from sqlalchemy import func, select

from config import Settings, get_settings
from database.init_db import init_db
from database.models import users
from database.session import Database
from scripts.create_admin import SYSTEM, create_admin
from services.document_registry import RegistryConflict, sync_registry
from src.ingestion.manifest import ManifestError, load_manifest


def register_documents(db: Database, settings: Settings) -> str:
    """Sync the registry; returns a one-line report. Needs data/chunks.parquet."""
    chunks_file = settings.data_dir / "chunks.parquet"
    if not chunks_file.is_file():
        return "No chunks yet: run `python -m scripts.build_chunks`, then this script again."
    try:
        entries = load_manifest(settings.manifest_path)
        with db.write() as conn:
            result = sync_registry(conn, entries, pd.read_parquet(chunks_file), SYSTEM)
    except (ManifestError, RegistryConflict) as exc:
        return f"Registry NOT updated: {exc}"
    skipped = f", {len(result.skipped)} without chunks" if result.skipped else ""
    return (f"Registry: {len(result.added)} added, {len(result.updated)} updated{skipped}.")


def main(argv: list[str] | None = None,
         read_password: Callable[[str], str] = getpass.getpass) -> int:
    argparse.ArgumentParser(description="One-time setup.").parse_args(argv)
    settings = get_settings()
    db = Database(settings.sqlite_path)
    try:
        init_db(db)
        print(f"Database ready: {settings.sqlite_path}")
        with db.read() as conn:
            has_admin = conn.execute(select(func.count()).select_from(users).where(
                users.c.role == "admin")).scalar_one() > 0
        if has_admin:
            print("An admin account exists already.")
        else:
            print("Create the first admin account.")
            username = input("Username [admin]: ").strip() or "admin"  # noqa: S322
            password = read_password("Password: ")
            if password != read_password("Repeat password: "):
                print("The two passwords differ.", file=sys.stderr)
                return 1
            try:
                create_admin(db, settings, username, "Administrator", password)
            except ValueError as exc:
                print(exc, file=sys.stderr)
                return 1
            print(f"Created admin '{username}'.")
        print(register_documents(db, settings))
    finally:
        db.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
