from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, time, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import models as m
from ..domain import attendance_engine as ae
from .policies import policy

OFF = ae.Shift("OFF", time(0), time(0), 0, is_off=True)


def shift_map(db: Session) -> dict[str, ae.Shift]:
    out = {}
    for s in db.scalars(select(m.Shift)):
        out[s.code] = ae.Shift(s.code, time.fromisoformat(s.start_time), time.fromisoformat(s.end_time), s.break_minutes, s.is_off)
    out.setdefault("OFF", OFF)
    return out


def leave_dates(db: Session, employee_id: int, start: date, end: date) -> tuple[set[date], set[date]]:
    """(all approved leave dates, unpaid leave dates)"""
    paid_types = {lt.code: lt.paid for lt in db.scalars(select(m.LeaveType))}
    all_d: set[date] = set()
    unpaid: set[date] = set()
    for lr in db.scalars(select(m.LeaveRequest).where(m.LeaveRequest.employee_id == employee_id, m.LeaveRequest.status == "approved",
                                                       m.LeaveRequest.from_date <= end, m.LeaveRequest.to_date >= start)):
        d = max(lr.from_date, start)
        while d <= min(lr.to_date, end):
            all_d.add(d)
            if not paid_types.get(lr.leave_code, True):
                unpaid.add(d)
            d += timedelta(days=1)
    return all_d, unpaid


def holidays_for(db: Session, location_id: int, start: date, end: date) -> set[date]:
    return set(db.scalars(select(m.Holiday.day).where(m.Holiday.day >= start, m.Holiday.day <= end,
                                                       or_(m.Holiday.location_id.is_(None), m.Holiday.location_id == location_id))))


def process_month(db: Session, year: int, month: int, *, location_id: int | None = None, employee_ids: list[int] | None = None) -> dict:
    start, end = date(year, month, 1), date(year, month, monthrange(year, month)[1])
    end = min(end, date.today())
    shifts = shift_map(db)
    grace = int(policy(db, "grace_minutes", end) or 10)
    ot_thr = int(policy(db, "ot_threshold_minutes", end) or 30)
    ot_blk = int(policy(db, "ot_block_minutes", end) or 30)
    stmt = select(m.Employee).where(m.Employee.doj <= end, or_(m.Employee.dol.is_(None), m.Employee.dol >= start))
    if location_id:
        stmt = stmt.where(m.Employee.location_id == location_id)
    if employee_ids:
        stmt = stmt.where(m.Employee.id.in_(employee_ids))
    locs = {x.id: x for x in db.scalars(select(m.Location))}
    counts = {"employees": 0, "days": 0, "missed_punch": 0, "absent": 0, "orphan_punches": 0, "skipped_locked": 0}
    for e in db.scalars(stmt):
        counts["employees"] += 1
        first, last = max(start, e.doj), min(end, e.dol or end)
        roster = {r.day: r.shift_code for r in db.scalars(select(m.RosterEntry).where(m.RosterEntry.employee_id == e.id, m.RosterEntry.day >= first,
                                                                                        m.RosterEntry.day <= last))}
        weekly_off = locs[e.location_id].weekly_off
        by_date: dict[date, ae.Shift] = {}
        d = first
        while d <= last:
            code = roster.get(d) or ("OFF" if d.weekday() == weekly_off else e.shift_code)
            by_date[d] = shifts.get(code, shifts.get("G", OFF))
            d += timedelta(days=1)
        punches = list(db.scalars(select(m.Punch.punched_at).where(m.Punch.employee_id == e.id, m.Punch.punched_at >= datetime.combine(first, time(0)) - timedelta(hours=8),
                                                                    m.Punch.punched_at <= datetime.combine(last, time(23, 59)) + timedelta(hours=14))))
        assigned, orphans = ae.assign_punches(punches, by_date)
        counts["orphan_punches"] += len(orphans)
        leave_all, _ = leave_dates(db, e.id, first, last)
        hols = holidays_for(db, e.location_id, first, last)
        existing = {x.work_date: x for x in db.scalars(select(m.AttendanceDay).where(m.AttendanceDay.employee_id == e.id, m.AttendanceDay.work_date >= first,
                                                                                     m.AttendanceDay.work_date <= last))}
        for wd, sh in by_date.items():
            row = existing.get(wd)
            if row and (row.locked or row.regularised):
                counts["skipped_locked"] += 1
                continue
            r = ae.build_day(wd, sh, assigned.get(wd, []), grace_minutes=grace, ot_threshold_minutes=ot_thr, ot_block_minutes=ot_blk,
                             on_leave=wd in leave_all, is_holiday=wd in hols)
            if row is None:
                row = m.AttendanceDay(employee_id=e.id, work_date=wd)
                db.add(row)
            row.shift_code, row.status = r.shift_code, r.status
            row.first_in, row.last_out = r.first_in, r.last_out
            row.worked_minutes, row.late_minutes, row.ot_minutes = r.worked_minutes, r.late_minutes, r.ot_minutes
            counts["days"] += 1
            if r.status in ("missed_punch", "absent"):
                counts[r.status] += 1
    db.flush()
    return counts


def month_summary(db: Session, employee: m.Employee, year: int, month: int, rule: str | None) -> ae.MonthSummary:
    start, end = date(year, month, 1), date(year, month, monthrange(year, month)[1])
    rows = db.scalars(select(m.AttendanceDay).where(m.AttendanceDay.employee_id == employee.id, m.AttendanceDay.work_date >= start,
                                                    m.AttendanceDay.work_date <= end)).all()
    days = [ae.DayResult(r.work_date, r.shift_code, r.status, r.first_in, r.last_out, r.worked_minutes, r.late_minutes,
                         r.ot_minutes if r.ot_approved else 0) for r in rows]
    _, unpaid = leave_dates(db, employee.id, start, end)
    night_codes = tuple(s.code for s in db.scalars(select(m.Shift).where(m.Shift.is_night.is_(True)))) or ("N",)
    s = ae.summarise_month(days, monthrange(year, month)[1], missed_punch_rule=rule, unpaid_leave_dates=unpaid, night_shift_codes=night_codes)
    # days outside employment (joined late / left early) are not paid
    outside = sum(1 for d in ae.month_dates(year, month) if d < employee.doj or (employee.dol and d > employee.dol))
    if outside:
        s.lop_days += outside
        s.paid_days -= outside
    # days after today that are not yet processed are treated as paid (attendance closes at cut-off)
    return s
