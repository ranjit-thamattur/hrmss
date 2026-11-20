"""Attendance engine: turn raw biometric punches into attendance days.

Pure Python. Rules:
- A night shift that crosses midnight counts on the date it starts.
- Each punch belongs to the work date whose shift window contains it; if two windows overlap,
  the one whose shift start/end is closest wins.
- Punches within DEDUPE_SECONDS of each other are one punch (double taps on the device).
- Odd number of punches = missed punch; it stays open until HR/HOD regularises it.
- What happens to a missed punch still open at the cut-off is the client's rule (policy
  'missed_punch_rule'): present | lop | hold. There is no default: payroll is blocked until it is set.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

DEDUPE_SECONDS = 120
WINDOW_BEFORE = timedelta(hours=4)
WINDOW_AFTER = timedelta(hours=6)
MISSED_PUNCH_RULES = ("present", "lop", "hold")


@dataclass(frozen=True)
class Shift:
    code: str
    start: time
    end: time
    break_minutes: int = 0
    is_off: bool = False  # weekly off marker

    def bounds(self, d: date) -> tuple[datetime, datetime]:
        s = datetime.combine(d, self.start)
        e = datetime.combine(d, self.end)
        if e <= s:  # crosses midnight
            e += timedelta(days=1)
        return s, e

    def scheduled_minutes(self) -> int:
        s, e = self.bounds(date(2000, 1, 1))
        return int((e - s).total_seconds() // 60) - self.break_minutes


@dataclass
class DayResult:
    work_date: date
    shift_code: str
    status: str  # present | absent | missed_punch | leave | holiday | weekly_off
    first_in: datetime | None = None
    last_out: datetime | None = None
    worked_minutes: int = 0
    late_minutes: int = 0
    ot_minutes: int = 0
    punches: list[datetime] = field(default_factory=list)


def dedupe(punches: list[datetime]) -> list[datetime]:
    out: list[datetime] = []
    for p in sorted(punches):
        if out and (p - out[-1]).total_seconds() <= DEDUPE_SECONDS:
            continue
        out.append(p)
    return out


def assign_punches(punches: list[datetime], shifts_by_date: dict[date, Shift]) -> tuple[dict[date, list[datetime]], list[datetime]]:
    """Give each punch to a work date. Returns (punches by date, punches that fit no window)."""
    by_date: dict[date, list[datetime]] = {d: [] for d in shifts_by_date}
    orphans: list[datetime] = []
    for p in dedupe(punches):
        best: tuple[float, date] | None = None
        for d, sh in shifts_by_date.items():
            if sh.is_off:
                s, e = datetime.combine(d, time(0)), datetime.combine(d, time(23, 59, 59))
                lo, hi = s, e
            else:
                s, e = sh.bounds(d)
                lo, hi = s - WINDOW_BEFORE, e + WINDOW_AFTER
            if lo <= p <= hi:
                dist = min(abs((p - s).total_seconds()), abs((p - e).total_seconds()))
                if best is None or dist < best[0]:
                    best = (dist, d)
        if best is None:
            orphans.append(p)
        else:
            by_date[best[1]].append(p)
    return by_date, orphans


def build_day(work_date: date, shift: Shift, punches: list[datetime], *, grace_minutes: int = 10,
              ot_threshold_minutes: int = 30, ot_block_minutes: int = 30, on_leave: bool = False,
              is_holiday: bool = False) -> DayResult:
    ps = dedupe(punches)
    if not ps:
        status = "leave" if on_leave else "holiday" if is_holiday else "weekly_off" if shift.is_off else "absent"
        return DayResult(work_date, shift.code, status)
    if len(ps) % 2 == 1:
        return DayResult(work_date, shift.code, "missed_punch", first_in=ps[0], last_out=ps[-1] if len(ps) > 1 else None, punches=ps)
    worked = sum(int((ps[i + 1] - ps[i]).total_seconds() // 60) for i in range(0, len(ps), 2))
    late = ot = 0
    if not shift.is_off:
        s, _ = shift.bounds(work_date)
        late = max(0, int((ps[0] - s).total_seconds() // 60) - grace_minutes)
        extra = worked - shift.scheduled_minutes()
        if extra >= ot_threshold_minutes:
            ot = (extra // ot_block_minutes) * ot_block_minutes
    else:
        ot = (worked // ot_block_minutes) * ot_block_minutes  # work on a weekly off is all OT
    return DayResult(work_date, shift.code, "present", ps[0], ps[-1], worked, late, ot, ps)


def regularise(day: DayResult, shift: Shift, in_at: datetime, out_at: datetime) -> DayResult:
    """HOD/HR supplies the missing times; the day is rebuilt from them."""
    return build_day(day.work_date, shift, [in_at, out_at])


@dataclass
class MonthSummary:
    days_in_month: int
    present: int
    absent: int
    leave_paid: int
    leave_unpaid: int
    holidays: int
    weekly_off: int
    missed_open: int
    lop_days: Decimal
    paid_days: Decimal
    ot_hours: Decimal
    night_shifts: int
    held_days: int


def summarise_month(days: list[DayResult], days_in_month: int, *, missed_punch_rule: str | None,
                    unpaid_leave_dates: set[date] | None = None, night_shift_codes: tuple[str, ...] = ("N",)) -> MonthSummary:
    """Paid days for payroll. Raises if missed punches are open and the client's rule is not set."""
    unpaid = unpaid_leave_dates or set()
    missed = [d for d in days if d.status == "missed_punch"]
    if missed and missed_punch_rule not in MISSED_PUNCH_RULES:
        raise ValueError(f"{len(missed)} missed punches are open and the missed-punch rule is not set (Company setup).")
    absent = sum(1 for d in days if d.status == "absent")
    leave_unpaid = sum(1 for d in days if d.status == "leave" and d.work_date in unpaid)
    lop = absent + leave_unpaid
    held = 0
    if missed_punch_rule == "lop":
        lop += len(missed)
    elif missed_punch_rule == "hold":
        lop += len(missed)
        held = len(missed)
    present = sum(1 for d in days if d.status == "present")
    if missed_punch_rule == "present":
        present += len(missed)
    ot_minutes = sum(d.ot_minutes for d in days)
    nights = sum(1 for d in days if d.status == "present" and d.shift_code in night_shift_codes)
    lop_d = Decimal(lop)
    return MonthSummary(days_in_month, present, absent, sum(1 for d in days if d.status == "leave") - leave_unpaid, leave_unpaid,
                        sum(1 for d in days if d.status == "holiday"), sum(1 for d in days if d.status == "weekly_off"),
                        len(missed), lop_d, Decimal(days_in_month) - lop_d, (Decimal(ot_minutes) / 60).quantize(Decimal("0.01")), nights, held)


def month_dates(year: int, month: int) -> list[date]:
    d = date(year, month, 1)
    out = []
    while d.month == month:
        out.append(d)
        d += timedelta(days=1)
    return out
