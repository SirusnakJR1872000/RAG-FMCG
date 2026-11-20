"""Golden evaluation set: schema, composition rules and the hit rule (PROJECT_SPEC §11.1).

Hit rule (§11.1): a retrieved chunk is a hit when its doc_code matches and its section
equals, or is a subsection of, an expected section. "Subsection" follows each document's
real section tree from `detect_sections`, not string prefixes:
- ICH Q7 paragraph 11.15 sits under heading 11.1, although "11.15" doesn't start with "11.1.";
- WHO paragraph 1.10 is NOT under 1.1, although "1.10" starts with "1.1".
A merged chunk (A-02, e.g. "11.14–11.16") counts as each section in its range.
"""

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.ingestion.sections import Section

RANGE_SEP = "–"  # en dash, as written by the chunker (A-02)

# §11.1 composition
TOTAL = 50
PER_CATEGORY = {"public": 30, "sop": 15, "unanswerable": 5}
PER_SPLIT = {"dev": 20, "test": 30}


class Expected(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_code: str = Field(min_length=1)
    section: str = Field(min_length=1)


class GoldenItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^G-\d{3}$")
    split: Literal["dev", "test"]
    answerable: bool
    question: str = Field(min_length=10, max_length=1000)
    expected: list[Expected]
    key_facts: list[str]

    @model_validator(mode="after")
    def _consistent(self) -> "GoldenItem":
        if self.answerable and not (self.expected and self.key_facts):
            raise ValueError(f"{self.id}: answerable questions need expected and key_facts")
        if not self.answerable and (self.expected or self.key_facts):
            raise ValueError(f"{self.id}: unanswerable questions have no expected/key_facts")
        return self

    @property
    def category(self) -> Literal["public", "sop", "unanswerable"]:
        if not self.answerable:
            return "unanswerable"
        return "sop" if any(e.doc_code.startswith("ACME-") for e in self.expected) else "public"


def load_golden(path: Path) -> list[GoldenItem]:
    items = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                items.append(GoldenItem.model_validate(json.loads(line)))
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"{path.name} line {n}: {exc}") from exc
    return items


def composition_problems(items: list[GoldenItem]) -> list[str]:
    """Everything that breaks the §11.1 composition rules (empty list = OK)."""
    problems = []
    if len(items) != TOTAL:
        problems.append(f"{len(items)} questions, expected {TOTAL}")
    for name, counts, wanted in (
        ("category", Counter(i.category for i in items), PER_CATEGORY),
        ("split", Counter(i.split for i in items), PER_SPLIT),
    ):
        for key, n in wanted.items():
            if counts[key] != n:
                problems.append(f"{name} {key}: {counts[key]}, expected {n}")
    for kind, values in (("id", [i.id for i in items]),
                         ("question", [i.question.lower() for i in items])):
        dupes = [v for v, n in Counter(values).items() if n > 1]
        if dupes:
            problems.append(f"duplicate {kind}: {dupes}")
    for split in PER_SPLIT:  # every split must be able to measure every metric
        cats = {i.category for i in items if i.split == split}
        missing = set(PER_CATEGORY) - cats
        if missing:
            problems.append(f"split {split} has no {sorted(missing)} questions")
    return problems


@dataclass
class SectionTree:
    """The section hierarchy of one document, in reading order."""

    order: list[str] = field(default_factory=list)
    parent: dict[str, str | None] = field(default_factory=dict)

    @classmethod
    def from_sections(cls, sections: list[Section]) -> "SectionTree":
        tree = cls()
        for s in sections:
            tree.order.append(s.label)
            tree.parent.setdefault(s.label, s.parent)
        return tree

    def __contains__(self, label: str) -> bool:
        return label in self.parent

    def members(self, label: str) -> list[str]:
        """'11.14–11.16' → ['11.14', '11.15', '11.16'] (document order); others → [label]."""
        if RANGE_SEP not in label:
            return [label]
        first, last = label.split(RANGE_SEP)
        if first not in self.parent or last not in self.parent:
            return [first, last]
        start = self.order.index(first)
        end = self.order.index(last, start)
        return self.order[start:end + 1]

    def ancestors(self, label: str) -> list[str]:
        chain, seen = [], set()
        parent = self.parent.get(label)
        while parent and parent not in seen:
            chain.append(parent)
            seen.add(parent)
            parent = self.parent.get(parent)
        return chain

    def covers(self, chunk_section: str, expected_section: str) -> bool:
        """True if the chunk's section equals or is a subsection of the expected section."""
        return any(
            expected_section == m or expected_section in self.ancestors(m)
            for m in self.members(chunk_section)
        )


def is_hit(trees: dict[str, SectionTree], doc_code: str, chunk_section: str,
           expected: list[Expected]) -> bool:
    tree = trees.get(doc_code)
    return tree is not None and any(
        e.doc_code == doc_code and tree.covers(chunk_section, e.section) for e in expected
    )


def load_section_trees(settings) -> dict[str, SectionTree]:
    """Section tree of every active manifest document, parsed from the corpus files."""
    from src.ingestion.manifest import load_manifest
    from src.ingestion.md_loader import load_markdown
    from src.ingestion.pdf_loader import load_pdf
    from src.ingestion.sections import detect_sections

    trees = {}
    for e in load_manifest(settings.manifest_path):
        if e.status != "active":
            continue
        path = settings.corpus_dir / e.file
        markdown = path.suffix == ".md"
        loaded = load_markdown(path) if markdown else load_pdf(path)
        trees[e.doc_code] = SectionTree.from_sections(detect_sections(loaded, markdown))
    return trees
