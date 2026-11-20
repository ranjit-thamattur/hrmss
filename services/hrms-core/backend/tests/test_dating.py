from datetime import date

import pytest

from app.core.dating import is_backdated, overlaps, plan_change, status

D = date


def test_same_day_change_corrects_the_version():
    assert plan_change([(D(2026, 1, 1), None)], D(2026, 1, 1)) == ("correct", 0)


def test_later_change_splits_the_version():
    assert plan_change([(D(2026, 1, 1), D(2026, 5, 31)), (D(2026, 6, 1), None)], D(2026, 7, 1)) == ("split", 1)


def test_change_before_start_or_after_end_is_refused():
    with pytest.raises(ValueError):
        plan_change([(D(2026, 1, 1), None)], D(2025, 12, 31))
    with pytest.raises(ValueError):
        plan_change([(D(2026, 1, 1), D(2026, 3, 31))], D(2026, 4, 1))


def test_overlaps_with_open_end():
    assert overlaps(D(2026, 1, 1), None, D(2030, 1, 1), D(2030, 2, 1))
    assert not overlaps(D(2026, 1, 1), D(2026, 1, 31), D(2026, 2, 1), None)


def test_status_and_backdating():
    t = D(2026, 11, 20)
    assert status(D(2026, 12, 1), None, True, t) == "scheduled"
    assert status(D(2026, 1, 1), D(2026, 10, 31), True, t) == "ended"
    assert status(D(2026, 1, 1), None, False, t) == "inactive"
    assert is_backdated(D(2026, 11, 19), t) and not is_backdated(t, t)
