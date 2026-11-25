"""The D-12 adoption rule (PROJECT_SPEC §10.4)."""

import pytest

from scripts.finetune_report import decide, rank_changes


def m(hit5, mrr):
    return {"hit@5": hit5, "mrr@10": mrr}


def test_a_two_point_hit5_gain_adopts():
    assert decide(m(0.80, 0.70), m(0.82, 0.70)).adopt


def test_a_002_mrr_gain_adopts():
    assert decide(m(0.80, 0.70), m(0.80, 0.72)).adopt


def test_one_extra_question_on_the_real_dev_set_counts_as_two_points():
    # 17/18 → 18/18: +5.6 points
    assert decide(m(17 / 18, 0.95), m(1.0, 0.95)).adopt


def test_a_gain_below_the_bar_does_not_adopt():
    d = decide(m(0.80, 0.70), m(0.81, 0.71))
    assert not d.adopt and "no sufficient improvement" in d.reasons[0]


def test_a_gain_in_one_metric_is_cancelled_by_a_drop_over_one_point_in_the_other():
    assert not decide(m(0.80, 0.70), m(0.90, 0.68)).adopt  # MRR fell 0.02
    assert not decide(m(0.80, 0.70), m(0.78, 0.75)).adopt  # Hit@5 fell 2 points


def test_a_drop_of_exactly_one_point_is_allowed():
    assert decide(m(0.80, 0.70), m(0.79, 0.73)).adopt


def test_float_noise_does_not_flip_the_decision():
    # 0.9444 + 0.02 computed in floating point may land a hair below 0.02
    assert decide(m(0.9444444, 0.9), m(0.9644444, 0.9)).adopt
    assert decide(m(1 / 3, 0.5), m(1 / 3 + 0.02, 0.5)).adopt


def test_no_change_does_not_adopt_and_reports_the_deltas():
    d = decide(m(0.94, 0.95), m(0.94, 0.95))
    assert not d.adopt and (d.delta_hit5, d.delta_mrr) == (0.0, 0.0)
    assert d.reasons[1].endswith("true")


def test_rank_changes_lists_only_questions_that_moved():
    base = [{"id": "G-001", "question": "q1", "first_hit_rank": 3},
            {"id": "G-002", "question": "q2", "first_hit_rank": 1},
            {"id": "G-003", "question": "q3", "first_hit_rank": None}]
    tuned = [{"id": "G-001", "question": "q1", "first_hit_rank": 1},
             {"id": "G-002", "question": "q2", "first_hit_rank": 1},
             {"id": "G-003", "question": "q3", "first_hit_rank": 8}]
    lines = rank_changes(base, tuned)
    assert lines == ["- G-001 q1: rank 3 → rank 1", "- G-003 q3: not in top 10 → rank 8"]
    assert rank_changes(base, base) == ["- no question changed rank"]


@pytest.mark.parametrize("hit5", [0.0, 0.5, 1.0])
def test_equal_metrics_never_adopt(hit5):
    assert not decide(m(hit5, 0.5), m(hit5, 0.5)).adopt
