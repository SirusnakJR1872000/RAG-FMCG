"""Real tokenizer, real corpus (PROJECT_SPEC §7.3, §7.4; START_HERE M1 tests).

Skipped when the public PDFs are not downloaded or the tokenizer cannot be loaded.
"""

import pandas as pd
import pytest

from config import get_settings
from scripts.build_chunks import build_chunk_table, unlisted_files
from src.ingestion.manifest import load_manifest

SETTINGS = get_settings()
ENTRIES = load_manifest(SETTINGS.manifest_path)
PDFS_PRESENT = all((SETTINGS.corpus_dir / e.file).is_file() for e in ENTRIES)

pytestmark = pytest.mark.skipif(not PDFS_PRESENT, reason="public PDFs not downloaded")


@pytest.fixture(scope="module")
def chunks() -> pd.DataFrame:
    try:
        return build_chunk_table(SETTINGS)
    except OSError as exc:  # tokenizer not cached and no network
        pytest.skip(f"tokenizer unavailable: {exc}")


def test_every_active_document_is_chunked(chunks):
    assert set(chunks["doc_code"]) == {e.doc_code for e in ENTRIES if e.status == "active"}


def test_no_chunk_exceeds_max_tokens(chunks):
    assert chunks["n_tokens"].max() <= SETTINGS.chunk_max_tokens


def test_every_chunk_has_a_section_and_pdf_chunks_have_pages(chunks):
    assert (chunks["section"].str.len() > 0).all()
    pdf = chunks[~chunks["doc_code"].str.startswith("ACME-")]
    sop = chunks[chunks["doc_code"].str.startswith("ACME-")]
    assert pdf["page_start"].notna().all() and (pdf["page_start"] <= pdf["page_end"]).all()
    assert sop["page_start"].isna().all()


def test_chunk_ids_are_unique(chunks):
    assert chunks["chunk_id"].is_unique


def test_embed_text_is_header_plus_text(chunks):
    for row in chunks.itertuples():
        assert row.embed_text.endswith(row.text)
        assert row.embed_text.startswith(f"{row.doc_code} | {row.section}")


def test_known_citations_are_found(chunks):
    def sections_containing(code: str, phrase: str) -> set[str]:
        rows = chunks[(chunks["doc_code"] == code) & chunks["text"].str.contains(phrase)]
        return set(rows["section"])

    q7 = sections_containing("ICH-Q7", "Any out-of-specification result obtained")
    assert any("11.1" in s for s in q7), q7  # 11.15, or a range such as 11.14–11.16
    assert "IV.C.2" in set(chunks.loc[chunks["doc_code"] == "FDA-PV-2011", "section"])
    assert "9" in set(chunks.loc[chunks["doc_code"] == "EU-ANNEX11", "section"])
    sop = sections_containing("ACME-SOP-QC-007", "within \\*\\*5 working days\\*\\*")
    assert any(s.startswith("5.2") for s in sop), sop


def test_no_unlisted_files_in_corpus():
    assert unlisted_files(SETTINGS.corpus_dir, ENTRIES) == []
