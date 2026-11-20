"""Load the real corpus end to end (PROJECT_SPEC §7.1).

Skipped when the public PDFs have not been downloaded (e.g. in CI):
run `python -m scripts.download_docs` first.
"""

import pytest

from config import get_settings
from src.ingestion.manifest import load_manifest
from src.ingestion.md_loader import load_markdown
from src.ingestion.pdf_loader import line_key, load_pdf

SETTINGS = get_settings()
ENTRIES = load_manifest(SETTINGS.manifest_path)
PUBLIC = [e for e in ENTRIES if e.is_public]
PDFS_PRESENT = all((SETTINGS.corpus_dir / e.file).is_file() for e in PUBLIC)

pytestmark = pytest.mark.skipif(not PDFS_PRESENT, reason="public PDFs not downloaded")

RUNNING_HEADERS = {
    "ICH-Q7": "Good Manufacturing Practice Guide for Active Pharmaceutical Ingredients",
    "ICH-Q9R1": "ICH Q9(R1) Guideline",
    "FDA-PV-2011": "Contains Nonbinding Recommendations",
    "FDA-P11-2003": "Contains Nonbinding Recommendations",
}


def load(entry):
    path = SETTINGS.corpus_dir / entry.file
    return load_pdf(path) if path.suffix == ".pdf" else load_markdown(path)


@pytest.mark.parametrize("entry", ENTRIES, ids=[e.doc_code for e in ENTRIES])
def test_every_manifest_document_loads_with_text(entry):
    doc = load(entry)
    assert doc.pages
    assert all(len(p.text) >= 100 for p in doc.pages)


@pytest.mark.parametrize("code", RUNNING_HEADERS)
def test_running_header_removed_from_page_edges(code):
    entry = next(e for e in PUBLIC if e.doc_code == code)
    header = line_key(RUNNING_HEADERS[code])
    for page in load(entry).pages:
        lines = page.text.splitlines()
        assert header not in {line_key(x) for x in lines[:3] + lines[-3:]}, f"page {page.page}"


def test_page_numbers_removed_from_ich_q7():
    # From page 3 on. Page 2 is the Document History table: its "10" is half of the date
    # "10 November 2000" split across table cells, i.e. real content that must be kept.
    for page in load(next(e for e in PUBLIC if e.doc_code == "ICH-Q7")).pages[2:]:
        lines = page.text.splitlines()
        assert not any(x.strip().isdigit() for x in lines[:3] + lines[-3:]), f"page {page.page}"


def test_ich_q7_oos_paragraph_intact():
    page = next(p for p in load(next(e for e in PUBLIC if e.doc_code == "ICH-Q7")).pages
                if p.page == 29)
    assert "11.15 Any out-of-specification result obtained should be investigated" in page.text
