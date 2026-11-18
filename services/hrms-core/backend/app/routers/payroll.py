"""Payroll: monthly inputs, runs, exception decisions, HR then Finance approval, lock, outputs.

Rules enforced here:
- Payroll does not run while missed punches are open and the missed-punch rule is not set.
- Every flagged line needs a decision; negative pay can never be accepted as it is.
- The preparer cannot approve the same run. Nothing locks without HR and Finance approval.
- A locked run cannot change; corrections go in the next month's run.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select, update

from .. import models as m
from ..deps import DB, User
from ..domain import outputs
from ..serial import Lookups, employee_summary, row
from ..services.access import has, require
from ..services.audit import record
from ..services.integrations import queue_message
from ..services.payroll import calculate_lines, line_view, period_bounds, refresh_totals
from ..services.security import decrypt

router = APIRouter(prefix="/api/payroll", tags=["payroll"])
D = Decimal
LOCKED = {"locked"}
EDITABLE_STATUSES = {"calculated", "reviewed"}


# ---------------------------------------------------------------- monthly inputs
class InputsIn(BaseModel):
    period: str
    rows: list[dict]  # [{employee_id, code, amount}]


@router.get("/inputs")
def inputs_get(user: User, db: DB, period: str, entity_id: int | None = None) -> dict:
    require(user, "payroll.read")
    start, end, _ = period_bounds(period)
    stmt = select(m.Employee).where(m.Employee.doj <= end).where((m.Employee.dol.is_(None)) | (m.Employee.dol >= start))
    if entity_id:
        stmt = stmt.where(m.Employee.location_id.in_(select(m.Location.id).where(m.Location.entity_id == entity_id)))
    emps = db.scalars(stmt.order_by(m.Employee.code)).all()
    vals: dict[int, dict[str, str]] = {}
    for i in db.scalars(select(m.MonthlyInput).where(m.MonthlyInput.period == period)):
        vals.setdefault(i.employee_id, {})[i.code] = str(i.amount)
    locked = db.scalar(select(m.PayrollRun.id).where(m.PayrollRun.period == period, m.PayrollRun.status == "locked",
                                                     *( [m.PayrollRun.entity_id == entity_id] if entity_id else []))) is not None
    lk = Lookups(db)
    return {"period": period, "locked": locked, "items": [{**employee_summary(e, lk), "inputs": vals.get(e.id, {})} for e in emps]}


@router.put("/inputs")
def inputs_put(body: InputsIn, user: User, db: DB) -> dict:
    require(user, "payroll.prepare")
    period_bounds(body.period)
    n = 0
    for r in body.rows:
        eid, code = int(r["employee_id"]), str(r["code"]).upper()
        amt = D(str(r.get("amount") or 0))
        existing = db.scalar(select(m.MonthlyInput).where(m.MonthlyInput.period == body.period, m.MonthlyInput.employee_id == eid, m.MonthlyInput.code == code))
        if amt == 0:
            if existing:
                db.delete(existing)
        elif existing:
            existing.amount = amt
        else:
            db.add(m.MonthlyInput(period=body.period, employee_id=eid, code=code, amount=amt))
        n += 1
    record(db, user.email, "monthly_inputs_saved", "payroll_inputs", body.period, after={"values": n})
    db.commit()
    return {"saved": n}


# ---------------------------------------------------------------- runs
class RunIn(BaseModel):
    entity_id: int
    period: str


def _run(db: DB, run_id: int) -> m.PayrollRun:
    r = db.get(m.PayrollRun, run_id)
    if not r:
        raise HTTPException(404, "Payroll run not found")
    return r


def _run_view(db: DB, r: m.PayrollRun, with_lines: bool = False) -> dict:
    ent = db.get(m.Entity, r.entity_id)
    d = row(r, ["id", "entity_id", "period", "run_no", "status", "missed_punch_rule", "steps", "totals", "prepared_by", "hr_approved_by",
                "finance_approved_by", "locked_by", "locked_at", "payslips_published", "created_at"])
    d["entity"] = {"code": ent.code, "name": ent.name}
    d["rule_version"] = (r.rules or {}).get("version")
    if with_lines:
        lines = db.scalars(select(m.PayrollLine).where(m.PayrollLine.run_id == r.id)).all()
        emps = {e.id: e for e in db.scalars(select(m.Employee).where(m.Employee.id.in_([ln.employee_id for ln in lines] or [-1])))}
        d["lines"] = sorted((line_view(ln, emps[ln.employee_id]) for ln in lines), key=lambda x: (not x["flags"], x["code"]))
    return d


@router.get("/runs")
def runs(user: User, db: DB, period: str | None = None) -> list[dict]:
    require(user, "payroll.read")
    stmt = select(m.PayrollRun).order_by(m.PayrollRun.period.desc(), m.PayrollRun.entity_id)
    if period:
        stmt = stmt.where(m.PayrollRun.period == period)
    return [_run_view(db, r) for r in db.scalars(stmt.limit(100))]


@router.post("/runs")
def run_create(body: RunIn, user: User, db: DB) -> dict:
    require(user, "payroll.prepare")
    period_bounds(body.period)
    if not db.get(m.Entity, body.entity_id):
        raise HTTPException(404, "Entity not found")
    existing = db.scalars(select(m.PayrollRun).where(m.PayrollRun.entity_id == body.entity_id, m.PayrollRun.period == body.period)).all()
    if any(r.status == "locked" for r in existing):
        raise HTTPException(409, "This month is locked for this entity. Corrections go in next month's run.")
    if existing:
        raise HTTPException(409, f"A run already exists (#{existing[0].id}). Open it and recalculate.")
    r = m.PayrollRun(entity_id=body.entity_id, period=body.period, prepared_by=user.email, rules={}, steps=[])
    db.add(r)
    db.flush()
    calculate_lines(db, r)
    record(db, user.email, "payroll_run_created", "payroll_run", r.id, after={"entity_id": r.entity_id, "period": r.period, "totals": r.totals})
    db.commit()
    return _run_view(db, r, True)


@router.get("/runs/{run_id}")
def run_get(run_id: int, user: User, db: DB) -> dict:
    require(user, "payroll.read")
    return _run_view(db, _run(db, run_id), True)


@router.post("/runs/{run_id}/recalculate")
def run_recalc(run_id: int, user: User, db: DB) -> dict:
    require(user, "payroll.prepare")
    r = _run(db, run_id)
    if r.status not in EDITABLE_STATUSES:
        raise HTTPException(409, f"Run is {r.status}; send it back before recalculating")
    r.steps = []
    calculate_lines(db, r)
    record(db, user.email, "payroll_recalculated", "payroll_run", r.id, after={"totals": r.totals})
    db.commit()
    return _run_view(db, r, True)


class DecisionIn(BaseModel):
    decision: str  # accept | hold | release
    note: str | None = None


@router.post("/lines/{line_id}/decide")
def line_decide(line_id: int, body: DecisionIn, user: User, db: DB) -> dict:
    require(user, "payroll.prepare")
    ln = db.get(m.PayrollLine, line_id)
    if not ln:
        raise HTTPException(404, "Line not found")
    r = _run(db, ln.run_id)
    if r.status not in EDITABLE_STATUSES:
        raise HTTPException(409, "Run is approved or locked")
    if body.decision == "accept" and any(f["code"] == "NEGATIVE_NET" for f in ln.flags):
        raise HTTPException(400, "Negative pay cannot be approved as it is: change the inputs (e.g. spread the recovery) or hold the line.")
    if body.decision not in ("accept", "hold", "release"):
        raise HTTPException(400, "decision must be accept, hold or release")
    if body.decision in ("accept", "hold") and ln.flags and not (body.note or "").strip() and any(f["severity"] == "block" for f in ln.flags):
        raise HTTPException(400, "Add a note for a blocking flag")
    ln.decision = None if body.decision == "release" else body.decision
    ln.hold = body.decision == "hold"
    ln.decision_note, ln.decided_by = body.note, user.email
    if r.status == "reviewed":
        r.status = "calculated"
    refresh_totals(db, r)
    record(db, user.email, f"payroll_line_{body.decision}", "payroll_line", ln.id, after={"note": body.note, "flags": [f["code"] for f in ln.flags]},
           employee_id=ln.employee_id)
    db.commit()
    e = db.get(m.Employee, ln.employee_id)
    return line_view(ln, e)


@router.post("/runs/{run_id}/submit")
def run_submit(run_id: int, user: User, db: DB) -> dict:
    require(user, "payroll.prepare")
    r = _run(db, run_id)
    if r.status != "calculated":
        raise HTTPException(409, f"Run is {r.status}")
    undecided = db.scalars(select(m.PayrollLine).where(m.PayrollLine.run_id == r.id, m.PayrollLine.decision.is_(None))).all()
    undecided = [ln for ln in undecided if ln.flags]
    if undecided:
        raise HTTPException(409, f"{len(undecided)} flagged lines still need a decision")
    r.status = "reviewed"
    record(db, user.email, "payroll_submitted", "payroll_run", r.id)
    db.commit()
    return _run_view(db, r)


@router.post("/runs/{run_id}/approve-hr")
def approve_hr(run_id: int, user: User, db: DB) -> dict:
    require(user, "payroll.approve_hr")
    r = _run(db, run_id)
    if r.status != "reviewed":
        raise HTTPException(409, "Run must be reviewed first")
    if user.email == r.prepared_by:
        raise HTTPException(403, "The person who prepared this payroll cannot approve it")
    r.status, r.hr_approved_by = "hr_approved", user.email
    record(db, user.email, "payroll_hr_approved", "payroll_run", r.id, after={"net": r.totals.get("net")})
    db.commit()
    return _run_view(db, r)


@router.post("/runs/{run_id}/approve-finance")
def approve_finance(run_id: int, user: User, db: DB) -> dict:
    require(user, "payroll.approve_finance")
    r = _run(db, run_id)
    if r.status != "hr_approved":
        raise HTTPException(409, "HR approval comes first")
    if user.email in (r.prepared_by, r.hr_approved_by):
        raise HTTPException(403, "Finance approval must be by a different person from the preparer and the HR approver")
    r.status, r.finance_approved_by = "finance_approved", user.email
    record(db, user.email, "payroll_finance_approved", "payroll_run", r.id, after={"net": r.totals.get("net")})
    db.commit()
    return _run_view(db, r)


@router.post("/runs/{run_id}/send-back")
def send_back(run_id: int, note: str, user: User, db: DB) -> dict:
    if not (has(user, "payroll.approve_hr") or has(user, "payroll.approve_finance")):
        raise HTTPException(403, "Not allowed")
    r = _run(db, run_id)
    if r.status in LOCKED:
        raise HTTPException(409, "Locked runs cannot change")
    r.status, r.hr_approved_by, r.finance_approved_by = "calculated", None, None
    record(db, user.email, "payroll_sent_back", "payroll_run", r.id, after={"note": note})
    db.commit()
    return _run_view(db, r)


@router.post("/runs/{run_id}/lock")
def lock(run_id: int, user: User, db: DB) -> dict:
    require(user, "payroll.approve_finance")
    r = _run(db, run_id)
    if r.status != "finance_approved":
        raise HTTPException(409, "Nothing locks without HR and Finance approval")
    start, end, _ = period_bounds(r.period)
    emp_ids = list(db.scalars(select(m.PayrollLine.employee_id).where(m.PayrollLine.run_id == r.id)))
    db.execute(update(m.AttendanceDay).where(m.AttendanceDay.employee_id.in_(emp_ids or [-1]), m.AttendanceDay.work_date >= start,
                                             m.AttendanceDay.work_date <= end).values(locked=True))
    r.status, r.locked_by, r.locked_at = "locked", user.email, datetime.now(timezone.utc)
    record(db, user.email, "payroll_locked", "payroll_run", r.id, after={"totals": r.totals})
    db.commit()
    return _run_view(db, r)


# ---------------------------------------------------------------- outputs (locked runs only)
def _locked(db: DB, user: User, run_id: int) -> tuple[m.PayrollRun, list[tuple[m.PayrollLine, m.Employee]]]:
    require(user, "payroll.read")
    r = _run(db, run_id)
    if r.status != "locked":
        raise HTTPException(409, "Files are created only from a locked payroll")
    lines = db.scalars(select(m.PayrollLine).where(m.PayrollLine.run_id == r.id)).all()
    emps = {e.id: e for e in db.scalars(select(m.Employee).where(m.Employee.id.in_([ln.employee_id for ln in lines] or [-1])))}
    return r, [(ln, emps[ln.employee_id]) for ln in sorted(lines, key=lambda x: emps[x.employee_id].code)]


def _file(content: str | bytes, name: str, media: str) -> Response:
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/runs/{run_id}/register.csv")
def register_csv(run_id: int, user: User, db: DB) -> Response:
    require(user, "payroll.read")
    r = _run(db, run_id)
    lines = db.scalars(select(m.PayrollLine).where(m.PayrollLine.run_id == r.id)).all()
    emps = {e.id: e for e in db.scalars(select(m.Employee).where(m.Employee.id.in_([ln.employee_id for ln in lines] or [-1])))}
    e_codes = sorted({k for ln in lines for k in ln.earnings})
    d_codes = sorted({k for ln in lines for k in ln.deductions})
    r_codes = sorted({k for ln in lines for k in ln.employer})
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Code", "Name", "Paid days", "LOP days", "OT hours", *e_codes, "Gross", *d_codes, "Total deductions", "Net", *r_codes, "Share %", "Hold", "Flags"])
    for ln in sorted(lines, key=lambda x: emps[x.employee_id].code):
        e = emps[ln.employee_id]
        w.writerow([e.code, f"{e.first_name} {e.last_name}".strip(), ln.paid_days, ln.lop_days, ln.ot_hours, *[ln.earnings.get(c, "0") for c in e_codes], ln.gross,
                    *[ln.deductions.get(c, "0") for c in d_codes], ln.total_deductions, ln.net, *[ln.employer.get(c, "0") for c in r_codes], ln.share_pct,
                    "yes" if ln.hold else "", " ".join(f["code"] for f in ln.flags)])
    ent = db.get(m.Entity, r.entity_id)
    return _file(buf.getvalue(), f"register-{ent.code}-{r.period}.csv", "text/csv")


@router.get("/runs/{run_id}/bank.csv")
def bank_file(run_id: int, user: User, db: DB) -> Response:
    r, pairs = _locked(db, user, run_id)
    ent = db.get(m.Entity, r.entity_id)
    lines = [{"code": e.code, "name": f"{e.first_name} {e.last_name}".strip(), "account": decrypt(e.bank_account_enc), "ifsc": e.ifsc, "net": ln.net}
             for ln, e in pairs if not ln.hold]
    record(db, user.email, "bank_file_downloaded", "payroll_run", r.id)
    db.commit()
    return _file(outputs.bank_csv(lines, narration=f"SALARY {r.period}"), f"bank-{ent.code}-{r.period}.csv", "text/csv")


@router.get("/runs/{run_id}/tally.xml")
def tally(run_id: int, user: User, db: DB) -> Response:
    r, _ = _locked(db, user, run_id)
    ent = db.get(m.Entity, r.entity_id)
    totals = {k: D(v) for k, v in (r.totals or {}).items()}
    debits, credits = outputs.payroll_journal(totals)
    _, end, _ = period_bounds(r.period)
    xml = outputs.tally_journal_xml(company=ent.tally_company or ent.name, date_yyyymmdd=end.strftime("%Y%m%d"),
                                    narration=f"Salary for {end:%B %Y}", debits=debits, credits=credits)
    return _file(xml, f"tally-{ent.code}-{r.period}.xml", "application/xml")


@router.get("/runs/{run_id}/epf-ecr.txt")
def ecr(run_id: int, user: User, db: DB) -> Response:
    r, pairs = _locked(db, user, run_id)
    lines = []
    for ln, e in pairs:
        pf_wage = sum((D(ln.earnings.get(c, "0")) for c in (r.rules or {}).get("pf", {}).get("wage_components", ["BASIC", "DA"])), D(0))
        lines.append({"uan": e.uan, "name": f"{e.first_name} {e.last_name}".strip(), "gross": ln.gross, "pf_wage": pf_wage, "PF": ln.deductions.get("PF", "0"),
                      "EPS": ln.employer.get("EPS", "0"), "EPF_ER": ln.employer.get("EPF_ER", "0"), "lop_days": ln.lop_days})
    ent = db.get(m.Entity, r.entity_id)
    return _file(outputs.epf_ecr(lines), f"ecr-{ent.code}-{r.period}.txt", "text/plain")


@router.get("/runs/{run_id}/esi.csv")
def esi(run_id: int, user: User, db: DB) -> Response:
    r, pairs = _locked(db, user, run_id)
    lines = [{"esic_no": e.esic_no, "name": f"{e.first_name} {e.last_name}".strip(), "paid_days": ln.paid_days, "gross": ln.gross, "ESI": ln.deductions.get("ESI", "0")}
             for ln, e in pairs]
    ent = db.get(m.Entity, r.entity_id)
    return _file(outputs.esi_csv(lines), f"esi-{ent.code}-{r.period}.csv", "text/csv")


def payslip_dict(db: DB, r: m.PayrollRun, ln: m.PayrollLine, e: m.Employee) -> dict:
    ent = db.get(m.Entity, r.entity_id)
    lk = Lookups(db)
    _, end, _ = period_bounds(r.period)
    return {"company": ent.name, "period": end.strftime("%B %Y"), "code": e.code, "name": f"{e.first_name} {e.last_name}".strip(),
            "designation": lk.desig.get(e.designation_id or 0, ""), "location": lk.loc[e.location_id].name, "paid_days": str(ln.paid_days),
            "earnings": ln.earnings, "deductions": ln.deductions, "employer": ln.employer, "gross": str(ln.gross),
            "total_deductions": str(ln.total_deductions), "net": str(ln.net), "language": e.language}


@router.get("/runs/{run_id}/payslips/{employee_id}.pdf")
def payslip(run_id: int, employee_id: int, user: User, db: DB) -> Response:
    r = _run(db, run_id)
    if user.employee_id != employee_id:
        require(user, "payroll.read")
    if r.status != "locked":
        raise HTTPException(409, "Payslips are created only from a locked payroll")
    ln = db.scalar(select(m.PayrollLine).where(m.PayrollLine.run_id == r.id, m.PayrollLine.employee_id == employee_id))
    if not ln:
        raise HTTPException(404, "No payslip")
    e = db.get(m.Employee, employee_id)
    return _file(outputs.payslip_pdf(payslip_dict(db, r, ln, e)), f"payslip-{e.code}-{r.period}.pdf", "application/pdf")


@router.post("/runs/{run_id}/publish")
def publish(run_id: int, user: User, db: DB) -> dict:
    """Queue payslip messages on WhatsApp in each employee's language (sent once the WhatsApp account is live)."""
    r, pairs = _locked(db, user, run_id)
    require(user, "payroll.approve_hr")
    n = 0
    for ln, e in pairs:
        if ln.hold or not e.phone:
            continue
        queue_message(db, to=e.phone, template="payslip", employee_id=e.id, payload={"period": r.period, "net": str(ln.net), "language": e.language, "run_id": r.id})
        n += 1
    r.payslips_published = True
    record(db, user.email, "payslips_published", "payroll_run", r.id, after={"messages": n})
    db.commit()
    return {"queued": n}
