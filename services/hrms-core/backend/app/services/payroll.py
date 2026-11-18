"""Payroll run orchestration. The calculation itself is domain.payroll_engine (tested code, not AI)."""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import models as m
from ..domain.payroll_engine import Allocation, PayInput, calculate
from .attendance import month_summary
from .policies import policy, rules_for

D = Decimal
VARIABLE_CODES = {"SERVICE_CHARGE", "INCENTIVE", "ARREAR", "BONUS", "OTHER_EARNING", "ADVANCE", "LOAN_EMI", "OTHER_DEDUCTION"}


def period_bounds(period: str) -> tuple[date, date, int]:
    try:
        y, mth = (int(x) for x in period.split("-"))
        days = monthrange(y, mth)[1]
        return date(y, mth, 1), date(y, mth, days), days
    except (ValueError, TypeError) as e:
        raise HTTPException(400, "Period must be YYYY-MM") from e


def _overlaps(model: type, start: date, end: date):
    return (model.effective_from <= end) & or_(model.effective_to.is_(None), model.effective_to >= start)


def employees_paid_by(db: Session, entity_id: int, start: date, end: date) -> list[m.Employee]:
    ids = select(m.EntityAllocation.employee_id).where(m.EntityAllocation.entity_id == entity_id, _overlaps(m.EntityAllocation, start, end))
    return list(db.scalars(select(m.Employee).where(m.Employee.id.in_(ids), m.Employee.doj <= end,
                                                    or_(m.Employee.dol.is_(None), m.Employee.dol >= start)).order_by(m.Employee.code)))


def open_missed_punches(db: Session, employee_ids: list[int], start: date, end: date) -> int:
    return db.scalar(select(func.count(m.AttendanceDay.id)).where(m.AttendanceDay.employee_id.in_(employee_ids or [-1]), m.AttendanceDay.status == "missed_punch",
                                                                 m.AttendanceDay.regularised.is_(False), m.AttendanceDay.work_date >= start,
                                                                 m.AttendanceDay.work_date <= end)) or 0


def _step(run: m.PayrollRun, step: str, detail: str) -> None:
    run.steps = [*(run.steps or []), {"step": step, "detail": detail, "at": datetime.now(timezone.utc).isoformat()}]


