"""Performance and increments, reports (static), circulars and wishes, approvals inbox, self-service, audit."""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from .. import models as m
from ..deps import DB, User
from ..serial import Lookups, employee_detail, employee_summary, row
from ..services.access import has, is_manager_of, require, scope_employees
from ..services.audit import record
from ..services.employees import close_dated, in_force
from ..services.integrations import queue_message
from ..services.policies import policy
from ..tenant import get_tenant

router = APIRouter(prefix="/api", tags=["people"])
D = Decimal

# rating (5 best) x position in pay band (low, middle, high) -> increment %. Sample; each client sets its own.
MERIT = {5: [12, 10, 8], 4: [9, 7, 5], 3: [6, 5, 3], 2: [2, 1, 0], 1: [0, 0, 0]}


# ---------------------------------------------------------------- performance
class CycleIn(BaseModel):
    name: str
    opens_on: date
    closes_on: date


@router.get("/performance/cycles")
def cycles(user: User, db: DB) -> list[dict]:
    out = []
    for c in db.scalars(select(m.ReviewCycle).order_by(m.ReviewCycle.opens_on.desc())):
        counts = dict(db.execute(select(m.Review.status, func.count()).where(m.Review.cycle_id == c.id).group_by(m.Review.status)).all())
        out.append(row(c, progress=counts, total=sum(counts.values())))
    return out


@router.post("/performance/cycles")
def cycle_create(body: CycleIn, user: User, db: DB) -> dict:
    require(user, "performance.manage")
    c = m.ReviewCycle(name=body.name, opens_on=body.opens_on, closes_on=body.closes_on, templates=get_tenant().KRA_TEMPLATES)
    db.add(c)
    db.flush()
    n = 0
    for e in db.scalars(select(m.Employee).where(m.Employee.status == "active")):
        db.add(m.Review(cycle_id=c.id, employee_id=e.id))
        queue_message(db, to=e.phone, template="review_open", employee_id=e.id, payload={"cycle": c.name, "language": e.language})
        n += 1
    record(db, user.email, "review_cycle_launched", "review_cycle", c.id, after={"name": c.name, "reviews": n})
    db.commit()
    return row(c, reviews=n)


@router.get("/performance/cycles/{cycle_id}/reviews")
def reviews(cycle_id: int, user: User, db: DB, mine: bool = False) -> list[dict]:
    c = db.get(m.ReviewCycle, cycle_id)
    if not c:
        raise HTTPException(404, "Cycle not found")
    stmt = select(m.Review).where(m.Review.cycle_id == cycle_id)
    if mine or not has(user, "performance.review"):
        stmt = stmt.where(m.Review.employee_id == (user.employee_id or -1))
    else:
        stmt = stmt.where(m.Review.employee_id.in_(scope_employees(select(m.Employee.id), user)))
    lk = Lookups(db)
    rs = db.scalars(stmt.limit(500)).all()
    emps = {e.id: e for e in db.scalars(select(m.Employee).where(m.Employee.id.in_([r.employee_id for r in rs] or [-1])))}
    return [row(r, employee=employee_summary(emps[r.employee_id], lk), kras=c.templates.get(lk.dept.get(emps[r.employee_id].department_id), c.templates["_default"]))
            for r in rs]


class ReviewIn(BaseModel):
    self_ratings: dict[str, int] | None = None
    manager_rating: int | None = None
    manager_comment: str | None = None
    final_rating: int | None = None


