from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from .. import models as m
from ..deps import DB, User
from ..domain import attendance_engine as ae
from ..serial import Lookups, employee_summary, row
from ..services.access import can_see_employee, has, is_manager_of, require, scope_employees
from ..services.attendance import month_summary, process_month, shift_map
from ..services.audit import record
from ..services.integrations import get_biometric
from ..services.policies import policy

router = APIRouter(prefix="/api", tags=["attendance and leave"])


# ---------------------------------------------------------------- attendance
class ProcessIn(BaseModel):
    year: int
    month: int
    location_id: int | None = None


@router.post("/attendance/process")
def process(body: ProcessIn, user: User, db: DB) -> dict:
    require(user, "attendance.manage")
    res = process_month(db, body.year, body.month, location_id=body.location_id)
    record(db, user.email, "attendance_processed", "attendance", f"{body.year}-{body.month:02d}", after=res)
    db.commit()
    return res


@router.post("/attendance/sync")
def sync_device(user: User, db: DB) -> dict:
    """Pull punches from the device API (http adapter). With the Excel adapter, upload the punch file instead."""
    require(user, "attendance.manage")
    adapter = get_biometric()
    last = db.scalar(select(func.max(m.Punch.punched_at)).where(m.Punch.source == "api")) or datetime.now() - timedelta(days=3)
    rows = adapter.fetch_punches(last)
    ids = {e.code: e.id for e in db.scalars(select(m.Employee))}
    added = 0
    for code, at, device in rows:
        eid = ids.get(code)
        if eid and not db.scalar(select(m.Punch.id).where(m.Punch.employee_id == eid, m.Punch.punched_at == at)):
            db.add(m.Punch(employee_id=eid, punched_at=at, device_id=device, source="api"))
            added += 1
    record(db, user.email, "biometric_sync", "attendance", None, after={"adapter": adapter.name, "read": len(rows), "added": added})
    db.commit()
    return {"adapter": adapter.name, "read": len(rows), "added": added}


@router.get("/attendance/days")
def days(user: User, db: DB, date_from: date, date_to: date, location_id: int | None = None, status: str | None = None,
         employee_id: int | None = None, limit: int = 500) -> list[dict]:
    if not (has(user, "attendance.read") or employee_id == user.employee_id):
        raise HTTPException(403, "Not allowed")
    emp_ids = select(m.Employee.id)
    emp_ids = scope_employees(emp_ids, user) if has(user, "attendance.read") else emp_ids.where(m.Employee.id == user.employee_id)
    if location_id:
        emp_ids = emp_ids.where(m.Employee.location_id == location_id)
    stmt = select(m.AttendanceDay).where(m.AttendanceDay.work_date >= date_from, m.AttendanceDay.work_date <= date_to, m.AttendanceDay.employee_id.in_(emp_ids))
    if status:
        stmt = stmt.where(m.AttendanceDay.status == status)
    if employee_id:
        stmt = stmt.where(m.AttendanceDay.employee_id == employee_id)
    rows = db.scalars(stmt.order_by(m.AttendanceDay.work_date.desc(), m.AttendanceDay.employee_id).limit(min(limit, 5000))).all()
    lk = Lookups(db)
    emps = {e.id: e for e in db.scalars(select(m.Employee).where(m.Employee.id.in_(list({r.employee_id for r in rows}) or [-1])))}
    return [row(r, employee=employee_summary(emps[r.employee_id], lk)) for r in rows]


@router.get("/attendance/exceptions")
def exceptions(user: User, db: DB, date_from: date | None = None, date_to: date | None = None) -> dict:
    require(user, "attendance.read")
    date_to = date_to or date.today()
    date_from = date_from or date_to.replace(day=1)
    emp_ids = scope_employees(select(m.Employee.id), user)
    base = select(m.AttendanceDay).where(m.AttendanceDay.work_date >= date_from, m.AttendanceDay.work_date <= date_to, m.AttendanceDay.employee_id.in_(emp_ids))
    missed = db.scalars(base.where(m.AttendanceDay.status == "missed_punch", m.AttendanceDay.regularised.is_(False))).all()
    late = db.scalars(base.where(m.AttendanceDay.late_minutes > 0)).all()
    ot = db.scalars(base.where(m.AttendanceDay.ot_minutes > 0, m.AttendanceDay.ot_approved.is_(False))).all()
    absent = db.scalars(base.where(m.AttendanceDay.status == "absent")).all()
    lk = Lookups(db)
    ids = {r.employee_id for r in [*missed, *late, *ot, *absent]}
    emps = {e.id: e for e in db.scalars(select(m.Employee).where(m.Employee.id.in_(list(ids) or [-1])))}
    pack = lambda rs: [row(r, employee=employee_summary(emps[r.employee_id], lk)) for r in rs]  # noqa: E731
    return {"from": date_from.isoformat(), "to": date_to.isoformat(), "missed_punch": pack(missed), "late": pack(late), "ot_pending": pack(ot),
            "absent": pack(absent), "missed_punch_rule": policy(db, "missed_punch_rule", date_to)}


