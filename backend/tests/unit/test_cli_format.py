"""CLI output formatting (the chat loop itself is exercised by the real-model run)."""

from cli import format_footer, format_source
from src.generation.citation_check import CitationCheck
from src.generation.pipeline import Result, SourceInfo


def src(n=1, page=29, fictional=False):
    return SourceInfo(n, f"c{n}", "ICH-Q7" if not fictional else "ACME-SOP-QC-007", "t", "v",
                      "11.15", "General Controls", page, page, "text", fictional, "ab", 4.25)


def result(answer_type="answered", check=None, truncated=False, top=4.25, sources=None):
    return Result(answer_type, "answer", "q", sources if sources is not None else [src()], check,
                  top, {"rewrite": 0, "retrieval": 20, "rerank": 800, "ttft": 9000,
                        "generation": 20000, "total": 30000}, truncated=truncated)


def test_source_line_shows_page_or_sop_and_the_fictional_tag():
    assert format_source(src()) == "  [1] ICH-Q7 §11.15 General Controls · v · p. 29  (score 4.2)"
    line = format_source(src(2, page=None, fictional=True))
    assert "SOP" in line and "[Fictional]" in line


def test_answered_footer_lists_sources_and_the_verify_notice():
    lines = format_footer(result(check=CitationCheck("ok", [1])))
    assert "Sources:" in lines and lines[-2] == "Verify against the cited source before acting."
    assert lines[-1].startswith("[answered ·") and "total 30000 ms" in lines[-1]


def test_invalid_and_uncited_answers_show_a_visible_warning():
    bad = format_footer(result(check=CitationCheck("invalid_citation", [1], [7])))
    assert any("couldn't be verified" in ln and "[7]" in ln for ln in bad)
    none = format_footer(result(check=CitationCheck("uncited_answer", uncited=True)))
    assert any("no citations" in ln for ln in none)


def test_truncated_answer_is_flagged():
    assert any("cut off" in ln for ln in format_footer(
        result(check=CitationCheck("ok", [1]), truncated=True)))


def test_refusals_have_no_sources_and_no_verify_notice():
    for kind in ("retrieval_refusal", "model_refusal"):
        lines = format_footer(result(kind, sources=[]))
        assert "Sources:" not in lines
        assert "Verify against the cited source before acting." not in lines
    assert any("below the threshold" in ln for ln in format_footer(result("retrieval_refusal")))


def test_sources_the_answer_actually_cites_are_marked():
    lines = format_footer(result(sources=[src(1), src(2)], check=CitationCheck("ok", [2])))
    marked = [ln for ln in lines if "← cited" in ln]
    assert len(marked) == 1 and marked[0].startswith("  [2]")