@router.put("/performance/reviews/{review_id}")
def review_update(review_id: int, body: ReviewIn, user: User, db: DB) -> dict:
    r = db.get(m.Review, review_id)
    if not r:
        raise HTTPException(404, "Review not found")
    if body.self_ratings is not None:
        if r.employee_id != user.employee_id:
            raise HTTPException(403, "Only the employee fills the self-review")
        if any(not 1 <= v <= 5 for v in body.self_ratings.values()):
            raise HTTPException(400, "Ratings are 1 to 5")
        r.self_ratings = body.self_ratings
        r.self_rating = round(sum(body.self_ratings.values()) / max(len(body.self_ratings), 1))
        r.status = "pending_manager"
    if body.manager_rating is not None:
        if not (is_manager_of(db, user, r.employee_id) or has(user, "performance.manage")):
            raise HTTPException(403, "Only the manager rates")
        r.manager_rating, r.manager_comment, r.status = body.manager_rating, body.manager_comment, "pending_calibration"
    if body.final_rating is not None:
        require(user, "performance.review")
        r.final_rating, r.status = body.final_rating, "done"
    record(db, user.email, "review_updated", "review", r.id, after=row(r, ["status", "self_rating", "manager_rating", "final_rating"]), employee_id=r.employee_id)
    db.commit()
    return row(r)


@router.get("/performance/cycles/{cycle_id}/increments")
def increments(cycle_id: int, user: User, db: DB, effective_from: date | None = None) -> list[dict]:
    """Merit-matrix proposals from final ratings and position in the grade pay band."""
    require(user, "performance.manage")
    eff = effective_from or date(date.today().year + 1, 4, 1)
    existing = {i.employee_id: i for i in db.scalars(select(m.Increment).where(m.Increment.cycle_id == cycle_id))}
    grades = {g.id: g for g in db.scalars(select(m.Grade))}
    lk = Lookups(db)
    out = []
    for r in db.scalars(select(m.Review).where(m.Review.cycle_id == cycle_id, m.Review.final_rating.is_not(None))):
        e = db.get(m.Employee, r.employee_id)
        st = in_force(db, m.SalaryStructure, e.id, date.today())
        gross = st[0].monthly_gross if st else D(0)
        g = grades.get(e.grade_id or 0)
        pos = 1
        if g and g.max_gross > g.min_gross:
            frac = (gross - g.min_gross) / (g.max_gross - g.min_gross)
            pos = 0 if frac < D("0.34") else 1 if frac < D("0.67") else 2
        suggested = MERIT.get(r.final_rating or 3, MERIT[3])[pos]
        inc = existing.get(e.id)
        out.append({**employee_summary(e, lk), "rating": r.final_rating, "band_position": ["low", "middle", "high"][pos], "current_gross": str(gross),
                    "suggested_pct": suggested, "pct": str(inc.pct) if inc else str(suggested), "status": inc.status if inc else "proposed",
                    "increment_id": inc.id if inc else None, "effective_from": (inc.effective_from if inc else eff).isoformat()})
    return out


class IncIn(BaseModel):
    employee_id: int
    pct: Decimal
    effective_from: date


@router.post("/performance/cycles/{cycle_id}/increments")
def increment_hr(cycle_id: int, items: list[IncIn], user: User, db: DB) -> dict:
    require(user, "performance.manage")
    for it in items:
        inc = db.scalar(select(m.Increment).where(m.Increment.cycle_id == cycle_id, m.Increment.employee_id == it.employee_id))
        if inc and inc.status in ("gm_approved", "applied"):
            continue
        if not inc:
            inc = m.Increment(cycle_id=cycle_id, employee_id=it.employee_id, pct=it.pct, effective_from=it.effective_from)
            db.add(inc)
        inc.pct, inc.effective_from, inc.status, inc.hr_by = it.pct, it.effective_from, "hr_approved", user.email
        record(db, user.email, "increment_hr_approved", "increment", it.employee_id, after={"pct": it.pct, "from": it.effective_from}, employee_id=it.employee_id)
    db.commit()
    return {"approved": len(items)}


