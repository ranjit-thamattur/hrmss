from __future__ import annotations

import io
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select

from .. import models as m
from ..deps import DB, User
from ..domain.fnf import FnfInput, calculate_fnf, last_working_day
from ..serial import Lookups, employee_summary, row
from ..services.access import has, require
from ..services.audit import record
from ..services.employees import in_force
from ..services.payroll import period_bounds
from ..services.policies import policy
from ..services.provisioning import queue

router = APIRouter(prefix="/api", tags=["statutory and exit"])
D = Decimal


# ---------------------------------------------------------------- compliance calendar
def _calendar(db: DB, months_back: int = 6) -> list[dict]:
    items: list[dict] = []
    challans = {c.item_key: c for c in db.scalars(select(m.StatutoryChallan))}
    today = date.today()
    ents = {e.id: e for e in db.scalars(select(m.Entity))}
    for r in db.scalars(select(m.PayrollRun).where(m.PayrollRun.status == "locked").order_by(m.PayrollRun.period.desc()).limit(36)):
        _, end, _ = period_bounds(r.period)
        nxt = end + timedelta(days=1)
        t = r.totals or {}
        ent = ents[r.entity_id]
        for law, day, amount in (("TDS", 7, D(t.get("TDS", "0"))),
                                 ("EPF", 15, sum((D(t.get(k, "0")) for k in ("PF", "EPF_ER", "EPS", "EDLI", "PF_ADMIN")), D(0))),
                                 ("ESI", 15, D(t.get("ESI", "0")) + D(t.get("ESI_ER", "0")))):
            if not amount:
                continue
            items.append({"key": f"{law}:{ent.code}:{r.period}", "law": law, "entity": ent.code, "period": r.period, "due": nxt.replace(day=day), "amount": amount})
        if end.month in (9, 3) and D(t.get("PT", "0")):
            items.append({"key": f"PT:{ent.code}:{r.period}", "law": "PT", "entity": ent.code, "period": r.period, "due": end, "amount": D(t["PT"])})
        if end.month == 12 and D(t.get("LWF", "0")):
            items.append({"key": f"LWF:{ent.code}:{end.year}", "law": "LWF", "entity": ent.code, "period": str(end.year),
                          "due": date(end.year + 1, 1, 31), "amount": D(t["LWF"]) + D(t.get("LWF_ER", "0"))})
    for i in items:
        c = challans.get(i["key"])
        i["status"] = "paid" if c else ("overdue" if i["due"] < today else "due")
        i["challan"] = row(c) if c else None
        i["due"] = i["due"].isoformat()
        i["amount"] = str(i["amount"])
    return sorted(items, key=lambda x: (x["status"] != "overdue", x["due"]))


@router.get("/statutory/calendar")
def calendar(user: User, db: DB) -> list[dict]:
    require(user, "statutory.manage")
    return _calendar(db)


class ChallanIn(BaseModel):
    item_key: str
    challan_no: str
    paid_on: date
    amount: Decimal | None = None


@router.post("/statutory/challans")
def challan(body: ChallanIn, user: User, db: DB) -> dict:
    require(user, "statutory.manage")
    if db.scalar(select(m.StatutoryChallan.id).where(m.StatutoryChallan.item_key == body.item_key)):
        raise HTTPException(409, "Challan already entered for this item")
    c = m.StatutoryChallan(item_key=body.item_key, challan_no=body.challan_no.strip(), paid_on=body.paid_on, amount=body.amount, entered_by=user.email)
    db.add(c)
    db.flush()
    record(db, user.email, "challan_entered", "statutory", body.item_key, after=row(c))
    db.commit()
    return row(c)


@router.get("/statutory/applicability")
def applicability(user: User, db: DB) -> list[dict]:
    require(user, "statutory.manage")
    return [{"entity": e.code, "name": e.name, "state": e.state, "statutory": e.statutory, "pf_code": e.pf_code, "esi_code": e.esi_code} for e in db.scalars(select(m.Entity))]


# ---------------------------------------------------------------- exit
CLEARANCE = [("HOD", "Handover of duties and keys", "Department head"), ("Housekeeping", "Uniforms returned", "Linen room"),
             ("Security", "Locker key and ID card", "Security"), ("Accounts", "Loans and advances confirmed", "Accounts"),
             ("IT / Engineering", "System, POS and Wi-Fi access removed", "Engineering"), ("HR", "Exit interview", "HR")]


class ResignIn(BaseModel):
    employee_id: int | None = None
    resigned_on: date | None = None
    reason: str | None = None
    last_working_day: date | None = None


