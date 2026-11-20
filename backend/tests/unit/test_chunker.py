"""Token-bounded chunking (PROJECT_SPEC §7.3, §7.4, amendment A-02).

A fake tokenizer (one token per word, 2 special tokens) keeps these tests fast and offline.
"""

from pathlib import Path

import pytest

from src.ingestion.chunker import Chunker, DocInfo
from src.ingestion.normalize import LoadedDocument, PageText
from src.ingestion.sections import detect_sections

SPECIAL = 2
REQUIRED_FIELDS = {  # PROJECT_SPEC §7.4
    "chunk_id", "doc_id", "doc_code", "doc_title", "version", "doc_sha256", "section",
    "section_title", "page_start", "page_end", "text", "embed_text", "n_tokens",
}


def words(text: str) -> int:
    return len(text.split())


def chunker(max_tokens=40, overlap=8) -> Chunker:
    return Chunker(words, SPECIAL, max_tokens, overlap)


def info(markdown=False) -> DocInfo:
    return DocInfo("ICH-Q7", "GMP Guide for APIs", "Step 4", 1, "ab" * 32, markdown)


def chunks_of(*pages: str, markdown=False, **kw) -> list[dict]:
    doc = LoadedDocument(Path("x"), [PageText(None if markdown else i, t)
                                     for i, t in enumerate(pages, 1)])
    return chunker(**kw).chunk(detect_sections(doc, markdown), info(markdown))


def sentence(n: int, tag: str) -> str:
    """n words starting with a capital, like a real sentence: 'A0x0 a0x1 … end.'"""
    tag = tag[0].upper() + tag[1:]
    return " ".join([f"{tag}{i}" for i in range(n - 1)] + ["end."])


def test_record_has_exactly_the_spec_fields():
    out = chunks_of("1. INTRODUCTION\nShort text.")
    assert set(out[0]) == REQUIRED_FIELDS


def test_no_chunk_exceeds_max_tokens_including_header_and_specials():
    long = " ".join(sentence(9, f"S{i}x") for i in range(30))  # 270 words in one section
    out = chunks_of(f"1. INTRODUCTION\n{long}")
    assert len(out) > 1
    for c in out:
        assert c["n_tokens"] == words(c["embed_text"]) + SPECIAL <= 40


def test_long_section_windows_overlap_by_whole_sentences():
    long = " ".join(sentence(5, f"S{i}x") for i in range(20))
    out = chunks_of(f"1. INTRODUCTION\n{long}", overlap=8)
    for a, b in zip(out, out[1:], strict=False):
        last_sentence_of_a = a["text"].split(". ")[-1]
        assert b["text"].startswith(last_sentence_of_a.rstrip("."))  # repeated context
    assert all(c["section"] == "1" for c in out)
    assert [c["chunk_id"].rsplit(":", 1)[1] for c in out] == [f"{i:03d}" for i in range(len(out))]


def test_A02_small_sibling_paragraphs_merge_into_a_range():
    out = chunks_of("1. LABORATORY CONTROLS\n1.1 General Controls\n"
                    "1.14 Controls are documented.\n1.15 OOS results are investigated.\n"
                    "1.16 Reagents are labelled.", max_tokens=60)
    assert [(c["section"], c["section_title"]) for c in out] == [
        ("1.14–1.16", "General Controls")]
    assert out[0]["embed_text"].startswith("ICH-Q7 | 1.14–1.16 General Controls\n")


def test_merge_stops_at_the_token_limit():
    paras = "\n".join(f"1.3{i} {sentence(12, f'P{i}w')}" for i in range(5))
    out = chunks_of(f"1. PRODUCTION\n1.3 In-process Controls\n{paras}", max_tokens=40)
    assert len(out) > 1 and all(c["n_tokens"] <= 40 for c in out)
    assert all(c["section"].startswith("1.3") for c in out)
    assert any("–" in c["section"] for c in out)


def test_heading_without_text_is_carried_into_next_chunk():
    out = chunks_of("1. LABORATORY CONTROLS\n1.1 General Controls\n"
                    "1.10 The quality unit should have adequate laboratory facilities.")
    assert len(out) == 1
    assert out[0]["section"] == "1.10"
    assert out[0]["text"].startswith("1. LABORATORY CONTROLS 1.1 General Controls 1.10")


def test_every_chunk_has_section_and_page_for_pdf():
    out = chunks_of("1. SCOPE\nScope text on page one.",
                    "2. PRINCIPLES\nPrinciples on page two.")
    assert [(c["section"], c["page_start"], c["page_end"]) for c in out] == [
        ("1", 1, 1), ("2", 2, 2)]


def test_chunk_spanning_pages_records_both():
    out = chunks_of("1. SCOPE\nFirst half of the text.", "Second half on the next page.")
    assert (out[0]["page_start"], out[0]["page_end"]) == (1, 2)


def test_markdown_chunks_have_no_page_and_keep_lines():
    out = chunks_of("# SOP-QC-007 OOS\n## 1. Purpose\nLine one.\n- bullet item", markdown=True)
    purpose = next(c for c in out if c["section"] == "1")
    assert purpose["page_start"] is None and purpose["page_end"] is None
    assert "Line one.\n- bullet item" in purpose["text"]


def test_one_sentence_longer_than_a_chunk_is_split_between_words():
    out = chunks_of("1. SCOPE\n" + " ".join(f"w{i}" for i in range(120)) + ".")
    assert len(out) >= 3 and all(c["n_tokens"] <= 40 for c in out)


def test_ids_are_unique_and_deterministic():
    pages = ("1. SCOPE\n" + " ".join(sentence(6, f"a{i}") for i in range(20)),
             "2. RULES\nRule text.")
    first, second = chunks_of(*pages), chunks_of(*pages)
    ids = [c["chunk_id"] for c in first]
    assert len(ids) == len(set(ids))
    assert ids == [c["chunk_id"] for c in second]
    assert ids[0] == "ICH-Q7:v1:1:000"
    assert first[0]["text"].startswith("1. SCOPE ")  # number kept with its title
    assert first[0]["doc_id"] == second[0]["doc_id"]


@pytest.mark.parametrize("max_tokens", [30, 64, 256])
def test_text_is_never_lost(max_tokens):
    body = " ".join(sentence(7, f"s{i}t") for i in range(40))
    out = chunks_of(f"1. SCOPE\n{body}", max_tokens=max_tokens, overlap=8)
    seen = set(" ".join(c["text"] for c in out).split())
    assert set(body.split()) <= seen