@router.post("/performance/increments/{inc_id}/gm")
def increment_gm(inc_id: int, approve: bool, user: User, db: DB) -> dict:
    """GM sign-off. The new salary becomes a dated structure: payroll uses it from the effective date."""
    require(user, "increments.gm")
    inc = db.get(m.Increment, inc_id)
    if not inc or inc.status != "hr_approved":
        raise HTTPException(409, "Needs HR approval first")
    if not approve:
        inc.status = "proposed"
    else:
        st = in_force(db, m.SalaryStructure, inc.employee_id, inc.effective_from - timedelta(days=1)) or in_force(db, m.SalaryStructure, inc.employee_id, date.today())
        if not st:
            raise HTTPException(400, "No salary structure to increase")
        factor = 1 + inc.pct / 100
        comps = {k: str((D(v) * factor).quantize(D("1"))) for k, v in st[0].components.items()}
        close_dated(db, m.SalaryStructure, inc.employee_id, inc.effective_from)
        db.add(m.SalaryStructure(employee_id=inc.employee_id, effective_from=inc.effective_from, components=comps,
                                 monthly_gross=sum((D(v) for v in comps.values()), D(0)), source="increment"))
        inc.status, inc.gm_by = "applied", user.email
    record(db, user.email, "increment_" + inc.status, "increment", inc.id, after={"pct": inc.pct}, employee_id=inc.employee_id)
    db.commit()
    return row(inc)


# ---------------------------------------------------------------- reports (static, ready-made)
REPORTS = {
    "headcount": "Headcount by location and department",
    "joiners_leavers": "Joiners and leavers (last 12 months)",
    "attendance_month": "Attendance summary for a month",
    "ot_by_department": "OT hours by department for a month",
    "payroll_register": "Payroll register totals by entity",
    "leave_balances": "Leave balances",
    "documents_expiring": "Documents expiring",
    "birthdays": "Birthdays and work anniversaries this month",
}


