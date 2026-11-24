"""Citation check (PROJECT_SPEC §9.4)."""

import pytest

from src.generation.citation_check import check_citations, parse_citations


def test_valid_citations_pass():
    result = check_citations("OOS results must be investigated [1]. A CAPA follows [2].", 4)
    assert (result.status, result.cited) == ("ok", [1, 2])
    assert (result.invalid, result.uncited) == ([], False)
    assert result.as_dict() == {"status": "ok", "invalid": [], "uncited": False}


@pytest.mark.parametrize("text", ["It is required [5].", "It is required [0].", "See [1] and [9]."])
def test_numbers_outside_1_to_n_are_invalid(text):
    result = check_citations(text, 4)
    assert result.status == "invalid_citation" and result.invalid and not result.uncited


def test_answer_without_citations_is_uncited():
    result = check_citations("Investigations must be documented.", 4)
    assert (result.status, result.uncited, result.cited) == ("uncited_answer", True, [])


def test_valid_and_invalid_together_report_the_invalid_ones():
    result = check_citations("A [1] B [7] C [7] D [2]", 4)
    assert (result.status, result.cited, result.invalid) == ("invalid_citation", [1, 2], [7])


@pytest.mark.parametrize(("text", "numbers"), [
    ("see [1, 2]", [1, 2]), ("see [1,2,3]", [1, 2, 3]), ("see [1-3]", [1, 2, 3]),
    ("see [2–4]", [2, 3, 4]), ("[1][2]", [1, 2]), ("[ 3 ]", [3]), ("a [1]; b [1]", [1, 1]),
])
def test_marker_forms(text, numbers):
    assert parse_citations(text) == numbers


def test_range_markers_cannot_hang_the_check():
    assert len(parse_citations("[1-9999999999]")) <= 21


@pytest.mark.parametrize("text", ["array[i]", "no brackets", "[abc]", "[]", "(1)"])
def test_non_citations_are_ignored(text):
    assert parse_citations(text) == []
