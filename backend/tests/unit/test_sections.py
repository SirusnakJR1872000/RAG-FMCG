"""Section detection (PROJECT_SPEC §7.2, amendment A-01)."""

from pathlib import Path

from src.ingestion.normalize import LoadedDocument, PageText
from src.ingestion.sections import detect_sections, is_toc_page, looks_like_heading


def pdf(*pages: str) -> LoadedDocument:
    return LoadedDocument(Path("x.pdf"), [PageText(i, t) for i, t in enumerate(pages, 1)])


def md(text: str) -> LoadedDocument:
    return LoadedDocument(Path("x.md"), [PageText(None, text)])


def summary(doc: LoadedDocument, markdown: bool = False) -> list[tuple[str, bool, str]]:
    return [(s.label, s.is_heading, s.title) for s in detect_sections(doc, markdown)]


def test_numbered_headings_and_paragraphs():
    doc = pdf(
        "1. INTRODUCTION\nSome intro text here.\n"
        "1.1 Objective\nThis guide covers APIs.\n"
        "1.10 The scope is wide and covers many sites."
    )
    assert summary(doc) == [
        ("1", True, "INTRODUCTION"),
        ("1.1", True, "Objective"),
        ("1.10", False, "Objective"),  # Q7 style: paragraph 1.10 under heading 1.1
    ]


def test_ich_q7_paragraph_parent_and_page():
    doc = pdf("1. LABORATORY CONTROLS\n1.1 General Controls",
              "1.15 Any out-of-specification result obtained should be investigated.")
    sec = detect_sections(doc, False)[-1]
    assert (sec.label, sec.parent, sec.title, sec.is_heading) == (
        "1.15", "1.1", "General Controls", False)
    assert sec.lines[0].page == 2


def test_A01_fda_roman_letter_number_with_title_on_next_line():
    doc = pdf("I.\nINTRODUCTION\nText.\nII.\nRECOMMENDATIONS\nC.\n"
              "Stage 2 ― Process Qualification\n"
              "2. Process Performance Qualification\nThe PPQ combines the facility.")
    labels = [(s.label, s.title) for s in detect_sections(doc, False)]
    assert labels == [
        ("I", "INTRODUCTION"),
        ("II", "RECOMMENDATIONS"),
        ("II.C", "Stage 2 ― Process Qualification"),
        ("II.C.2", "Process Performance Qualification"),
    ]


def test_A01_letters_only_count_inside_roman_sections():
    doc = pdf("1. Scope\nA. This is not a heading because there is no Roman section.")
    assert [s.label for s in detect_sections(doc, False)] == ["1"]


def test_A01_roman_number_annex_sections():
    doc = pdf("8. REFERENCES\nI.1 Basic Risk Management Facilitation Methods\nText.")
    assert [s.label for s in detect_sections(doc, False)][-1] == "I.1"


def test_footnotes_and_wrapped_numbers_are_not_headings():
    doc = pdf("1. Scope\n3 In this guidance, the term process refers to it.\n"
              "2.5 times the normal batch size is not allowed.")
    assert [s.label for s in detect_sections(doc, False)] == ["1"]


def test_numbered_list_cannot_walk_through_chapter_numbers():
    doc = pdf("2. QUALITY MANAGEMENT\n2.2 Responsibilities\nThe duties are:\n"
              "3.\nReviewing completed batch records;\n4.\nApproving all specifications;\n"
              "3. PERSONNEL\nStaff text.")
    labels = [s.label for s in detect_sections(doc, False)]
    assert labels == ["2", "2.2", "3"]  # list items 3., 4. were undone; real chapter 3 kept


def test_chapters_follow_the_documents_all_caps_style():
    doc = pdf("1. DEFINITIONS\nText.\n2. REFERENCES\n3. ICH Q8 Pharmaceutical Development")
    assert [s.label for s in detect_sections(doc, False)] == ["1", "2"]


def test_marker_followed_by_sentence_is_a_paragraph():
    doc = pdf("2. QUALITY MANAGEMENT\n2.1 Principles\n2.10\nQuality should be the responsibility "
              "of all persons involved in manufacturing.")
    sec = detect_sections(doc, False)[-1]
    assert (sec.label, sec.is_heading, sec.title) == ("2.10", False, "Principles")


def test_wrapped_heading_title_is_joined():
    doc = pdf("1. Contract production\nText.\n2. Self-inspection, quality audits and\n"
              "suppliers’ audits and approval\n2.1 Principle. The purpose is to evaluate.")
    sec = next(s for s in detect_sections(doc, False) if s.label == "2")
    assert sec.title == "Self-inspection, quality audits and suppliers’ audits and approval"


def test_heading_followed_by_lowercase_sentence_is_demoted():
    doc = pdf("1. EQUIPMENT\n1.4 Computer Systems\nText here.\n1.5 Appropriate\n"
              "installation qualification and operational qualification should demonstrate it.")
    sec = detect_sections(doc, False)[-1]
    assert (sec.label, sec.is_heading) == ("1.5", False)


def test_footnote_number_removed_from_title():
    doc = pdf("II.\nDISCUSSION\nC.\nApproach\n3. Legacy Systems7\nText.")
    assert detect_sections(doc, False)[-1].title == "Legacy Systems"


def test_toc_pages_are_dropped():
    toc = "\n".join(f"{n}. Chapter title {n} ........ {n * 3}" for n in range(1, 8))
    doc = pdf(toc, "1. INTRODUCTION\nReal text.")
    secs = detect_sections(doc, False)
    assert [s.label for s in secs] == ["1"] and secs[0].lines[0].page == 2


def test_who_style_toc_with_page_numbers_on_own_lines():
    lines = ["Introduction", "79", "Glossary", "81", "1. Quality system", "85", "2. GMP", "92"]
    assert is_toc_page(lines)
    assert not is_toc_page(["1. Quality system", "Body text continues here.", "More text."])


def test_markdown_headings_and_numbered_paragraphs():
    doc = md("FICTIONAL DOCUMENT\n\n# SOP-QC-007 OOS Investigation\n\n| Field | Value |\n"
             "## 1. Procedure\n### 1.2 Phase I — laboratory investigation\n"
             "1.2.1 Phase I must be completed within 5 working days.\n")
    assert summary(doc, markdown=True) == [
        ("0", True, "SOP-QC-007 OOS Investigation"),
        ("1", True, "Procedure"),
        ("1.2", True, "Phase I — laboratory investigation"),
        ("1.2.1", False, "Phase I — laboratory investigation"),
    ]


def test_heading_test():
    assert looks_like_heading("Periodic evaluation")
    assert looks_like_heading("Process Performance Qualification")
    assert not looks_like_heading("Supplier performance results are reported in the Review.")