def _report(db: DB, user: User, key: str, period: str | None) -> tuple[list[str], list[list[Any]]]:
    emp_ids = scope_employees(select(m.Employee.id), user)
    lk = Lookups(db)
    today = date.today()
    period = period or today.strftime("%Y-%m")
    y, mo = int(period[:4]), int(period[5:7])
    start = date(y, mo, 1)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    if key == "headcount":
        rows = db.execute(select(m.Employee.location_id, m.Employee.department_id, func.count()).where(m.Employee.id.in_(emp_ids), m.Employee.status != "exited")
                          .group_by(m.Employee.location_id, m.Employee.department_id)).all()
        return ["Location", "Department", "Headcount"], sorted([[lk.loc[a].name, lk.dept.get(b), c] for a, b, c in rows])
    if key == "joiners_leavers":
        since = today - timedelta(days=365)
        j = db.scalars(select(m.Employee).where(m.Employee.id.in_(emp_ids), m.Employee.doj >= since)).all()
        lv = db.scalars(select(m.Employee).where(m.Employee.id.in_(emp_ids), m.Employee.dol.is_not(None), m.Employee.dol >= since)).all()
        return ["Type", "Code", "Name", "Location", "Date"], [["Joiner", e.code, e.first_name, lk.loc[e.location_id].name, e.doj.isoformat()] for e in j] + \
            [["Leaver", e.code, e.first_name, lk.loc[e.location_id].name, e.dol.isoformat()] for e in lv]
    if key == "attendance_month":
        rows = db.execute(select(m.AttendanceDay.employee_id, m.AttendanceDay.status, func.count()).where(m.AttendanceDay.employee_id.in_(emp_ids),
                          m.AttendanceDay.work_date >= start, m.AttendanceDay.work_date <= end).group_by(m.AttendanceDay.employee_id, m.AttendanceDay.status)).all()
        agg: dict[int, dict[str, int]] = {}
        for eid, st, c in rows:
            agg.setdefault(eid, {})[st] = c
        emps = {e.id: e for e in db.scalars(select(m.Employee).where(m.Employee.id.in_(list(agg) or [-1])))}
        cols = ["present", "absent", "missed_punch", "leave", "weekly_off", "holiday"]
        return ["Code", "Name", "Location", *[c.replace("_", " ").title() for c in cols]], \
            [[emps[k].code, emps[k].first_name, lk.loc[emps[k].location_id].name, *[v.get(c, 0) for c in cols]] for k, v in sorted(agg.items(), key=lambda kv: emps[kv[0]].code)]
    if key == "ot_by_department":
        rows = db.execute(select(m.Employee.location_id, m.Employee.department_id, func.sum(m.AttendanceDay.ot_minutes))
                          .join(m.Employee, m.Employee.id == m.AttendanceDay.employee_id)
                          .where(m.AttendanceDay.employee_id.in_(emp_ids), m.AttendanceDay.work_date >= start, m.AttendanceDay.work_date <= end, m.AttendanceDay.ot_approved.is_(True))
                          .group_by(m.Employee.location_id, m.Employee.department_id)).all()
        return ["Location", "Department", "Approved OT hours"], sorted([[lk.loc[a].name, lk.dept.get(b), round((c or 0) / 60, 1)] for a, b, c in rows])
    if key == "payroll_register":
        require(user, "payroll.read")
        rs = db.scalars(select(m.PayrollRun).where(m.PayrollRun.period == period)).all()
        return ["Entity", "Period", "Status", "Headcount", "Gross", "Net", "PF", "ESI", "TDS"], \
            [[lk.ent[r.entity_id].code, r.period, r.status, r.totals.get("headcount"), r.totals.get("gross"), r.totals.get("net"), r.totals.get("PF", "0"),
              r.totals.get("ESI", "0"), r.totals.get("TDS", "0")] for r in rs]
    if key == "leave_balances":
        rows = db.execute(select(m.Employee, m.LeaveBalance).join(m.LeaveBalance, m.LeaveBalance.employee_id == m.Employee.id)
                          .where(m.Employee.id.in_(emp_ids), m.LeaveBalance.year == y).order_by(m.Employee.code)).all()
        return ["Code", "Name", "Leave", "Opening", "Used", "Available"], [[e.code, e.first_name, b.leave_code, str(b.opening), str(b.used), str(b.opening - b.used)] for e, b in rows]
    if key == "documents_expiring":
        soon = today + timedelta(days=int(policy(db, "doc_expiry_alert_days") or 30))
        rows = db.execute(select(m.Employee, m.EmployeeDocument).join(m.EmployeeDocument, m.EmployeeDocument.employee_id == m.Employee.id)
                          .where(m.Employee.id.in_(emp_ids), m.EmployeeDocument.expiry_date.is_not(None), m.EmployeeDocument.expiry_date <= soon)
                          .order_by(m.EmployeeDocument.expiry_date)).all()
        return ["Code", "Name", "Location", "Document", "Expiry"], [[e.code, e.first_name, lk.loc[e.location_id].name, d.doc_type, d.expiry_date.isoformat()] for e, d in rows]
    if key == "birthdays":
        emps = db.scalars(select(m.Employee).where(m.Employee.id.in_(emp_ids), m.Employee.status != "exited")).all()
        out = [["Birthday", e.code, e.first_name, lk.loc[e.location_id].name, e.dob.strftime("%d-%b")] for e in emps if e.dob and e.dob.month == mo]
        out += [["Anniversary", e.code, e.first_name, lk.loc[e.location_id].name, f"{e.doj:%d-%b} ({y - e.doj.year} yrs)"] for e in emps
                if e.doj.month == mo and e.doj.year < y]
        return ["Type", "Code", "Name", "Location", "Date"], out
    raise HTTPException(404, "Unknown report")


@router.get("/reports")
def reports_list(user: User) -> dict:
    require(user, "reports.read")
    return REPORTS


@router.get("/reports/{key}")
def report(key: str, user: User, db: DB, period: str | None = None, fmt: str = "json") -> Any:
    require(user, "reports.read")
    cols, rows = _report(db, user, key, period)
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(cols)
        w.writerows(rows)
        return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{key}-{period or "current"}.csv"'})
    return {"key": key, "title": REPORTS.get(key), "columns": cols, "rows": rows}


