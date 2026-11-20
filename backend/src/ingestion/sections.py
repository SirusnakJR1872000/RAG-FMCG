"""Section detection (PROJECT_SPEC §7.2, amendment A-01).

Turns a loaded document into an ordered list of sections. A section is one numbered heading
or numbered paragraph plus the lines that follow it, each line keeping its page number.

Rules, in plain words:
- Candidates are numbered lines: `1.`, `8.1`, `8.1.2`, `IV.`, `C.` (only inside a Roman
  section), `I.1`, `Annex 2`, `Article 5`, `§ 11.10`, and Markdown `#` headings.
- A candidate is a *heading* if its text reads like a title (Title Case, ALL CAPS, or a short
  phrase without end punctuation), otherwise a *numbered paragraph* (ICH Q7 "11.15 Any
  out-of-specification result…"). Paragraphs inherit the title of their heading.
- A marker alone on its line (`IV.`, `2.10`) is decided by the next line: a title-like line
  is its title, a sentence means the marker numbers a paragraph.
- If the line after a heading starts in lowercase, the "heading" was really the first line of
  a wrapped sentence ("5.41 Appropriate" / "controls should…"), so it is demoted.
- Guards against false headings:
  * a single number needs a dot (`8.`), so footnotes like "3 In this guidance" are ignored;
  * text after the number must not start in lowercase ("2.5 times higher");
  * top-level numbers only move forward by 1–2 and must read like headings, in the same
    case style as the document's first chapter (ALL CAPS in ICH), so numbered lists and
    reference lists can't walk through the chapter numbers;
  * table-of-contents pages are dropped (A-01).
"""

import re
from dataclasses import dataclass, field

from src.ingestion.normalize import LoadedDocument

FRONT_MATTER = "0"
MAX_TOP_LEVEL_JUMP = 2  # 8 → 9 or 10 is plausible; 8 → 12 is a stray number in the text
SHORT_HEADING_WORDS = 6  # "Periodic evaluation" is a heading even in sentence case
TOC_MIN_LINES = 4  # this many TOC-style lines make a page a table of contents
TOC_BARE_NUMBER_SHARE = 0.25  # or: this share of lines are bare page numbers (WHO style)

_ARABIC = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})(\.?)(?:\s+(.*))?$")
_ROMAN = re.compile(r"^([IVX]{1,4})\.(?:\s+(.*))?$")
_ROMAN_NUM = re.compile(r"^([IVX]{1,4})\.(\d{1,2})\.?(?:\s+(.*))?$")
_LETTER = re.compile(r"^([A-H])\.(?:\s+(.*))?$")
_NAMED = re.compile(r"^((?:Annex|Article)\s+\d+)\b[.:]?\s*(.*)$")
_SECTION_SIGN = re.compile(r"^§\s*(\d+(?:\.\d+)*)\s+(.*)$")
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_DOT_LEADER = re.compile(r"(?:\.\s?){5,}\s*\S*\s*$|…{2,}")
_TOC_ENTRY = re.compile(  # "9. Personnel 99" — a TOC line ending in a page number
    r"^(?:\d{1,2}(?:\.\d{1,2})*\.?|[IVX]{1,4}\.|[A-H]\.)?\s*[A-Z][^.]{2,80}\s\d{1,3}$"
)
_FOOTNOTE_MARK = re.compile(r"(?<=[a-z])\d{1,2}$")  # footnote number glued to a title
_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10}


@dataclass
class Line:
    page: int | None
    text: str


@dataclass
class Section:
    label: str  # "11.15", "IV.C.2", "I.1", "0" for front matter
    title: str  # own title for headings; inherited from the parent heading for paragraphs
    parent: str | None  # label of the enclosing heading
    is_heading: bool
    lines: list[Line] = field(default_factory=list)
    heading_lines: int = 1  # lines used by the heading itself (marker + title, wrapped title)

    @property
    def has_body(self) -> bool:
        """False for a heading with no text of its own ("11.1 General Controls")."""
        return not self.is_heading or self.label == FRONT_MATTER or (
            len(self.lines) > self.heading_lines
        )


# ── text tests ───────────────────────────────────────────────────────────────────────────

def roman_to_int(numeral: str) -> int:
    total = 0
    for i, ch in enumerate(numeral):
        value = _ROMAN_VALUES[ch]
        nxt = _ROMAN_VALUES[numeral[i + 1]] if i + 1 < len(numeral) else 0
        total += -value if value < nxt else value
    return total


def looks_like_title(text: str) -> bool:
    """Title Case or ALL CAPS: most words longer than 3 letters start with a capital."""
    if text.rstrip().endswith(".") and len(text.split()) > 3:
        return False  # a full sentence; headings don't end with a period
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z'’\-]*", text) if len(w) > 3]
    if not words:
        return bool(text) and text[0].isupper()
    if text.isupper():
        return True
    return sum(w[0].isupper() for w in words) / len(words) >= 0.6


