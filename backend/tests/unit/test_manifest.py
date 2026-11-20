"""Manifest validation and lifecycle rules (PROJECT_SPEC §6.2, §6.4)."""

import hashlib
import textwrap

import pytest

from src.ingestion.manifest import ManifestError, load_manifest, sha256_of

PUBLIC = """
- doc_code: ICH-Q7
  title: "GMP Guide for APIs"
  version: "Step 4, 10 Nov 2000"
  effective_date: 2000-11-10
  file: public/ICH_Q7.pdf
  publisher: ICH
  source_url: https://database.ich.org/sites/default/files/Q7%20Guideline.pdf
  status: active
"""

SOP = """
- doc_code: ACME-SOP-QC-007
  title: "OOS Investigation"
  version: "3.0"
  effective_date: 2026-01-15
  file: sops/SOP-QC-007_OOS_Investigation.md
  publisher: "Acme Pharma Ltd. (fictional)"
  status: active
"""


def write(tmp_path, text):
    path = tmp_path / "manifest.yaml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def test_valid_manifest_loads(tmp_path):
    entries = load_manifest(write(tmp_path, PUBLIC + SOP))
    assert [e.doc_code for e in entries] == ["ICH-Q7", "ACME-SOP-QC-007"]
    assert entries[0].is_public and not entries[0].is_fictional
    assert entries[1].is_fictional and not entries[1].is_public


def test_empty_manifest_is_allowed(tmp_path):
    assert load_manifest(write(tmp_path, "[]\n")) == []


def test_missing_manifest_raises(tmp_path):
    with pytest.raises(ManifestError, match="not found"):
        load_manifest(tmp_path / "nope.yaml")


def test_two_active_versions_of_same_doc_rejected(tmp_path):
    second = SOP.replace('"3.0"', '"3.1"').replace("OOS_Investigation.md", "OOS_v31.md")
    with pytest.raises(ManifestError, match="more than one active"):
        load_manifest(write(tmp_path, SOP + second))


def test_duplicate_code_and_version_rejected(tmp_path):
    with pytest.raises(ManifestError, match="duplicate"):
        load_manifest(write(tmp_path, SOP + SOP.replace("status: active", "status: withdrawn")))


def test_public_document_needs_source_url(tmp_path):
    no_url = "\n".join(line for line in PUBLIC.splitlines() if "source_url" not in line)
    with pytest.raises(ManifestError, match="source_url"):
        load_manifest(write(tmp_path, no_url))


def test_path_traversal_rejected(tmp_path):
    with pytest.raises(ManifestError, match="inside corpus"):
        load_manifest(write(tmp_path, SOP.replace("sops/SOP-QC", "../../etc/SOP-QC")))


def test_unknown_status_rejected(tmp_path):
    with pytest.raises(ManifestError):
        load_manifest(write(tmp_path, SOP.replace("status: active", "status: draft")))


def test_withdrawn_needs_reason(tmp_path):
    with pytest.raises(ManifestError, match="withdrawn_reason"):
        load_manifest(write(tmp_path, SOP.replace("status: active", "status: withdrawn")))


def test_yaml_tags_cannot_execute_code(tmp_path):
    evil = "- !!python/object/apply:os.system ['echo pwned']\n"
    with pytest.raises(Exception):  # noqa: B017 — safe_load refuses python tags outright
        load_manifest(write(tmp_path, evil))


def test_sha256_of_matches_hashlib(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"gmp" * 1000)
    assert sha256_of(f) == hashlib.sha256(b"gmp" * 1000).hexdigest()
