"""Effective dating, pure functions (no database). Rule: history is never overwritten.

A record is a chain of versions. Each version applies from valid_from to valid_to (inclusive; None = open).
Versions of one record never overlap: a change from date D closes the version covering D on D-1 and starts
a new version on D. A change that starts on the same day as the version it hits corrects that version.
"""
from __future__ import annotations

from datetime import date, timedelta

FAR = date(9999, 12, 31)


def end(d: date | None) -> date:
    return d or FAR


def covers(valid_from: date, valid_to: date | None, on: date) -> bool:
    return valid_from <= on <= end(valid_to)


def overlaps(a_from: date, a_to: date | None, b_from: date, b_to: date | None) -> bool:
    return a_from <= end(b_to) and b_from <= end(a_to)


def day_before(d: date) -> date:
    return d - timedelta(days=1)


def status(valid_from: date, valid_to: date | None, is_active: bool, on: date) -> str:
    """active | inactive | scheduled (starts later) | ended (finished before `on`)."""
    if valid_from > on:
        return "scheduled"
    if valid_to is not None and valid_to < on:
        return "ended"
    return "active" if is_active else "inactive"


def plan_change(versions: list[tuple[date, date | None]], effective: date) -> tuple[str, int]:
    """Where a change from `effective` lands in a record's version chain (sorted by valid_from).

    Returns ("correct", i)  -> version i starts on `effective`: correct it in place
            ("split", i)    -> close version i on effective-1 and add a new version from `effective`
    Raises ValueError when `effective` is before the record starts or after it has ended.
    """
    if not versions:
        raise ValueError("The record has no versions")
    if effective < versions[0][0]:
        raise ValueError(f"The change starts on {effective}, before the record starts ({versions[0][0]})")
    for i, (vf, vt) in enumerate(versions):
        if covers(vf, vt, effective):
            return ("correct", i) if vf == effective else ("split", i)
    raise ValueError(f"The record has ended before {effective}; it cannot be changed from that date")


def is_backdated(effective: date, today: date) -> bool:
    """Backdated changes need approval; same-day and future-dated changes do not."""
    return effective < today
