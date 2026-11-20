"""PDF/Markdown loaders, header/footer removal and normalisation (PROJECT_SPEC §7.1)."""

import pymupdf
import pytest

from src.ingestion.md_loader import load_markdown
from src.ingestion.normalize import normalize_text
from src.ingestion.pdf_loader import line_key, load_pdf

BODY = (
    "Quality should be the responsibility of all persons involved in manufacturing. "
    "Each manufacturer should establish, document and implement an effective system."
)
# Different body text on each page, as in a real document (identical bodies would themselves
# look like repeated headers when a page is short).
TOPICS = ["sampling", "labelling", "cleaning", "storage", "calibration", "training"]


def body_lines(n):
    topic = TOPICS[n % len(TOPICS)]
    return [
        f"This paragraph describes {topic} controls for intermediates and APIs.",
        f"Written procedures for {topic} should be approved by the quality unit.",
        f"Records of {topic} activities should be retained and reviewed regularly.",
        f"Deviations in {topic} should be documented and explained before release.",
    ]


def make_pdf(path, pages):
    """Write a PDF where each page is a list of lines (top to bottom)."""
    doc = pymupdf.open()
    for lines in pages:
        page = doc.new_page()
        for i, line in enumerate(lines):
            page.insert_text((72, 72 + 18 * i), line, fontsize=10)
    doc.save(path)
    doc.close()
    return path


def page(n, header=True, footer=True):
    lines = (["ICH Q7 Guideline"] if header else []) + body_lines(n)
    return lines + ([f"Page {n} of 12"] if footer else [])


# ── normalisation ─────────────────────────────────────────────────────────────

def test_normalize_nfkc_ligatures_and_spaces():
    assert normalize_text("ﬁrst   speciﬁcation limit") == "first specification limit"


def test_normalize_rejoins_hyphenated_line_break():
    assert normalize_text("the manufac-\nturing process") == "the manufacturing process"


def test_normalize_keeps_hyphen_before_capital_or_list_item():
    assert normalize_text("see ICH-\nQ7") == "see ICH-\nQ7"


def test_normalize_keeps_lines_and_collapses_blank_runs():
    assert normalize_text("8.1 Title\n\n\n\nBody  text") == "8.1 Title\n\nBody text"


def test_line_key_treats_page_numbers_of_any_width_alike():
    assert line_key("Page 9  of 49") == line_key("Page 10 of 49") == "Page # of #"


# ── header / footer removal ───────────────────────────────────────────────────

def test_header_and_page_number_footer_removed(tmp_path):
    # pages 8–12: page numbers cross from one digit to two
    doc = load_pdf(make_pdf(tmp_path / "a.pdf", [page(n) for n in range(8, 13)]))
    assert len(doc.pages) == 5
    for p in doc.pages:
        assert "ICH Q7 Guideline" not in p.text
        assert "of 12" not in p.text
        assert "should be approved by the quality unit" in p.text
    assert "Page # of #" in doc.removed_lines


def test_line_on_exactly_half_the_pages_is_kept(tmp_path):
    # header on 2 of 4 pages = 50%: the rule needs MORE than 50%
    pages = [page(1), page(2), page(3, header=False), page(4, header=False)]
    doc = load_pdf(make_pdf(tmp_path / "b.pdf", pages))
    assert sum("ICH Q7 Guideline" in p.text for p in doc.pages) == 2


def test_repeated_line_in_page_body_is_kept(tmp_path):
    # the same sentence sits in the middle of every page, outside the top/bottom 3 lines
    middle = "Repeated body sentence"
    pages = [[f"Top {t} one", f"Top {t} two", f"Top {t} three", middle, BODY[:90], BODY[90:],
              f"End {t} a", f"End {t} b", f"End {t} c"] for t in TOPICS[:4]]
    doc = load_pdf(make_pdf(tmp_path / "c.pdf", pages))
    assert all(middle in p.text for p in doc.pages)


def test_short_pages_skipped_and_reported(tmp_path):
    pages = [page(1), ["ICH Q7 Guideline", "Intentionally blank", "Page 2 of 12"], page(3), page(4)]
    doc = load_pdf(make_pdf(tmp_path / "d.pdf", pages))
    assert doc.skipped_pages == [2]
    assert [p.page for p in doc.pages] == [1, 3, 4]


def test_no_stripping_for_very_short_documents(tmp_path):
    doc = load_pdf(make_pdf(tmp_path / "e.pdf", [page(1), page(2)]))
    assert doc.removed_lines == []
    assert all("ICH Q7 Guideline" in p.text for p in doc.pages)


# ── markdown ──────────────────────────────────────────────────────────────────

def test_markdown_single_page_without_number(tmp_path):
    md = tmp_path / "sop.md"
    md.write_text("FICTIONAL DOCUMENT\n\n## 1. Purpose\n\nSpeciﬁcation  text.\n", encoding="utf-8")
    doc = load_markdown(md)
    assert len(doc.pages) == 1 and doc.pages[0].page is None
    assert doc.pages[0].text.startswith("FICTIONAL DOCUMENT")
    assert "## 1. Purpose\n\nSpecification text." in doc.pages[0].text


def test_markdown_must_be_utf8(tmp_path):
    md = tmp_path / "bad.md"
    md.write_bytes(b"\xff\xfe not utf-8 \x80")
    with pytest.raises(UnicodeDecodeError):
        load_markdown(md)