def calculate_lines(db: Session, run: m.PayrollRun) -> None:
    start, end, days = period_bounds(run.period)
    entity = db.get(m.Entity, run.entity_id)
    emps = employees_paid_by(db, run.entity_id, start, end)
    rule = policy(db, "missed_punch_rule", end)
    missed = open_missed_punches(db, [e.id for e in emps], start, end)
    if missed and rule is None:
        raise HTTPException(409, f"{missed} missed punches are open and the company's missed-punch rule is not set. "
                                 "Regularise them on the Attendance screen or set the rule in Company setup.")
    rules = rules_for(db, run.entity_id, end)
    run.rules, run.missed_punch_rule = rules, rule
    _step(run, "Lock attendance", f"1–{days} {start:%b %Y} · {len(emps)} staff · {missed} open missed punches → rule: {rule or 'n/a'}")

    inputs: dict[int, dict[str, Decimal]] = {}
    for i in db.scalars(select(m.MonthlyInput).where(m.MonthlyInput.period == run.period, m.MonthlyInput.employee_id.in_([e.id for e in emps] or [-1]))):
        inputs.setdefault(i.employee_id, {})[i.code] = i.amount
    _step(run, "Apply inputs", f"{sum(len(v) for v in inputs.values())} monthly input values for {len(inputs)} staff")

    prev_net: dict[int, Decimal] = {}
    for ln in db.scalars(select(m.PayrollLine).join(m.PayrollRun, m.PayrollRun.id == m.PayrollLine.run_id)
                         .where(m.PayrollRun.status == "locked", m.PayrollRun.period < run.period).order_by(m.PayrollRun.period)):
        prev_net[ln.employee_id] = D(str(ln.full_result.get("net", "0")))

    stat = entity.statutory or {}
    old = {ln.employee_id: ln for ln in db.scalars(select(m.PayrollLine).where(m.PayrollLine.run_id == run.id))}
    for ln in old.values():
        db.delete(ln)
    db.flush()

    flagged = 0
    for e in emps:
        st = db.scalar(select(m.SalaryStructure).where(m.SalaryStructure.employee_id == e.id, m.SalaryStructure.effective_from <= end)
                       .order_by(m.SalaryStructure.effective_from.desc()))
        allocs = db.scalars(select(m.EntityAllocation).where(m.EntityAllocation.employee_id == e.id, _overlaps(m.EntityAllocation, end, end))).all() \
            or db.scalars(select(m.EntityAllocation).where(m.EntityAllocation.employee_id == e.id, _overlaps(m.EntityAllocation, start, end))).all()
        summary = month_summary(db, e, int(run.period[:4]), int(run.period[5:]), rule)
        var = inputs.get(e.id, {})
        inp = PayInput(
            employee_code=e.code, name=f"{e.first_name} {e.last_name}".strip(),
            components={k: D(str(v)) for k, v in (st.components if st else {}).items()},
            days_in_month=days, paid_days=summary.paid_days, month=start.month, year=start.year,
            ot_hours=summary.ot_hours, night_shifts=summary.night_shifts,
            variable={k: v for k, v in var.items() if k in VARIABLE_CODES},
            pf_applicable=e.pf_applicable and stat.get("PF", True), esi_applicable=e.esi_applicable and stat.get("ESI", True),
            pt_applicable=e.pt_applicable and stat.get("PT", True), lwf_applicable=e.lwf_applicable and stat.get("LWF", True),
            tds_override=var.get("TDS_OVERRIDE"), has_bank=bool(e.bank_account_enc), previous_net=prev_net.get(e.id),
            default_entity=str(run.entity_id),
            allocations=[Allocation(str(a.entity_id), a.method, D(str(a.value)), a.is_primary) for a in allocs],
        )
        res = calculate(inp, rules)
        share = res.by_entity.get(str(run.entity_id), {"earnings": {}, "deductions": {}, "employer": {}, "gross": D(0), "net": D(0)})
        flags = [f.as_dict() for f in res.flags]
        if summary.held_days:
            flags.append({"code": "HELD_DAYS", "severity": "warn", "message": f"{summary.held_days} days held for open missed punches (paid in the next run once regularised)."})
        prev = old.get(e.id)
        keep = prev and prev.decision and {f["code"] for f in prev.flags} == {f["code"] for f in flags}
        gross = D(str(share["gross"]))
        line = m.PayrollLine(
            run_id=run.id, employee_id=e.id, paid_days=summary.paid_days, lop_days=summary.lop_days, ot_hours=summary.ot_hours,
            earnings={k: str(v) for k, v in share["earnings"].items()}, deductions={k: str(v) for k, v in share["deductions"].items()},
            employer={k: str(v) for k, v in share["employer"].items()}, gross=gross,
            total_deductions=sum((D(str(v)) for v in share["deductions"].values()), D(0)), net=D(str(share["net"])),
            share_pct=(gross / res.gross * 100).quantize(D("0.0001")) if res.gross else D(100), full_result=res.as_dict(), flags=flags,
            decision=prev.decision if keep else None, decision_note=prev.decision_note if keep else None,
            decided_by=prev.decided_by if keep else None, hold=bool(prev.hold) if keep else False,
        )
        db.add(line)
        flagged += 1 if flags else 0
    db.flush()
    _step(run, f"Calculate {entity.code}", f"{len(emps)} lines · rules {rules.get('version')}")
    _step(run, "Run checks", f"{flagged} lines flagged for review")
    refresh_totals(db, run)
    run.status = "calculated"


def refresh_totals(db: Session, run: m.PayrollRun) -> None:
    lines = db.scalars(select(m.PayrollLine).where(m.PayrollLine.run_id == run.id)).all()
    t: dict[str, Decimal] = {"headcount": D(len(lines)), "gross": D(0), "net": D(0), "net_payable": D(0), "held": D(0), "flagged": D(0), "undecided": D(0)}
    for ln in lines:
        t["gross"] += ln.gross
        t["net"] += ln.net
        if ln.hold:
            t["held"] += 1
        else:
            t["net_payable"] += ln.net
        if ln.flags:
            t["flagged"] += 1
            if not ln.decision:
                t["undecided"] += 1
        for k, v in {**ln.deductions, **ln.employer}.items():
            t[k] = t.get(k, D(0)) + D(str(v))
    run.totals = {k: str(v) for k, v in t.items()}


def line_view(ln: m.PayrollLine, e: m.Employee) -> dict[str, Any]:
    return {"id": ln.id, "employee_id": e.id, "code": e.code, "name": f"{e.first_name} {e.last_name}".strip(), "paid_days": str(ln.paid_days),
            "lop_days": str(ln.lop_days), "ot_hours": str(ln.ot_hours), "earnings": ln.earnings, "deductions": ln.deductions, "employer": ln.employer,
            "gross": str(ln.gross), "total_deductions": str(ln.total_deductions), "net": str(ln.net), "share_pct": str(ln.share_pct),
            "flags": ln.flags, "decision": ln.decision, "decision_note": ln.decision_note, "decided_by": ln.decided_by, "hold": ln.hold,
            "split": len((ln.full_result or {}).get("by_entity", {})) > 1}
