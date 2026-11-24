"""Threshold selection rule (PROJECT_SPEC §8.5)."""

import pytest

from scripts.tune_threshold import choose_threshold


def test_clean_separation_picks_the_middle_of_the_gap():
    choice = choose_threshold(answerable=[2.0, 5.0, 8.0], unanswerable=[-9.0, -7.0])
    assert choice.tau == -2.5  # halfway between best unanswerable (-7) and weakest answerable (2)
    assert (choice.refusal_accuracy, choice.false_refusal_rate) == (1.0, 0.0)
    assert (choice.margin_below, choice.margin_above) == (4.5, 4.5)


def test_tau_sits_in_the_middle_of_the_gap_not_at_an_edge():
    choice = choose_threshold([4.0, 6.0, 10.0], [-8.0, -2.0])
    assert choice.tau == 1.0  # not hugging either edge: 3 points of room on both sides
    assert (choice.margin_below, choice.margin_above) == (3.0, 3.0)


def test_an_unanswerable_question_that_scores_like_an_answerable_one_is_not_chased():
    # one unanswerable question scores 3.0, above the weakest answerable (1.0): refusing it
    # would also refuse an answerable question, which §8.5 forbids (≤ 5 % false refusals)
    choice = choose_threshold(answerable=[1.0, 5.0, 6.0, 7.0, 8.0] * 4, unanswerable=[-6.0, 3.0])
    assert choice.refusal_accuracy == 0.5 and choice.false_refusal_rate == 0.0
    assert choice.tau <= 1.0


def test_one_false_refusal_is_allowed_when_it_is_within_5_percent():
    answerable = [0.5] + [5.0 + i for i in range(20)]  # 1 of 21 = 4.8 %
    choice = choose_threshold(answerable, unanswerable=[2.0, 3.0])
    assert choice.refusal_accuracy == 1.0 and choice.false_refusal_rate == pytest.approx(1 / 21)


def test_needs_both_groups():
    with pytest.raises(ValueError):
        choose_threshold([1.0], [])
    with pytest.raises(ValueError):
        choose_threshold([], [1.0])
