"""Full and final settlement (pure). Sample rules; confirm with the client's consultant."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from .payroll_engine import ZERO, rupee

D = Decimal


def add_working_days(start: date, n: int, holidays: set[date] | None = None, weekly_off: int = 6) -> date:
    """n working days after start; weekly_off is the weekday number (Mon=0 … Sun=6)."""
    hol = holidays or set()
    d = start
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() != weekly_off and d not in hol:
            n -= 1
    return d


def service_years(doj: date, lwd: date) -> tuple[int, int]:
    """Completed years and remaining months."""
    months = (lwd.year - doj.year) * 12 + (lwd.month - doj.month) - (1 if lwd.day < doj.day else 0)
    return months // 12, months % 12


def last_working_day(resigned_on: date, notice_days: int) -> date:
    return resigned_on + timedelta(days=notice_days - 1)


@dataclass
class FnfInput:
    monthly_gross: Decimal
    monthly_basic: Decimal
    doj: date
    resigned_on: date
    last_working_day: date
    notice_days: int
    days_in_month: int
    days_worked_in_last_month: int
    el_balance_days: Decimal = ZERO
    loan_balance: Decimal = ZERO
    advance_balance: Decimal = ZERO
    other_earnings: dict[str, Decimal] = field(default_factory=dict)
    other_deductions: dict[str, Decimal] = field(default_factory=dict)
    notice_waived: bool = False
    gratuity_min_years: int = 5


@dataclass
class FnfResult:
    earnings: dict[str, Decimal]
    deductions: dict[str, Decimal]
    net: Decimal
    gratuity_eligible: bool
    service: str
    due_on: date

    def as_dict(self) -> dict:
        return {"earnings": {k: str(v) for k, v in self.earnings.items()}, "deductions": {k: str(v) for k, v in self.deductions.items()},
                "net": str(self.net), "gratuity_eligible": self.gratuity_eligible, "service": self.service, "due_on": self.due_on.isoformat()}


def calculate_fnf(i: FnfInput, holidays: set[date] | None = None) -> FnfResult:
    e: dict[str, Decimal] = {}
    d: dict[str, Decimal] = {}
    e["SALARY_TO_LWD"] = rupee(i.monthly_gross * D(i.days_worked_in_last_month) / D(i.days_in_month))
    if i.el_balance_days:
        e["LEAVE_ENCASHMENT"] = rupee(i.monthly_basic / D(26) * D(str(i.el_balance_days)))
    years, months = service_years(i.doj, i.last_working_day)
    counted = years + (1 if months >= 6 else 0)
    eligible = years >= i.gratuity_min_years
    if eligible:
        e["GRATUITY"] = rupee(i.monthly_basic * D(15) / D(26) * D(counted))
    e.update({k: rupee(v) for k, v in i.other_earnings.items() if v})
    served = (i.last_working_day - i.resigned_on).days + 1
    shortfall = max(0, i.notice_days - served)
    if shortfall and not i.notice_waived:
        d["NOTICE_SHORTFALL"] = rupee(i.monthly_gross / D(30) * D(shortfall))
    if i.loan_balance:
        d["LOAN_BALANCE"] = rupee(i.loan_balance)
    if i.advance_balance:
        d["ADVANCE_BALANCE"] = rupee(i.advance_balance)
    d.update({k: rupee(v) for k, v in i.other_deductions.items() if v})
    net = sum(e.values(), ZERO) - sum(d.values(), ZERO)
    return FnfResult(e, d, net, eligible, f"{years} years {months} months", add_working_days(i.last_working_day, 2, holidays))
