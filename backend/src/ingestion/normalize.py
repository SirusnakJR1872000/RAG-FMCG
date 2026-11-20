"""Shared output shape and text normalisation for the loaders (PROJECT_SPEC §7.1)."""

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class PageText:
    """Text of one PDF page, or the whole Markdown file (page=None)."""

    page: int | None
    text: str


@dataclass(frozen=True)
class LoadedDocument:
    """What every loader returns, so the chunker doesn't care about the file type."""

    path: Path
    pages: list[PageText]
    skipped_pages: list[int] = field(default_factory=list)  # PDF pages with too little text
    removed_lines: list[str] = field(default_factory=list)  # header/footer patterns stripped


# A word broken across a line end: "manufac-\nturing". Only rejoined when the next line starts
# with a lowercase letter, so "ICH-\nQ7" or a list item starting "- Item" is left alone.
_HYPHEN_BREAK = re.compile(r"(\w)-\n(?=[a-z])")
_SPACES = re.compile(r"[ \t\f\v ]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    """NFKC, rejoin hyphenated line breaks, collapse whitespace; keep line structure.

    Line breaks are kept because section headings are detected at the start of a line (§7.2).
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _HYPHEN_BREAK.sub(r"\1", text)
    lines = [_SPACES.sub(" ", line).strip() for line in text.split("\n")]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()