@router.post("/exits")
def resign(body: ResignIn, user: User, db: DB) -> dict:
    eid = body.employee_id or user.employee_id
    if not eid or (eid != user.employee_id and not has(user, "exits.manage")):
        raise HTTPException(403, "Not allowed")
    e = db.get(m.Employee, eid)
    if not e or e.status != "active":
        raise HTTPException(400, "Employee is not active")
    if db.scalar(select(m.ExitCase.id).where(m.ExitCase.employee_id == eid, m.ExitCase.status != "closed")):
        raise HTTPException(409, "An exit is already open")
    grade = db.get(m.Grade, e.grade_id) if e.grade_id else None
    notice = grade.notice_days if grade else int(policy(db, "notice_days_default") or 30)
    resigned = body.resigned_on or date.today()
    lwd = body.last_working_day if (body.last_working_day and has(user, "exits.manage")) else last_working_day(resigned, notice)
    x = m.ExitCase(employee_id=eid, resigned_on=resigned, reason=body.reason, last_working_day=lwd, created_by=user.email)
    db.add(x)
    db.flush()
    for dept, item, owner in CLEARANCE:
        db.add(m.ClearanceTask(exit_id=x.id, department=dept, item=item, owner=owner))
    e.status, e.dol = "notice", lwd
    record(db, user.email, "resigned", "exit", x.id, after={"resigned_on": resigned, "last_working_day": lwd, "reason": body.reason}, employee_id=eid)
    db.commit()
    return exit_get(x.id, user, db)


@router.get("/exits")
def exits(user: User, db: DB, status: str | None = None) -> list[dict]:
    require(user, "exits.manage")
    stmt = select(m.ExitCase).order_by(m.ExitCase.last_working_day)
    if status:
        stmt = stmt.where(m.ExitCase.status == status)
    lk = Lookups(db)
    out = []
    for x in db.scalars(stmt):
        e = db.get(m.Employee, x.employee_id)
        tasks = db.scalars(select(m.ClearanceTask).where(m.ClearanceTask.exit_id == x.id)).all()
        out.append(row(x, ["id", "resigned_on", "last_working_day", "status", "fnf_due_on"], employee=employee_summary(e, lk),
                       clearance_done=sum(1 for t in tasks if t.status == "done"), clearance_total=len(tasks)))
    return out


@router.get("/exits/{exit_id}")
def exit_get(exit_id: int, user: User, db: DB) -> dict:
    x = db.get(m.ExitCase, exit_id)
    if not x or (x.employee_id != user.employee_id and not has(user, "exits.manage")):
        raise HTTPException(404, "Not found")
    e = db.get(m.Employee, x.employee_id)
    return row(x, employee=employee_summary(e, Lookups(db)), clearance=[row(t) for t in db.scalars(select(m.ClearanceTask).where(m.ClearanceTask.exit_id == x.id))])


@router.post("/exits/{exit_id}/clearance/{task_id}")
def clearance_done(exit_id: int, task_id: int, done: bool, user: User, db: DB) -> dict:
    require(user, "exits.manage")
    t = db.get(m.ClearanceTask, task_id)
    if not t or t.exit_id != exit_id:
        raise HTTPException(404, "Not found")
    t.status, t.done_by = ("done" if done else "pending"), user.email
    x = db.get(m.ExitCase, exit_id)
    record(db, user.email, "clearance_" + t.status, "exit", exit_id, after={"item": t.item}, employee_id=x.employee_id)
    db.commit()
    return row(t)


class FnfIn(BaseModel):
    el_balance_days: Decimal | None = None
    loan_balance: Decimal = D(0)
    advance_balance: Decimal = D(0)
    other_earnings: dict[str, Decimal] = {}
    other_deductions: dict[str, Decimal] = {}
    notice_waived: bool = False


@router.post("/exits/{exit_id}/fnf")
def fnf(exit_id: int, body: FnfIn, user: User, db: DB) -> dict:
    """F&F reuses salary structure, leave balance and the loan/advance figures."""
    require(user, "exits.manage")
    x = db.get(m.ExitCase, exit_id)
    if not x or x.status in ("fnf_approved", "closed"):
        raise HTTPException(409, "F&F is already approved")
    e = db.get(m.Employee, x.employee_id)
    st = in_force(db, m.SalaryStructure, e.id, x.last_working_day)
    if not st:
        raise HTTPException(400, "No salary structure in force on the last working day")
    comps = {k: D(v) for k, v in st[0].components.items()}
    el = body.el_balance_days
    if el is None:
        b = db.scalar(select(m.LeaveBalance).where(m.LeaveBalance.employee_id == e.id, m.LeaveBalance.leave_code == "EL", m.LeaveBalance.year == x.last_working_day.year))
        el = (b.opening - b.used) if b else D(0)
    lwd = x.last_working_day
    import calendar as cal

    dim = cal.monthrange(lwd.year, lwd.month)[1]
    holidays = set(db.scalars(select(m.Holiday.day).where(m.Holiday.day > lwd, m.Holiday.day <= lwd + timedelta(days=14))))
    grade = db.get(m.Grade, e.grade_id) if e.grade_id else None
    res = calculate_fnf(FnfInput(monthly_gross=sum(comps.values(), D(0)), monthly_basic=comps.get("BASIC", D(0)) + comps.get("DA", D(0)), doj=e.doj,
                                 resigned_on=x.resigned_on, last_working_day=lwd, notice_days=grade.notice_days if grade else 30, days_in_month=dim,
                                 days_worked_in_last_month=lwd.day, el_balance_days=D(str(el)), loan_balance=body.loan_balance,
                                 advance_balance=body.advance_balance, other_earnings=body.other_earnings, other_deductions=body.other_deductions,
                                 notice_waived=body.notice_waived), holidays)
    x.fnf, x.fnf_due_on, x.status = res.as_dict(), res.due_on, "fnf_calculated"
    record(db, user.email, "fnf_calculated", "exit", x.id, after={"net": str(res.net), "due_on": res.due_on}, employee_id=e.id)
    db.commit()
    return exit_get(x.id, user, db)


