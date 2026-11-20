"""PDF loader: text per page, repeated headers/footers removed (PROJECT_SPEC §7.1).

Header/footer rule (exact spec wording): a line that, after whitespace normalisation and with
digits replaced by `#`, appears in the top or bottom 3 lines of more than 50% of pages is a
header/footer. Such lines are removed only where they appear in those top/bottom positions,
so the same text in the body of a page is kept.
"""

import re
from collections import Counter
from pathlib import Path

import pymupdf
import structlog

from src.ingestion.normalize import LoadedDocument, PageText, normalize_text

log = structlog.get_logger(__name__)

EDGE_LINES = 3  # top/bottom lines inspected on each page (§7.1)
REPEAT_SHARE = 0.5  # a pattern must appear on MORE than this share of pages (§7.1)
MIN_PAGE_CHARS = 100  # pages with less text are skipped and logged (§7.1)
MIN_PAGES_FOR_STRIPPING = 3  # with 1–2 pages "more than 50%" would strip every title line
MIN_LINE_NUMBERS = 10  # a page needs this many bare numbers to have margin line numbering…
LINE_NUMBER_STEP_SHARE = 0.8  # …and most consecutive pairs must count up by exactly one


def line_key(line: str) -> str:
    """Comparison key for a line: whitespace collapsed, each run of digits replaced by '#'.

    Runs, not single digits: otherwise "Page 9" (#) and "Page 10" (##) get different keys and
    the footers of pages 1–9 never reach the 50% threshold.
    """
    return re.sub(r"\d+", "#", re.sub(r"\s+", " ", line).strip())


def _edge_indexes(n_lines: int) -> set[int]:
    return set(range(min(EDGE_LINES, n_lines))) | set(range(max(0, n_lines - EDGE_LINES), n_lines))


def _repeated_in(pages: list[list[str]]) -> set[str]:
    if len(pages) < MIN_PAGES_FOR_STRIPPING:
        return set()
    counts: Counter[str] = Counter()
    for lines in pages:
        counts.update({line_key(lines[i]) for i in _edge_indexes(len(lines))})
    return {key for key, n in counts.items() if key and n > REPEAT_SHARE * len(pages)}


def find_repeated_lines(pages: list[list[str]]) -> set[str]:
    """Keys of lines in the top/bottom lines of more than half the pages (§7.1, A-03).

    Checked over all pages, and over odd and even pages separately: book-style documents
    (e.g. WHO TRS) put one running header on odd pages and another on even pages, so each
    appears on only ~50% of all pages.
    """
    return _repeated_in(pages) | _repeated_in(pages[0::2]) | _repeated_in(pages[1::2])


def strip_line_numbers(lines: list[str]) -> list[str]:
    """Remove margin line numbers (FDA Part 11 numbers every line: 76, 77, 78…).

    Only a long run of bare numbers that mostly count up by one is treated as line numbering;
    scattered numbers such as table-of-contents page references are kept.
    """
    numbers = [int(x) for x in lines if x.isdigit()]
    if len(numbers) < MIN_LINE_NUMBERS:
        return lines
    steps = sum(b == a + 1 for a, b in zip(numbers, numbers[1:], strict=False))
    if steps < LINE_NUMBER_STEP_SHARE * (len(numbers) - 1):
        return lines
    return [x for x in lines if not x.isdigit()]


def strip_repeated_lines(lines: list[str], repeated: set[str]) -> list[str]:
    edges = _edge_indexes(len(lines))
    return [line for i, line in enumerate(lines) if not (i in edges and line_key(line) in repeated)]


def load_pdf(path: Path) -> LoadedDocument:
    with pymupdf.open(path) as doc:
        raw_pages = [page.get_text("text") for page in doc]

    # Work on non-empty lines so blank lines don't push headers out of the top/bottom 3.
    page_lines = [[ln.strip() for ln in text.splitlines() if ln.strip()] for text in raw_pages]
    repeated = find_repeated_lines(page_lines)

    pages: list[PageText] = []
    skipped: list[int] = []
    for number, lines in enumerate(page_lines, start=1):
        kept = strip_line_numbers(strip_repeated_lines(lines, repeated))
        text = normalize_text("\n".join(kept))
        if len(text) < MIN_PAGE_CHARS:
            skipped.append(number)
            continue
        pages.append(PageText(page=number, text=text))

    if skipped:
        log.info("pdf_pages_skipped", file=path.name, pages=skipped, reason="under 100 chars")
    return LoadedDocument(
        path=path, pages=pages, skipped_pages=skipped, removed_lines=sorted(repeated),
    )
