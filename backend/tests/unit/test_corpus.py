"""The committed corpus follows PROJECT_SPEC §2.1, §1.4 and §6.3.

Only the fictional SOPs are checked for content: the public PDFs are gitignored,
so these tests also run in CI where the PDFs are not downloaded.
"""

import re

import pytest

from config import get_settings
from src.ingestion.manifest import load_manifest

SETTINGS = get_settings()
ENTRIES = load_manifest(SETTINGS.manifest_path)
SOPS = [e for e in ENTRIES if e.is_fictional]
SOP_IDS = [e.doc_code for e in SOPS]


def sop_text(entry) -> str:
    return (SETTINGS.corpus_dir / entry.file).read_text(encoding="utf-8")


def header_field(text: str, name: str) -> str:
    match = re.search(rf"^\| {name} \| (.+?) \|$", text, re.MULTILINE)
    assert match, f"header field '{name}' missing"
    return match.group(1)


def test_tier1_corpus_is_7_public_and_12_fictional():
    assert sum(e.is_public for e in ENTRIES) == 7
    assert len(SOPS) == 12
    assert all(e.status == "active" for e in ENTRIES)


@pytest.mark.parametrize("entry", SOPS, ids=SOP_IDS)
def test_sop_first_line_is_fictional_marker(entry):
    first_line = sop_text(entry).splitlines()[0]
    assert first_line.startswith("FICTIONAL DOCUMENT")


@pytest.mark.parametrize("entry", SOPS, ids=SOP_IDS)
def test_sop_header_matches_manifest(entry):
    text = sop_text(entry)
    assert f"ACME-{header_field(text, 'Document number')}" == entry.doc_code
    assert header_field(text, "Version") == entry.version
    assert header_field(text, "Effective date") == entry.effective_date.isoformat()
    assert header_field(text, "Company") == "Acme Pharma Ltd. (fictional)"


@pytest.mark.parametrize("entry", SOPS, ids=SOP_IDS)
def test_sop_has_numbered_sections_and_required_parts(entry):
    text = sop_text(entry)
    top = re.findall(r"^## (\d+)\. (.+)$", text, re.MULTILINE)
    numbers = [int(n) for n, _ in top]
    assert numbers == list(range(1, len(numbers) + 1)), "top-level sections must be 1, 2, 3…"
    titles = " ".join(t for _, t in top).lower()
    for required in ("purpose", "scope", "responsibilities", "references", "revision history"):
        assert required in titles, f"missing section: {required}"


@pytest.mark.parametrize("entry", SOPS, ids=SOP_IDS)
def test_sop_cross_references_point_to_existing_sops(entry):
    referenced = set(re.findall(r"\bSOP-[A-Z]{2}-\d{3}\b", sop_text(entry)))
    known = {code.removeprefix("ACME-") for code in SOP_IDS}
    assert referenced <= known, f"unknown SOPs referenced: {referenced - known}"


def test_at_least_four_sops_cover_public_guidance_topics():
    """§6.3: cross-document questions need SOPs that cite the public guidance."""
    citing = [e for e in SOPS if re.search(r"ICH Q\d|Annex 11|FDA Guidance", sop_text(e))]
    assert len(citing) >= 4
