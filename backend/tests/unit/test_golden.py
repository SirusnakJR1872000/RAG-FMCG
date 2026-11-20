"""Golden set schema, composition and hit rule (PROJECT_SPEC §11.1)."""

import json

import pytest
from pydantic import ValidationError

from config import PROJECT_ROOT, get_settings
from src.evaluation.golden import (
    Expected,
    GoldenItem,
    SectionTree,
    composition_problems,
    is_hit,
    load_golden,
)
from src.ingestion.manifest import load_manifest
from src.ingestion.sections import Section

GOLDEN = PROJECT_ROOT / "backend/tests/golden/golden_set.jsonl"


def item(i=1, split="dev", answerable=True, code="ICH-Q7", section="11.15", q=None):
    return GoldenItem(
        id=f"G-{i:03d}", split=split, answerable=answerable,
        question=q or f"Question number {i} about GMP?",
        expected=[Expected(doc_code=code, section=section)] if answerable else [],
        key_facts=["a fact"] if answerable else [],
    )


# ── schema ────────────────────────────────────────────────────────────────────

def test_unanswerable_must_have_no_expected_sections():
    with pytest.raises(ValidationError):
        GoldenItem(id="G-001", split="dev", answerable=False, question="Not in any document?",
                   expected=[Expected(doc_code="ICH-Q7", section="1")], key_facts=[])


def test_answerable_needs_expected_and_key_facts():
    with pytest.raises(ValidationError):
        GoldenItem(id="G-001", split="dev", answerable=True, question="What is a PQR exactly?",
                   expected=[], key_facts=[])


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        GoldenItem.model_validate({**item().model_dump(), "style": "direct"})


def test_category_from_expected_documents():
    assert item(code="ICH-Q7").category == "public"
    assert item(code="ACME-SOP-QC-007").category == "sop"
    assert item(answerable=False).category == "unanswerable"


def test_load_reports_line_number(tmp_path):
    path = tmp_path / "g.jsonl"
    path.write_text(json.dumps(item().model_dump()) + "\n{not json}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        load_golden(path)


def test_composition_rules():
    good = (
        [item(i, "dev") for i in range(1, 13)]
        + [item(i, "dev", code="ACME-SOP-QA-005", section="5") for i in range(13, 19)]
        + [item(i, "dev", answerable=False) for i in range(19, 21)]
        + [item(i, "test") for i in range(21, 39)]
        + [item(i, "test", code="ACME-SOP-QA-005", section="5") for i in range(39, 48)]
        + [item(i, "test", answerable=False) for i in range(48, 51)]
    )
    assert composition_problems(good) == []
    bad = good[:-1] + [item(50, "dev", answerable=False)]
    assert any("split" in p for p in composition_problems(bad))


# ── hit rule ──────────────────────────────────────────────────────────────────

def tree(*rows: tuple[str, str | None]) -> SectionTree:
    return SectionTree.from_sections([Section(label, "", parent, True) for label, parent in rows])


Q7 = tree(("11", None), ("11.1", "11"), ("11.14", "11.1"), ("11.15", "11.1"),
          ("11.16", "11.1"), ("11.2", "11"))
WHO = tree(("1", None), ("1.1", "1"), ("1.10", "1"))


def test_exact_match_and_subsection():
    assert Q7.covers("11.15", "11.15")
    assert Q7.covers("11.15", "11.1")  # paragraph under its heading
    assert Q7.covers("11.15", "11")
    assert not Q7.covers("11.1", "11.15")  # a parent is not a subsection of its child


def test_merged_range_counts_as_each_member():
    assert Q7.members("11.14–11.16") == ["11.14", "11.15", "11.16"]
    assert Q7.covers("11.14–11.16", "11.15")
    assert not Q7.covers("11.14–11.16", "11.2")


def test_string_prefix_is_not_enough():
    assert not WHO.covers("1.10", "1.1")  # WHO 1.10 is a sibling of 1.1, not a child


def test_is_hit_requires_matching_document():
    trees = {"ICH-Q7": Q7}
    expected = [Expected(doc_code="ICH-Q7", section="11.15")]
    assert is_hit(trees, "ICH-Q7", "11.14–11.16", expected)
    assert not is_hit(trees, "WHO-GMP-MAIN", "11.15", expected)


# ── the real golden set (no PDFs needed) ──────────────────────────────────────

@pytest.mark.skipif(not GOLDEN.is_file(), reason="golden set not written yet")
def test_real_golden_set_schema_and_composition():
    items = load_golden(GOLDEN)
    assert composition_problems(items) == []
    codes = {e.doc_code for e in load_manifest(get_settings().manifest_path)}
    unknown = {e.doc_code for i in items for e in i.expected} - codes
    assert not unknown, f"expected doc_codes not in manifest: {unknown}"
