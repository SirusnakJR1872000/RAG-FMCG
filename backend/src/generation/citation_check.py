"""Citation check (PROJECT_SPEC §9.4).

- every [n] must satisfy 1 ≤ n ≤ number of sources, else `invalid_citation`;
- a non-refusal answer with no citation at all is `uncited_answer`.

Models sometimes write "[1, 2]" or "[1-3]" instead of "[1][2]"; those are read as the
numbers they list. Only the *validity* of the markers is checked here: whether a sentence is
really supported by its source is the job of the faithfulness evaluation (§11.2).
"""

import re
from dataclasses import dataclass, field

# [3]   [1, 2]   [1-3]   [1–3]
_MARKER = re.compile(r"\[\s*(\d+(?:\s*(?:[,;]|[-–])\s*\d+)*)\s*\]")
_RANGE_LIMIT = 20  # [1-999999] must not hang the check


@dataclass(frozen=True)
class CitationCheck:
    status: str  # "ok" | "invalid_citation" | "uncited_answer"
    cited: list[int] = field(default_factory=list)  # distinct valid numbers, ascending
    invalid: list[int] = field(default_factory=list)  # distinct out-of-range numbers
    uncited: bool = False

    def as_dict(self) -> dict:
        """The shape of `citation_check` in §16."""
        return {"status": self.status, "invalid": self.invalid, "uncited": self.uncited}


def parse_citations(text: str) -> list[int]:
    """All citation numbers in the text, in order of appearance (with repeats)."""
    numbers: list[int] = []
    for match in _MARKER.finditer(text):
        body = match.group(1)
        if re.search(r"\d\s*[-–]\s*\d", body):  # a range such as 1-3
            start, end = (int(x) for x in re.split(r"\s*[-–]\s*", body, maxsplit=1))
            numbers.extend(range(start, min(end, start + _RANGE_LIMIT) + 1))
        else:
            numbers.extend(int(x) for x in re.split(r"\s*[,;]\s*", body))
    return numbers


def check_citations(answer: str, n_sources: int) -> CitationCheck:
    numbers = parse_citations(answer)
    if not numbers:
        return CitationCheck(status="uncited_answer", uncited=True)
    invalid = sorted({n for n in numbers if not 1 <= n <= n_sources})
    cited = sorted({n for n in numbers if 1 <= n <= n_sources})
    return CitationCheck(status="invalid_citation" if invalid else "ok",
                         cited=cited, invalid=invalid)