def looks_like_heading(text: str) -> bool:
    """Title-like, or a short phrase without end punctuation ("Periodic evaluation")."""
    text = text.strip()
    if not text:
        return False
    short = len(text.split()) <= SHORT_HEADING_WORDS and text[-1] not in ".,;:"
    return looks_like_title(text) or short


def _is_title_continuation(text: str) -> bool:
    """A short lowercase line with no end punctuation finishes a wrapped heading."""
    text = text.strip()
    return len(text.split()) <= SHORT_HEADING_WORDS and text[-1:] not in ".,;:"


def _starts_ok(rest: str | None) -> bool:
    """Text after a section number: empty (title on next line) or not lowercase."""
    return not rest or rest[0].isupper() or rest[0] in "(“\"'"


def is_toc_page(lines: list[str]) -> bool:
    """Dot-leader lines (ICH, FDA) or many bare page-number lines (WHO)."""
    toc_lines = sum(bool(_DOT_LEADER.search(x) or _TOC_ENTRY.match(x)) for x in lines)
    bare_numbers = sum(x.strip().isdigit() for x in lines)
    return toc_lines >= TOC_MIN_LINES or (
        bare_numbers >= TOC_MIN_LINES and bare_numbers >= TOC_BARE_NUMBER_SHARE * len(lines)
    )


# ── parser ───────────────────────────────────────────────────────────────────────────────

@dataclass
class _Open:
    """A heading whose status depends on the next line."""

    section: Section
    previous_top: int | None
    marker_only: bool  # True: 'IV.' alone; False: has a title that may be a wrapped sentence


