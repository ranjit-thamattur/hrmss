"""Dated settings. A value takes effect from its date; old versions are kept."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..domain.payroll_engine import DEFAULT_RULES

# Starting values. Each is a sample until Hotel Vivek confirms it (open decisions list, SCRUM-122).
POLICY_DEFAULTS: dict[str, Any] = {
    "payroll_day": 26,
    "attendance_cutoff_day": 25,
    "missed_punch_rule": None,  # present | lop | hold — no default: Hotel Vivek decides
    "grace_minutes": 10,
    "ot_threshold_minutes": 30,
    "ot_block_minutes": 30,
    "leave_hr_after_days": 5,  # leave longer than this also needs HR after the HOD
    "notice_days_default": 30,
    "fnf_working_days": 2,
    "doc_expiry_alert_days": 30,
}

POLICY_HELP = {
    "payroll_day": "Day of the month salaries are paid",
    "attendance_cutoff_day": "Attendance is final up to this day; later days roll to next month",
    "missed_punch_rule": "What happens to a missed punch still open at cut-off: present, lop or hold",
    "grace_minutes": "Minutes after shift start before an arrival counts as late",
    "ot_threshold_minutes": "Extra minutes before OT starts counting",
    "ot_block_minutes": "OT is counted in blocks of this many minutes",
    "leave_hr_after_days": "Leave longer than this goes to HR after the HOD",
    "notice_days_default": "Notice period when the grade has none",
    "fnf_working_days": "Full and final must be paid within this many working days of the last day",
    "doc_expiry_alert_days": "Flag documents expiring within this many days",
}


def policy(db: Session, key: str, on: date | None = None) -> Any:
    on = on or date.today()
    row = db.scalar(select(m.PolicyVersion).where(m.PolicyVersion.key == key, m.PolicyVersion.effective_from <= on)
                    .order_by(m.PolicyVersion.effective_from.desc(), m.PolicyVersion.id.desc()))
    return row.value if row else POLICY_DEFAULTS.get(key)


def all_policies(db: Session, on: date | None = None) -> dict[str, Any]:
    return {k: policy(db, k, on) for k in POLICY_DEFAULTS}


def rules_for(db: Session, entity_id: int | None, on: date) -> dict[str, Any]:
    stmt = select(m.StatutoryRuleVersion).where(m.StatutoryRuleVersion.effective_from <= on).order_by(
        m.StatutoryRuleVersion.effective_from.desc(), m.StatutoryRuleVersion.id.desc())
    rows = db.scalars(stmt).all()
    for r in rows:
        if r.entity_id == entity_id:
            return deepcopy(r.rules)
    for r in rows:
        if r.entity_id is None:
            return deepcopy(r.rules)
    return deepcopy(DEFAULT_RULES)
