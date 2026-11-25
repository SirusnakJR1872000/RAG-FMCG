"""Section-aware, token-bounded chunking (PROJECT_SPEC §7.3, §7.4, amendment A-02).

- Length is counted with the embedding model's tokenizer, including the special tokens the
  model adds ([CLS], [SEP]), so a chunk of n_tokens ≤ 256 is never truncated by any candidate.
- Every chunk carries a context header "<doc_code> | <section> <title>\\n" that counts too.
- A section that fits becomes one chunk. Adjacent small sections with the same parent heading
  are merged while they fit; the merged chunk's section is a range, e.g. "11.14–11.16" (A-02).
- A longer section is split at sentence boundaries into windows that fit, and each window
  repeats up to 48 tokens of whole sentences from the end of the previous one (overlap).
- A heading with no text of its own ("11.1 General Controls") is not a chunk by itself:
  its line is carried into the next chunk.
"""

import re
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property

from src.ingestion.sections import Section
from src.model_paths import resolve_model

# Sentence end: . ! ? followed by space and a capital, digit, quote or bracket.
# "e.g. the" or "approx. 5" (lowercase / mid-sentence) are not split.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(“\"'•])")
ID_NAMESPACE = uuid.UUID("6f1c2d4e-8a3b-4c5d-9e7f-0a1b2c3d4e5f")  # fixed: stable doc_ids


_MARKER = re.compile(r"^(?:\d{1,2}(?:\.\d{1,2})*|[IVX]{1,4}|[A-H])\.$")  # "1." "11.15." "IV." "C."


def _merge_markers(pieces: list[str]) -> list[str]:
    """Keep a section number with its text: "1." + "SCOPE …" → "1. SCOPE …"."""
    merged: list[str] = []
    for piece in pieces:
        if merged and _MARKER.match(merged[-1]):
            merged[-1] = f"{merged[-1]} {piece}"
        else:
            merged.append(piece)
    return merged


class TokenCounter:
    """Counts tokens with the embedding model's own tokenizer (loaded lazily)."""

    def __init__(self, model_name: str):
        self.model_name = model_name

    @cached_property
    def _tokenizer(self):
        from transformers import AutoTokenizer  # heavy import, only when actually counting

        tokenizer = AutoTokenizer.from_pretrained(resolve_model(self.model_name))
        # We only *count* tokens of long texts before splitting them; never feed them to the
        # model. This silences "sequence length is longer than the maximum" warnings.
        tokenizer.model_max_length = 10**9
        return tokenizer

    def count(self, text: str) -> int:
        """Tokens in the text, without special tokens."""
        return len(self._tokenizer(text, add_special_tokens=False)["input_ids"])

    @cached_property
    def special(self) -> int:
        """Special tokens the model adds to every input ([CLS] + [SEP] = 2 for BERT models)."""
        return self._tokenizer.num_special_tokens_to_add(pair=False)


@dataclass(frozen=True)
class DocInfo:
    doc_code: str
    doc_title: str
    version: str
    version_index: int  # 1 for the first registered version of this doc_code
    doc_sha256: str
    markdown: bool

    @property
    def doc_id(self) -> str:
        return str(uuid.uuid5(ID_NAMESPACE, f"{self.doc_code}|{self.version}"))


@dataclass(frozen=True)
class Unit:
    """A sentence (PDF) or a line (Markdown), with its page."""

    text: str
    page: int | None


@dataclass
class _Group:
    sections: list[Section]
    units: list[Unit]