class _Parser:
    def __init__(self, markdown: bool):
        self.markdown = markdown
        self.sections: list[Section] = [Section(FRONT_MATTER, "Front matter", None, True)]
        self.top: int | None = None  # current top-level Arabic number
        self.roman: str | None = None  # current Roman section, e.g. "IV"
        self.letter: str | None = None  # current letter inside it, e.g. "C"
        self.headings: dict[str, str] = {}  # label → title of every confirmed heading
        self.caps_top: bool | None = None  # are top-level headings ALL CAPS in this document?
        self.open: _Open | None = None

    # ── entry point ──
    def feed(self, line: Line) -> None:
        if self.open and self._resolve_open(line):
            return
        md = _MD_HEADING.match(line.text) if self.markdown else None
        text = md.group(2).strip() if md else line.text
        previous_top = self.top

        section = self._arabic(text, bool(md))
        if section is None and not self.markdown:
            section = self._roman(text)
        if section is None:
            section = self._named(text)

        if section is None:
            if md and len(md.group(1)) == 1 and self.sections[-1].label == FRONT_MATTER:
                self.sections[-1].title = text  # SOP H1: "# SOP-QC-007 Title"
            self.sections[-1].lines.append(line)
            return

        section.lines.append(line)
        self.sections.append(section)
        if section.is_heading and section.title:
            self._confirm(section)
        if section.is_heading and not md:
            self.open = _Open(section, previous_top, marker_only=not section.title)

    # ── candidates ──
    def _arabic(self, text: str, is_md: bool) -> Section | None:
        m = _ARABIC.match(text)
        if not m:
            return None
        number, dot, rest = m.group(1), m.group(2), m.group(3)
        parts = number.split(".")
        if (len(parts) == 1 and not dot) or not _starts_ok(rest):
            return None  # "3 In this guidance" is a footnote; "2.5 times" is a sentence

        if self.roman:  # FDA style: "2." inside IV.C → IV.C.2
            if len(parts) != 1:
                return None
            prefix = f"{self.roman}.{self.letter}" if self.letter else self.roman
            return self._new(f"{prefix}.{parts[0]}", rest, prefix, heading_hint=is_md)

        top = int(parts[0])
        highest = (self.top or 0) + MAX_TOP_LEVEL_JUMP
        if len(parts) == 1:
            lowest = 1 if self.top is None else self.top + 1  # chapters only move forward
            if not lowest <= top <= highest:
                return None
            if rest and not is_md and not self._chapter_title_ok(rest):
                return None
        elif not (self.top or 1) <= top <= highest:
            return None
        self.top = top
        parent, q7_paragraph = self._arabic_parent(number)
        if q7_paragraph:  # ICH Q7: 5.41 under heading 5.4 is always a numbered paragraph
            return Section(number, self._inherited_title(parent), parent, False)
        return self._new(number, rest, parent, heading_hint=is_md)

    def _roman(self, text: str) -> Section | None:
        if m := _ROMAN_NUM.match(text):  # "I.1" — ICH Q9(R1) annex sections
            if not _starts_ok(m.group(3)):
                return None
            self.roman = self.letter = None
            return self._new(f"{m.group(1)}.{m.group(2)}", m.group(3), None, heading_hint=True)
        if m := _ROMAN.match(text):
            value = roman_to_int(m.group(1))
            current = roman_to_int(self.roman) if self.roman else 0
            if not current < value <= current + MAX_TOP_LEVEL_JUMP or not _starts_ok(m.group(2)):
                return None
            self.roman, self.letter = m.group(1), None
            return self._new(m.group(1), m.group(2), None, heading_hint=True)
        if self.roman and (m := _LETTER.match(text)):
            if not _starts_ok(m.group(2)):
                return None
            self.letter = m.group(1)
            return self._new(f"{self.roman}.{m.group(1)}", m.group(2), self.roman,
                             heading_hint=True)
        return None

    def _named(self, text: str) -> Section | None:
        if m := _NAMED.match(text):
            return self._new(m.group(1), m.group(2), None, heading_hint=True)
        if m := _SECTION_SIGN.match(text):
            return self._new(m.group(1), m.group(2), None, heading_hint=False)
        return None

    # ── helpers ──
    def _new(self, label: str, rest: str | None, parent: str | None, heading_hint: bool) -> Section:
        rest = (rest or "").strip()
        if not rest:  # marker alone: provisional heading, decided by the next line
            return Section(label, "", parent, True)
        if heading_hint or looks_like_heading(rest):
            return Section(label, rest, parent, True)
        return Section(label, self._inherited_title(parent), parent, False)

    def _chapter_title_ok(self, text: str) -> bool:
        if not looks_like_heading(text):
            return False
        return not (self.caps_top and not text.isupper())

    def _confirm(self, section: Section) -> None:
        section.title = _FOOTNOTE_MARK.sub("", section.title)  # "Legacy Systems7"
        self.headings[section.label] = section.title
        if "." not in section.label and not self.roman and self.caps_top is None:
            self.caps_top = section.title.isupper()

    def _arabic_parent(self, number: str) -> tuple[str | None, bool]:
        """Nearest heading above this number, and whether it is an ICH Q7-style paragraph.

        ICH Q7 numbers paragraphs by appending a digit to their heading: 8.31 sits under
        heading 8.3 (not under 8). WHO's 1.10 has no heading "1.1", so it stays under 1.
        """
        parts = number.split(".")
        if len(parts) >= 2 and len(parts[-1]) == 2:
            q7_parent = ".".join([*parts[:-1], parts[-1][0]])
            if q7_parent in self.headings:
                return q7_parent, True
        for i in range(len(parts) - 1, 0, -1):
            if (candidate := ".".join(parts[:i])) in self.headings:
                return candidate, False
        return None, False

    def _inherited_title(self, parent: str | None) -> str:
        while parent:
            if title := self.headings.get(parent):
                return title
            parent = parent.rsplit(".", 1)[0] if "." in parent else None
        return ""

    def _resolve_open(self, line: Line) -> bool:
        """Decide the open heading using this line. True if the line was consumed here."""
        opened, self.open = self.open, None
        section = opened.section
        chapter = "." not in section.label and section.label.isdigit()

        if opened.marker_only:
            check = self._chapter_title_ok if chapter else looks_like_heading
            if check(line.text):  # 'IV.' + 'RECOMMENDATIONS'
                section.title = line.text.strip()
                section.lines.append(line)
                section.heading_lines += 1
                self._confirm(section)
                # the title itself may wrap, or be the first word of a sentence ('Appropriate')
                self.open = _Open(section, opened.previous_top, marker_only=False)
                return True
            if chapter:  # '7.' + 'Making sure that…' is a list item, not chapter 7
                self._undo(section, opened.previous_top, line)
                return True
            self._demote(section)  # '2.10' + 'Quality should be…' numbers a paragraph
            section.lines.append(line)
            return True

        if line.text[:1].islower():
            if _is_title_continuation(line.text):  # '8. Self-inspection, quality audits and'
                section.title = f"{section.title} {line.text.strip()}"  # + 'suppliers’ audits…'
                section.lines.append(line)
                section.heading_lines += 1
                self._confirm(section)
                return True
            if chapter:  # '5.41 Appropriate' + 'installation qualification and…' (a sentence)
                self._undo(section, opened.previous_top, line)
                return True
            self._demote(section)
        return False

    def _demote(self, section: Section) -> None:
        if self.headings.get(section.label) == section.title:
            del self.headings[section.label]
        section.is_heading = False
        section.title = self._inherited_title(section.parent)

    def _undo(self, section: Section, previous_top: int | None, line: Line) -> None:
        """Not a section after all: give its lines back to the previous section."""
        self._demote(section)
        self.sections.pop()
        self.top = previous_top
        self.sections[-1].lines.extend([*section.lines, line])


def detect_sections(doc: LoadedDocument, markdown: bool) -> list[Section]:
    """Split a loaded document into sections, in reading order. TOC pages are dropped."""
    parser = _Parser(markdown)
    for page in doc.pages:
        lines = [x for x in page.text.splitlines() if x.strip()]
        if not markdown and is_toc_page(lines):
            continue
        for text in lines:
            parser.feed(Line(page.page, text))
    return [s for s in parser.sections if s.lines]