class ResolveIn(BaseModel):
    in_time: str | None = None  # HH:MM
    out_time: str | None = None
    mark: str | None = None  # present | absent
    note: str | None = None


def _day_for(db: DB, day_id: int) -> m.AttendanceDay:
    d = db.get(m.AttendanceDay, day_id)
    if not d:
        raise HTTPException(404, "Attendance day not found")
    if d.locked:
        raise HTTPException(409, "This day is locked by a payroll run")
    return d


def apply_times(db: DB, d: m.AttendanceDay, in_time: str, out_time: str) -> None:
    sh = shift_map(db).get(d.shift_code) or shift_map(db)["OFF"]
    tin = datetime.combine(d.work_date, time.fromisoformat(in_time))
    tout = datetime.combine(d.work_date, time.fromisoformat(out_time))
    if tout <= tin:
        tout += timedelta(days=1)
    r = ae.build_day(d.work_date, sh, [tin, tout], grace_minutes=int(policy(db, "grace_minutes") or 10))
    d.status, d.first_in, d.last_out = r.status, r.first_in, r.last_out
    d.worked_minutes, d.late_minutes, d.ot_minutes = r.worked_minutes, r.late_minutes, r.ot_minutes
    d.regularised = True


@router.post("/attendance/days/{day_id}/resolve")
def resolve(day_id: int, body: ResolveIn, user: User, db: DB) -> dict:
    """HR/HOD clears an exception on screen (missed punch, wrong status)."""
    d = _day_for(db, day_id)
    if not (has(user, "attendance.manage") or (has(user, "attendance.approve") and is_manager_of(db, user, d.employee_id))):
        raise HTTPException(403, "Not allowed")
    before = row(d)
    if body.in_time and body.out_time:
        apply_times(db, d, body.in_time, body.out_time)
    elif body.mark in ("present", "absent"):
        d.status, d.regularised = body.mark, True
    else:
        raise HTTPException(400, "Give in and out times, or mark present/absent")
    record(db, user.email, "attendance_resolved", "attendance_day", d.id, before=before, after={**row(d), "note": body.note}, employee_id=d.employee_id)
    db.commit()
    return row(d)


@router.post("/attendance/days/{day_id}/ot")
def approve_ot(day_id: int, approve: bool, user: User, db: DB) -> dict:
    d = _day_for(db, day_id)
    if not (has(user, "attendance.manage") or (has(user, "attendance.approve") and is_manager_of(db, user, d.employee_id))):
        raise HTTPException(403, "Only the HOD or HR can approve OT")
    d.ot_approved = approve
    if not approve:
        d.ot_minutes = 0
    record(db, user.email, "ot_approved" if approve else "ot_rejected", "attendance_day", d.id, after={"ot_minutes": d.ot_minutes}, employee_id=d.employee_id)
    db.commit()
    return row(d)


class RegIn(BaseModel):
    employee_id: int | None = None
    work_date: date
    kind: str = "missed_punch"
    in_time: str | None = None
    out_time: str | None = None
    reason: str | None = None


@router.post("/regularisations")
def reg_request(body: RegIn, user: User, db: DB) -> dict:
    eid = body.employee_id or user.employee_id
    if not eid or (eid != user.employee_id and not has(user, "attendance.manage")):
        raise HTTPException(403, "Not allowed")
    r = m.Regularisation(employee_id=eid, work_date=body.work_date, kind=body.kind, in_time=body.in_time, out_time=body.out_time, reason=body.reason,
                         requested_by=user.email)
    db.add(r)
    db.flush()
    record(db, user.email, "regularisation_requested", "regularisation", r.id, after=row(r), employee_id=eid)
    db.commit()
    return row(r)


@router.post("/regularisations/{reg_id}/decide")
def reg_decide(reg_id: int, approve: bool, user: User, db: DB) -> dict:
    r = db.get(m.Regularisation, reg_id)
    if not r or r.status != "pending":
        raise HTTPException(404, "No pending request")
    if not (has(user, "attendance.manage") or (has(user, "attendance.approve") and is_manager_of(db, user, r.employee_id))):
        raise HTTPException(403, "Only the HOD or HR can decide")
    r.status, r.decided_by = ("approved" if approve else "rejected"), user.email
    if approve:
        d = db.scalar(select(m.AttendanceDay).where(m.AttendanceDay.employee_id == r.employee_id, m.AttendanceDay.work_date == r.work_date))
        if d and not d.locked:
            if r.kind == "ot":
                d.ot_approved = True
            elif r.in_time and r.out_time:
                apply_times(db, d, r.in_time, r.out_time)
    record(db, user.email, "regularisation_" + r.status, "regularisation", r.id, employee_id=r.employee_id)
    db.commit()
    return row(r)