@router.post("/exits/{exit_id}/fnf/approve")
def fnf_approve(exit_id: int, user: User, db: DB) -> dict:
    require(user, "exits.manage")
    x = db.get(m.ExitCase, exit_id)
    if not x or x.status != "fnf_calculated":
        raise HTTPException(409, "Calculate the F&F first")
    pending = db.scalars(select(m.ClearanceTask).where(m.ClearanceTask.exit_id == x.id, m.ClearanceTask.status != "done")).all()
    if pending:
        raise HTTPException(409, f"{len(pending)} clearance items are still pending")
    x.status, x.fnf_approved_by = "fnf_approved", user.email
    record(db, user.email, "fnf_approved", "exit", x.id, after={"net": (x.fnf or {}).get("net")}, employee_id=x.employee_id)
    db.commit()
    return exit_get(x.id, user, db)


@router.post("/exits/{exit_id}/close")
def close_exit(exit_id: int, user: User, db: DB) -> dict:
    """Last step: employee marked exited, software access and biometric access removed."""
    require(user, "exits.manage")
    x = db.get(m.ExitCase, exit_id)
    if not x or x.status != "fnf_approved":
        raise HTTPException(409, "Approve the F&F first")
    e = db.get(m.Employee, x.employee_id)
    e.status = "exited"
    u = db.scalar(select(m.AppUser).where(m.AppUser.employee_id == e.id))
    if u and u.is_active:
        u.is_active = False
        queue(db, target="identity", action="disable", user_id=u.id, employee_id=e.id, actor=user.email)
    queue(db, target="biometric", action="disable", employee_id=e.id, actor=user.email)
    x.status = "closed"
    record(db, user.email, "exit_closed", "exit", x.id, employee_id=e.id)
    db.commit()
    return exit_get(x.id, user, db)


@router.get("/exits/{exit_id}/letter/{kind}.pdf")
def letter(exit_id: int, kind: str, user: User, db: DB) -> Response:
    require(user, "exits.manage")
    x = db.get(m.ExitCase, exit_id)
    if not x or x.status not in ("fnf_approved", "closed"):
        raise HTTPException(409, "Letters are issued after the F&F is approved")
    e = db.get(m.Employee, x.employee_id)
    lk = Lookups(db)
    ent = lk.entity_of_location(e.location_id)
    name = f"{e.first_name} {e.last_name}".strip()
    if kind == "relieving":
        title = "Relieving letter"
        body = (f"This is to confirm that {name} (employee code {e.code}) worked with {ent.name} as {lk.desig.get(e.designation_id or 0, 'staff')} "
                f"from {e.doj:%d-%m-%Y} to {x.last_working_day:%d-%m-%Y}. {name} resigned on {x.resigned_on:%d-%m-%Y} and has been relieved of all duties "
                f"at the close of business on {x.last_working_day:%d-%m-%Y}. All dues have been settled.")
    elif kind == "experience":
        title = "Experience certificate"
        body = (f"This is to certify that {name} worked with {ent.name} from {e.doj:%d-%m-%Y} to {x.last_working_day:%d-%m-%Y} "
                f"in the {lk.dept.get(e.department_id)} department. We wish {name} the very best.")
    else:
        raise HTTPException(404, "Unknown letter")
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    buf = io.BytesIO()
    ss = getSampleStyleSheet()
    SimpleDocTemplate(buf, pagesize=A4).build([Paragraph(ent.name, ss["Title"]), Paragraph(title, ss["Heading2"]),
                                               Paragraph(f"Date: {date.today():%d-%m-%Y}", ss["Normal"]), Spacer(1, 12), Paragraph(body, ss["Normal"]),
                                               Spacer(1, 36), Paragraph(f"For {ent.name}<br/>HR Manager", ss["Normal"])])
    record(db, user.email, f"letter_{kind}", "exit", x.id, employee_id=e.id)
    db.commit()
    return Response(buf.getvalue(), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{kind}-{e.code}.pdf"'})
