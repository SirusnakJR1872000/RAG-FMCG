"""Every expected section in the golden set exists and is reachable (PROJECT_SPEC §11.1).

No retrieval is involved: this only proves that each answerable question *can* be hit,
i.e. at least one chunk carries an expected section. Skipped without the public PDFs.
"""

import pytest

from config import PROJECT_ROOT, get_settings
from scripts.build_chunks import build_chunk_table
from src.evaluation.golden import is_hit, load_golden, load_section_trees
from src.ingestion.manifest import load_manifest

SETTINGS = get_settings()
GOLDEN = load_golden(PROJECT_ROOT / "backend/tests/golden/golden_set.jsonl")
PDFS_PRESENT = all((SETTINGS.corpus_dir / e.file).is_file()
                   for e in load_manifest(SETTINGS.manifest_path))
pytestmark = pytest.mark.skipif(not PDFS_PRESENT, reason="public PDFs not downloaded")
ANSWERABLE = [g for g in GOLDEN if g.answerable]


@pytest.fixture(scope="module")
def trees():
    return load_section_trees(SETTINGS)


@pytest.fixture(scope="module")
def chunks():
    try:
        return build_chunk_table(SETTINGS)
    except OSError as exc:
        pytest.skip(f"tokenizer unavailable: {exc}")


@pytest.mark.parametrize("item", ANSWERABLE, ids=[g.id for g in ANSWERABLE])
def test_expected_sections_exist(item, trees):
    for e in item.expected:
        assert e.section in trees[e.doc_code], f"{e.doc_code} has no section {e.section}"


@pytest.mark.parametrize("item", ANSWERABLE, ids=[g.id for g in ANSWERABLE])
def test_every_expected_section_is_carried_by_some_chunk(item, trees, chunks):
    for e in item.expected:
        rows = chunks[chunks["doc_code"] == e.doc_code]
        assert any(is_hit(trees, e.doc_code, s, [e]) for s in rows["section"]), (
            f"no chunk covers {e.doc_code} §{e.section}")