@router.get("/attendance/summary")
def summary(user: User, db: DB, year: int, month: int, location_id: int | None = None) -> dict:
    require(user, "attendance.read")
    rule = policy(db, "missed_punch_rule", date(year, month, 1))
    stmt = scope_employees(select(m.Employee).where(m.Employee.status != "exited"), user)
    if location_id:
        stmt = stmt.where(m.Employee.location_id == location_id)
    lk = Lookups(db)
    out, blocked = [], 0
    for e in db.scalars(stmt.order_by(m.Employee.code)):
        try:
            s = month_summary(db, e, year, month, rule)
            out.append({**employee_summary(e, lk), **{k: (str(v) if isinstance(v, Decimal) else v) for k, v in s.__dict__.items()}})
        except ValueError as err:
            blocked += 1
            out.append({**employee_summary(e, lk), "error": str(err)})
    return {"rule": rule, "blocked": blocked, "items": out}


# ---------------------------------------------------------------- roster
class RosterIn(BaseModel):
    entries: list[dict]  # [{employee_id, day, shift_code}]


@router.get("/attendance/roster")
def roster(user: User, db: DB, week_start: date, location_id: int | None = None, department_id: int | None = None) -> dict:
    require(user, "attendance.read")
    days = [week_start + timedelta(days=i) for i in range(7)]
    stmt = scope_employees(select(m.Employee).where(m.Employee.status != "exited"), user)
    if location_id:
        stmt = stmt.where(m.Employee.location_id == location_id)
    if department_id:
        stmt = stmt.where(m.Employee.department_id == department_id)
    emps = db.scalars(stmt.order_by(m.Employee.code).limit(300)).all()
    entries = {(r.employee_id, r.day): r.shift_code for r in db.scalars(select(m.RosterEntry).where(m.RosterEntry.day >= days[0], m.RosterEntry.day <= days[-1],
                                                                                                      m.RosterEntry.employee_id.in_([e.id for e in emps] or [-1])))}
    locs = {x.id: x for x in db.scalars(select(m.Location))}
    lk = Lookups(db)
    return {"days": [d.isoformat() for d in days], "shifts": [row(s) for s in db.scalars(select(m.Shift))],
            "rows": [{**employee_summary(e, lk), "cells": [entries.get((e.id, d)) or ("OFF" if d.weekday() == locs[e.location_id].weekly_off else e.shift_code)
                                                           for d in days]} for e in emps]}


@router.put("/attendance/roster")
def roster_save(body: RosterIn, user: User, db: DB) -> dict:
    require(user, "attendance.manage")
    codes = {s.code for s in db.scalars(select(m.Shift))} | {"OFF"}
    n = 0
    for en in body.entries:
        if en["shift_code"] not in codes:
            raise HTTPException(400, f"Unknown shift {en['shift_code']}")
        d = date.fromisoformat(en["day"])
        r = db.scalar(select(m.RosterEntry).where(m.RosterEntry.employee_id == en["employee_id"], m.RosterEntry.day == d))
        if r:
            r.shift_code = en["shift_code"]
        else:
            db.add(m.RosterEntry(employee_id=en["employee_id"], day=d, shift_code=en["shift_code"]))
        n += 1
    record(db, user.email, "roster_saved", "roster", None, after={"entries": n})
    db.commit()
    return {"saved": n}


# ---------------------------------------------------------------- leave
class LeaveIn(BaseModel):
    employee_id: int | None = None
    leave_code: str
    from_date: date
    to_date: date
    half_day: bool = False
    reason: str | None = None


@router.get("/leave/balances")
def balances(user: User, db: DB, employee_id: int | None = None, year: int | None = None) -> list[dict]:
    eid = employee_id or user.employee_id
    if not eid or (eid != user.employee_id and not can_see_employee(db, user, eid)):
        raise HTTPException(403, "Not allowed")
    year = year or date.today().year
    types = {t.code: t for t in db.scalars(select(m.LeaveType))}
    out = []
    for b in db.scalars(select(m.LeaveBalance).where(m.LeaveBalance.employee_id == eid, m.LeaveBalance.year == year)):
        t = types.get(b.leave_code)
        out.append({"leave_code": b.leave_code, "name": t.name if t else b.leave_code, "opening": str(b.opening), "used": str(b.used),
                    "available": str(b.opening - b.used), "paid": t.paid if t else True})
    return out


