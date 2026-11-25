"""The setup scripts (PROJECT_SPEC §24.1)."""

import json

import pandas as pd
import pytest
from sqlalchemy import select

from auth import passwords
from database.init_db import SYSTEM_USER_ID, init_db
from database.models import audit_log, documents, users
from scripts import create_admin as create_admin_script
from scripts import setup as setup_script
from tests.conftest import PASSWORD

MANIFEST = """
- doc_code: ACME-SOP-QC-007
  title: "OOS Investigation"
  version: "3.0"
  effective_date: 2026-01-15
  file: sops/SOP-QC-007.md
  publisher: "Acme Pharma Ltd. (fictional)"
  status: active
"""


def test_create_admin_makes_a_working_admin_without_a_forced_password_change(db, settings):
    user = create_admin_script.create_admin(db, settings, " Root ", "The Admin", PASSWORD)
    with db.read() as conn:
        row = conn.execute(select(users).where(users.c.id == user["id"])).mappings().one()
        event = conn.execute(select(audit_log.c.username, audit_log.c.payload_json).where(
            audit_log.c.event_type == "USER_CREATED")).one()
    assert (row["username"], row["role"], row["must_change_password"]) == ("root", "admin", 0)
    assert row["created_by"] == SYSTEM_USER_ID
    assert passwords.verify_password(row["password_hash"], PASSWORD)
    assert event.username == "system" and PASSWORD not in event.payload_json


@pytest.mark.parametrize("password", ["short", "password1234"])
def test_create_admin_enforces_the_password_policy(db, settings, password):
    with pytest.raises(ValueError, match="not acceptable"):
        create_admin_script.create_admin(db, settings, "root", "Admin", password)


def test_create_admin_refuses_an_existing_username(db, settings):
    create_admin_script.create_admin(db, settings, "root", "Admin", PASSWORD)
    with pytest.raises(ValueError, match="already exists"):
        create_admin_script.create_admin(db, settings, "ROOT", "Admin", PASSWORD)


def test_create_admin_command_prompts_twice_and_reports_mismatches(settings, monkeypatch, capsys):
    monkeypatch.setattr(create_admin_script, "get_settings", lambda: settings)
    answers = iter([PASSWORD, "something else entirely"])
    assert create_admin_script.main(["--username", "root"], lambda _: next(answers)) == 1
    assert "differ" in capsys.readouterr().err
    answers = iter([PASSWORD, PASSWORD])
    assert create_admin_script.main(["--username", "root"], lambda _: next(answers)) == 0
    assert "Created admin 'root'" in capsys.readouterr().out
    answers = iter([PASSWORD, PASSWORD])  # the same name again
    assert create_admin_script.main(["--username", "root"], lambda _: next(answers)) == 1


@pytest.fixture(autouse=True)
def private_corpus(settings, tmp_path):
    """Never touch the real corpus/: these tests write their own manifest."""
    settings.corpus_dir = tmp_path / "corpus"


def prepare_corpus(settings, sha="ab" * 32):
    settings.corpus_dir.mkdir(parents=True, exist_ok=True)
    settings.manifest_path.write_text(MANIFEST, encoding="utf-8")
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"doc_code": "ACME-SOP-QC-007", "version": "3.0", "doc_sha256": sha,
                   "page_end": None}] * 4).to_parquet(settings.data_dir / "chunks.parquet")


def test_setup_creates_everything_and_a_second_run_changes_nothing(settings, monkeypatch, capsys):
    monkeypatch.setattr(setup_script, "get_settings", lambda: settings)
    monkeypatch.setattr("builtins.input", lambda _: "boss")
    prepare_corpus(settings)
    answers = iter([PASSWORD, PASSWORD])
    assert setup_script.main([], lambda _: next(answers)) == 0
    first = capsys.readouterr().out
    assert "Created admin 'boss'" in first and "Registry: 1 added" in first
    assert setup_script.main([], lambda _: pytest.fail("must not ask again")) == 0
    second = capsys.readouterr().out
    assert "exists already" in second and "Registry: 0 added, 0 updated" in second
    db = setup_script.Database(settings.sqlite_path)
    with db.read() as conn:
        assert conn.execute(select(documents.c.chunk_count)).scalar() == 4
        types = [json.loads(r)["doc_code"] for r in conn.execute(select(
            audit_log.c.payload_json).where(audit_log.c.event_type == "DOCUMENT_INGESTED")
        ).scalars()]
    assert types == ["ACME-SOP-QC-007"]
    db.dispose()


def test_setup_tells_you_what_is_missing_instead_of_failing(settings, monkeypatch, capsys):
    monkeypatch.setattr(setup_script, "get_settings", lambda: settings)
    db = setup_script.Database(settings.sqlite_path)
    init_db(db)
    assert "build_chunks" in setup_script.register_documents(db, settings)
    prepare_corpus(settings)
    settings.manifest_path.write_text("- doc_code: not valid\n", encoding="utf-8")
    assert "Registry NOT updated" in setup_script.register_documents(db, settings)
    prepare_corpus(settings)
    setup_script.register_documents(db, settings)
    prepare_corpus(settings, sha="cd" * 32)  # same version, different file
    assert "needs a new version" in setup_script.register_documents(db, settings)
    db.dispose()


def test_setup_stops_when_the_passwords_differ(settings, monkeypatch, capsys):
    monkeypatch.setattr(setup_script, "get_settings", lambda: settings)
    monkeypatch.setattr("builtins.input", lambda _: "")
    answers = iter([PASSWORD, "different-password-12"])
    assert setup_script.main([], lambda _: next(answers)) == 1
    assert "differ" in capsys.readouterr().err