class Chunker:
    def __init__(self, count: Callable[[str], int], special_tokens: int,
                 max_tokens: int, overlap_tokens: int):
        self.count = count
        self.special = special_tokens
        self.max_tokens = max_tokens
        self.overlap = overlap_tokens

    # ── public ──
    def chunk(self, sections: list[Section], doc: DocInfo) -> list[dict]:
        titles = {s.label: s.title for s in sections if s.is_heading}
        sep = "\n" if doc.markdown else " "
        records: list[dict] = []
        per_label: dict[str, int] = defaultdict(int)  # keeps chunk ids unique per label
        carried: list[Unit] = []  # lines of headings that have no text of their own
        group: _Group | None = None

        def flush(g: _Group | None) -> None:
            if g is None:
                return
            label, title = self._label_and_title(g.sections, titles)
            for window in self._windows(g.units, doc.doc_code, label, title, sep):
                records.append(self._record(doc, label, title, window, sep, per_label))

        for section in sections:
            units = self._units(section, doc.markdown)
            if not section.has_body:
                carried.extend(units)
                continue
            units, carried = carried + units, []
            if group and self._can_merge(group, section, units, doc.doc_code, titles, sep):
                group.sections.append(section)
                group.units.extend(units)
                continue
            flush(group)
            group = _Group([section], units)
        if carried:  # a document that ends with a bare heading
            group = group or _Group([sections[-1]], [])
            group.units.extend(carried)
        flush(group)
        return records

    # ── grouping ──

    def _can_merge(self, group: _Group, section: Section, units: list[Unit], code: str,
                   titles: dict[str, str], sep: str) -> bool:
        first = group.sections[0]
        if section.parent is None or section.parent != first.parent:
            return False
        label, title = self._label_and_title([*group.sections, section], titles)
        return self._fits([*group.units, *units], code, label, title, sep)

    @staticmethod
    def _label_and_title(sections: list[Section], titles: dict[str, str]) -> tuple[str, str]:
        first, last = sections[0], sections[-1]
        if len(sections) == 1:
            return first.label, first.title
        parent_title = titles.get(first.parent or "", "") or first.title
        return f"{first.label}–{last.label}", parent_title

    # ── units and windows ──
    def _units(self, section: Section, markdown: bool) -> list[Unit]:
        if markdown:  # keep Markdown lines (tables, lists); split only over-long lines
            return [Unit(s, x.page) for x in section.lines for s in self._split_long(x.text)]
        units: list[Unit] = []
        by_page: dict[int | None, list[str]] = {}
        for line in section.lines:  # reflow PDF lines into running text, page by page
            by_page.setdefault(line.page, []).append(line.text)
        for page, lines in by_page.items():
            pieces = [s for s in _SENTENCE_END.split(" ".join(lines)) if s.strip()]
            units += [Unit(s, page) for s in _merge_markers(pieces)]
        return units

    def _split_long(self, text: str) -> list[str]:
        if self.count(text) <= self.overlap:
            return [text]
        return [s for s in _SENTENCE_END.split(text) if s.strip()]

    def header(self, code: str, label: str, title: str) -> str:
        return f"{code} | {label} {title}".rstrip() + "\n"

    def n_tokens(self, embed_text: str) -> int:
        return self.count(embed_text) + self.special

    def _fits(self, units: list[Unit], code: str, label: str, title: str, sep: str) -> bool:
        text = self.header(code, label, title) + sep.join(u.text for u in units)
        return self.n_tokens(text) <= self.max_tokens

    def _windows(self, units: list[Unit], code: str, label: str, title: str,
                 sep: str) -> list[list[Unit]]:
        """Pack units into windows that fit; consecutive windows overlap by ≤ overlap tokens."""
        def fits(us: list[Unit]) -> bool:
            return self._fits(us, code, label, title, sep)

        windows: list[list[Unit]] = []
        current: list[Unit] = []
        new_in_current = 0
        for unit in units:
            pieces = [unit] if fits([unit]) else self._split_words(unit, fits)
            for piece in pieces:
                if fits([*current, piece]):
                    current.append(piece)
                    new_in_current += 1
                    continue
                if new_in_current:
                    windows.append(current)
                current = self._overlap_tail(current, sep)
                if not fits([*current, piece]):
                    current = []
                current.append(piece)
                new_in_current = 1
        if current and new_in_current:
            windows.append(current)
        return windows

    def _overlap_tail(self, window: list[Unit], sep: str) -> list[Unit]:
        """Whole sentences from the end of a window, up to `overlap` tokens."""
        tail: list[Unit] = []
        for unit in reversed(window):
            if self.count(sep.join(u.text for u in [unit, *tail])) > self.overlap:
                break
            tail.insert(0, unit)
        return tail

    def _split_words(self, unit: Unit, fits: Callable[[list[Unit]], bool]) -> list[Unit]:
        """Last resort for one sentence longer than a chunk: split between words."""
        pieces: list[Unit] = []
        words: list[str] = []
        for word in unit.text.split():
            if words and not fits([Unit(" ".join([*words, word]), unit.page)]):
                pieces.append(Unit(" ".join(words), unit.page))
                words = []
            words.append(word)
        if words:
            pieces.append(Unit(" ".join(words), unit.page))
        return pieces

    # ── output ──
    def _record(self, doc: DocInfo, label: str, title: str, window: list[Unit], sep: str,
                per_label: dict[str, int]) -> dict:
        text = sep.join(u.text for u in window)
        embed_text = self.header(doc.doc_code, label, title) + text
        pages = [u.page for u in window if u.page is not None]
        index = per_label[label]
        per_label[label] += 1
        return {
            "chunk_id": f"{doc.doc_code}:v{doc.version_index}:{label}:{index:03d}",
            "doc_id": doc.doc_id,
            "doc_code": doc.doc_code,
            "doc_title": doc.doc_title,
            "version": doc.version,
            "doc_sha256": doc.doc_sha256,
            "section": label,
            "section_title": title,
            "page_start": min(pages) if pages else None,
            "page_end": max(pages) if pages else None,
            "text": text,
            "embed_text": embed_text,
            "n_tokens": self.n_tokens(embed_text),
        }