# ---------------------------------------------------------------- circulars and wishes
class CircularIn(BaseModel):
    title: str
    body: dict[str, str]  # en (required), ta, hi
    entity_ids: list[int] = []
    location_ids: list[int] = []
    department_ids: list[int] = []


@router.get("/circulars")
def circulars(user: User, db: DB) -> list[dict]:
    out = []
    for c in db.scalars(select(m.Circular).order_by(m.Circular.id.desc()).limit(100)):
        reads = db.scalar(select(func.count(m.CircularRead.id)).where(m.CircularRead.circular_id == c.id)) or 0
        out.append(row(c, reads=reads))
    return out


@router.post("/circulars")
def circular_send(body: CircularIn, user: User, db: DB) -> dict:
    require(user, "comms.send")
    if not body.body.get("en"):
        raise HTTPException(400, "English text is required; other languages are checked by a native speaker before sending")
    stmt = select(m.Employee).where(m.Employee.status != "exited")
    if body.location_ids:
        stmt = stmt.where(m.Employee.location_id.in_(body.location_ids))
    if body.entity_ids:
        stmt = stmt.where(m.Employee.location_id.in_(select(m.Location.id).where(m.Location.entity_id.in_(body.entity_ids))))
    if body.department_ids:
        stmt = stmt.where(m.Employee.department_id.in_(body.department_ids))
    from datetime import datetime, timezone

    c = m.Circular(title=body.title, body=body.body, audience={"entity_ids": body.entity_ids, "location_ids": body.location_ids,
                                                                "department_ids": body.department_ids}, sent_at=datetime.now(timezone.utc), sent_by=user.email)
    db.add(c)
    db.flush()
    n = 0
    for e in db.scalars(stmt):
        text_ = body.body.get(e.language) or body.body["en"]
        queue_message(db, to=e.phone, template="circular", employee_id=e.id, payload={"circular_id": c.id, "title": body.title, "text": text_})
        n += 1
    c.recipients = n
    record(db, user.email, "circular_sent", "circular", c.id, after={"title": body.title, "recipients": n})
    db.commit()
    return row(c)


@router.post("/circulars/{circular_id}/read")
def circular_read(circular_id: int, user: User, db: DB) -> dict:
    if not user.employee_id:
        raise HTTPException(400, "Only employees mark circulars read")
    if not db.scalar(select(m.CircularRead.id).where(m.CircularRead.circular_id == circular_id, m.CircularRead.employee_id == user.employee_id)):
        db.add(m.CircularRead(circular_id=circular_id, employee_id=user.employee_id))
        db.commit()
    return {"ok": True}


@router.post("/wishes/today")
def wishes(user: User, db: DB) -> dict:
    """Queue birthday and work-anniversary wishes for today (run daily by a scheduler)."""
    require(user, "comms.send")
    t = date.today()
    n = 0
    for e in db.scalars(select(m.Employee).where(m.Employee.status != "exited")):
        if e.dob and (e.dob.month, e.dob.day) == (t.month, t.day):
            queue_message(db, to=e.phone, template="birthday", employee_id=e.id, payload={"name": e.first_name, "language": e.language})
            n += 1
        if (e.doj.month, e.doj.day) == (t.month, t.day) and e.doj.year < t.year:
            queue_message(db, to=e.phone, template="anniversary", employee_id=e.id, payload={"name": e.first_name, "years": t.year - e.doj.year, "language": e.language})
            n += 1
    db.commit()
    return {"queued": n}


@router.get("/outbox")
def outbox(user: User, db: DB) -> list[dict]:
    require(user, "comms.send")
    return [row(o) for o in db.scalars(select(m.Outbox).order_by(m.Outbox.id.desc()).limit(200))]