@router.get("/leave/requests")
def leave_list(user: User, db: DB, status: str | None = None, mine: bool = False) -> list[dict]:
    stmt = select(m.LeaveRequest).order_by(m.LeaveRequest.created_at.desc()).limit(500)
    if mine or not has(user, "leave.approve"):
        stmt = stmt.where(m.LeaveRequest.employee_id == (user.employee_id or -1))
    else:
        stmt = stmt.where(m.LeaveRequest.employee_id.in_(scope_employees(select(m.Employee.id), user)))
    if status:
        stmt = stmt.where(m.LeaveRequest.status == status)
    lk = Lookups(db)
    rows = db.scalars(stmt).all()
    emps = {e.id: e for e in db.scalars(select(m.Employee).where(m.Employee.id.in_(list({r.employee_id for r in rows}) or [-1])))}
    return [row(r, employee=employee_summary(emps[r.employee_id], lk)) for r in rows]


@router.post("/leave/requests")
def leave_apply(body: LeaveIn, user: User, db: DB) -> dict:
    eid = body.employee_id or user.employee_id
    if not eid or (eid != user.employee_id and not has(user, "leave.approve")):
        raise HTTPException(403, "Not allowed")
    if body.to_date < body.from_date:
        raise HTTPException(400, "To date is before from date")
    lt = db.get(m.LeaveType, body.leave_code)
    if not lt:
        raise HTTPException(400, "Unknown leave type")
    days = Decimal("0.5") if body.half_day else Decimal((body.to_date - body.from_date).days + 1)
    if lt.paid:
        bal = db.scalar(select(m.LeaveBalance).where(m.LeaveBalance.employee_id == eid, m.LeaveBalance.leave_code == lt.code,
                                                     m.LeaveBalance.year == body.from_date.year))
        if not bal or bal.opening - bal.used < days:
            raise HTTPException(400, f"Not enough {lt.name} balance")
    overlap = db.scalar(select(m.LeaveRequest.id).where(m.LeaveRequest.employee_id == eid, m.LeaveRequest.status.in_(["pending_hod", "pending_hr", "approved"]),
                                                        m.LeaveRequest.from_date <= body.to_date, m.LeaveRequest.to_date >= body.from_date))
    if overlap:
        raise HTTPException(409, "There is already leave on these dates")
    e = db.get(m.Employee, eid)
    r = m.LeaveRequest(employee_id=eid, leave_code=lt.code, from_date=body.from_date, to_date=body.to_date, days=days, reason=body.reason,
                       status="pending_hod" if e.manager_id else "pending_hr", requested_by=user.email)
    db.add(r)
    db.flush()
    record(db, user.email, "leave_applied", "leave", r.id, after=row(r), employee_id=eid)
    db.commit()
    return row(r)


@router.post("/leave/requests/{req_id}/decide")
def leave_decide(req_id: int, approve: bool, user: User, db: DB) -> dict:
    r = db.get(m.LeaveRequest, req_id)
    if not r or r.status not in ("pending_hod", "pending_hr"):
        raise HTTPException(404, "No pending request")
    is_hr = has(user, "employees.write")
    if r.status == "pending_hod" and not (is_hr or (has(user, "leave.approve") and is_manager_of(db, user, r.employee_id))):
        raise HTTPException(403, "Waiting for the employee's HOD")
    if r.status == "pending_hr" and not is_hr:
        raise HTTPException(403, "Waiting for HR")
    if not approve:
        r.status = "rejected"
    elif r.status == "pending_hod" and not is_hr and r.days > Decimal(str(policy(db, "leave_hr_after_days") or 5)):
        r.status = "pending_hr"
    else:
        r.status = "approved"
        lt = db.get(m.LeaveType, r.leave_code)
        if lt and lt.paid:
            bal = db.scalar(select(m.LeaveBalance).where(m.LeaveBalance.employee_id == r.employee_id, m.LeaveBalance.leave_code == r.leave_code,
                                                         m.LeaveBalance.year == r.from_date.year))
            if bal:
                bal.used += r.days
        for d in db.scalars(select(m.AttendanceDay).where(m.AttendanceDay.employee_id == r.employee_id, m.AttendanceDay.work_date >= r.from_date,
                                                          m.AttendanceDay.work_date <= r.to_date, m.AttendanceDay.locked.is_(False))):
            if d.status in ("absent", "missed_punch"):
                d.status = "leave"
    r.decided_by = user.email
    record(db, user.email, f"leave_{r.status}", "leave", r.id, employee_id=r.employee_id)
    db.commit()
    return row(r)


@router.post("/leave/requests/{req_id}/cancel")
def leave_cancel(req_id: int, user: User, db: DB) -> dict:
    r = db.get(m.LeaveRequest, req_id)
    if not r or r.employee_id != user.employee_id or r.status not in ("pending_hod", "pending_hr"):
        raise HTTPException(400, "Only your own pending leave can be cancelled")
    r.status = "cancelled"
    record(db, user.email, "leave_cancelled", "leave", r.id, employee_id=r.employee_id)
    db.commit()
    return row(r)