# ---------------------------------------------------------------- approvals inbox
@router.get("/approvals")
def approvals(user: User, db: DB) -> dict:
    lk = Lookups(db)
    items: list[dict] = []
    hr = has(user, "employees.write")
    team = set(db.scalars(select(m.Employee.id).where(m.Employee.manager_id == (user.employee_id or -1))))
    emp = lambda eid: employee_summary(db.get(m.Employee, eid), lk)  # noqa: E731
    for r in db.scalars(select(m.LeaveRequest).where(m.LeaveRequest.status.in_(["pending_hod", "pending_hr"]))):
        if (r.status == "pending_hod" and (r.employee_id in team or hr)) or (r.status == "pending_hr" and hr):
            items.append({"type": "leave", "id": r.id, "employee": emp(r.employee_id), "summary": f"{r.leave_code} {r.from_date} to {r.to_date} ({r.days} d)",
                          "detail": r.reason, "status": r.status, "created_at": r.created_at.isoformat()})
    for r in db.scalars(select(m.Regularisation).where(m.Regularisation.status == "pending")):
        if r.employee_id in team or has(user, "attendance.manage"):
            items.append({"type": "regularisation", "id": r.id, "employee": emp(r.employee_id), "summary": f"{r.kind.replace('_', ' ')} on {r.work_date}",
                          "detail": f"{r.in_time or ''}–{r.out_time or ''} {r.reason or ''}", "status": r.status, "created_at": r.created_at.isoformat()})
    if has(user, "attendance.approve"):
        q = select(m.AttendanceDay).where(m.AttendanceDay.ot_minutes > 0, m.AttendanceDay.ot_approved.is_(False), m.AttendanceDay.locked.is_(False))
        if not has(user, "attendance.manage"):
            q = q.where(m.AttendanceDay.employee_id.in_(list(team) or [-1]))
        for d in db.scalars(q.order_by(m.AttendanceDay.work_date.desc()).limit(200)):
            items.append({"type": "ot", "id": d.id, "employee": emp(d.employee_id), "summary": f"OT {d.ot_minutes // 60}h{d.ot_minutes % 60:02d} on {d.work_date}",
                          "detail": "", "status": "pending", "created_at": d.work_date.isoformat()})
    if hr:
        for c in db.scalars(select(m.ChangeRequest).where(m.ChangeRequest.status == "pending")):
            items.append({"type": "change_request", "id": c.id, "employee": emp(c.employee_id), "summary": f"Change {c.field.replace('_', ' ')}",
                          "detail": c.reason, "status": "pending", "created_at": c.created_at.isoformat()})
        for x in db.scalars(select(m.ExitCase).where(m.ExitCase.status == "fnf_calculated")):
            items.append({"type": "fnf", "id": x.id, "employee": emp(x.employee_id), "summary": f"F&F net {(x.fnf or {}).get('net')} due {x.fnf_due_on}",
                          "detail": "", "status": x.status, "created_at": x.created_at.isoformat()})
    for r in db.scalars(select(m.PayrollRun).where(m.PayrollRun.status.in_(["reviewed", "hr_approved", "finance_approved"]))):
        if (r.status == "reviewed" and has(user, "payroll.approve_hr")) or (r.status in ("hr_approved", "finance_approved") and has(user, "payroll.approve_finance")):
            items.append({"type": "payroll", "id": r.id, "employee": None, "summary": f"Payroll {lk.ent[r.entity_id].code} {r.period}: {r.status.replace('_', ' ')}",
                          "detail": f"Net {r.totals.get('net')}", "status": r.status, "created_at": r.created_at.isoformat()})
    if has(user, "increments.gm"):
        for i in db.scalars(select(m.Increment).where(m.Increment.status == "hr_approved")):
            items.append({"type": "increment", "id": i.id, "employee": emp(i.employee_id), "summary": f"Increment {i.pct}% from {i.effective_from}",
                          "detail": f"HR: {i.hr_by}", "status": i.status, "created_at": i.effective_from.isoformat()})
    return {"count": len(items), "items": items}


# ---------------------------------------------------------------- self-service
class ChangeIn(BaseModel):
    field: str
    new_value: str
    reason: str | None = None


@router.get("/me/profile")
def my_profile(user: User, db: DB) -> dict:
    if not user.employee_id:
        raise HTTPException(404, "Your user is not linked to an employee record")
    d = employee_detail(db, db.get(m.Employee, user.employee_id), user, Lookups(db))
    d["change_requests"] = [row(x, ["id", "field", "status", "reason", "created_at"]) for x in db.scalars(
        select(m.ChangeRequest).where(m.ChangeRequest.employee_id == user.employee_id).order_by(m.ChangeRequest.created_at.desc()))]
    return d


@router.post("/me/change-requests")
def my_change(body: ChangeIn, user: User, db: DB) -> dict:
    allowed = {"bank_account", "ifsc", "bank_name", "phone", "email", "address", "language", "pan"}
    if not user.employee_id or body.field not in allowed:
        raise HTTPException(400, f"You can request changes to: {', '.join(sorted(allowed))}")
    c = m.ChangeRequest(employee_id=user.employee_id, field=body.field, new_value=body.new_value.strip(), reason=body.reason, requested_by=user.email)
    db.add(c)
    db.flush()
    record(db, user.email, "change_requested", "employee", user.employee_id, after={"field": body.field}, employee_id=user.employee_id)
    db.commit()
    return row(c, new_value="***" if body.field in ("bank_account", "pan") else c.new_value)


@router.get("/me/payslips")
def my_payslips(user: User, db: DB) -> list[dict]:
    if not user.employee_id:
        return []
    rows = db.execute(select(m.PayrollRun, m.PayrollLine).join(m.PayrollLine, m.PayrollLine.run_id == m.PayrollRun.id)
                      .where(m.PayrollLine.employee_id == user.employee_id, m.PayrollRun.status == "locked").order_by(m.PayrollRun.period.desc())).all()
    return [{"run_id": r.id, "period": r.period, "entity_id": r.entity_id, "gross": str(ln.gross), "net": str(ln.net), "earnings": ln.earnings,
             "deductions": ln.deductions, "paid_days": str(ln.paid_days)} for r, ln in rows]


@router.get("/me/attendance")
def my_attendance(user: User, db: DB, year: int, month: int) -> list[dict]:
    if not user.employee_id:
        return []
    start = date(year, month, 1)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return [row(d) for d in db.scalars(select(m.AttendanceDay).where(m.AttendanceDay.employee_id == user.employee_id, m.AttendanceDay.work_date >= start,
                                                                      m.AttendanceDay.work_date <= end).order_by(m.AttendanceDay.work_date))]


@router.get("/me/exit")
def my_exit(user: User, db: DB) -> dict | None:
    x = db.scalar(select(m.ExitCase).where(m.ExitCase.employee_id == (user.employee_id or -1)).order_by(m.ExitCase.id.desc()))
    return row(x, ["id", "resigned_on", "last_working_day", "status", "fnf_due_on"]) if x else None


# ---------------------------------------------------------------- audit
@router.get("/audit")
def audit(user: User, db: DB, entity_type: str | None = None, actor: str | None = None, q: str | None = None, limit: int = 200) -> list[dict]:
    require(user, "audit.read")
    stmt = select(m.AuditLog).order_by(m.AuditLog.id.desc()).limit(min(limit, 1000))
    if entity_type:
        stmt = stmt.where(m.AuditLog.entity_type == entity_type)
    if actor:
        stmt = stmt.where(m.AuditLog.actor.ilike(f"%{actor}%"))
    if q:
        stmt = stmt.where(or_(m.AuditLog.action.ilike(f"%{q}%"), m.AuditLog.entity_id == q))
    return [row(a) for a in db.scalars(stmt)]
