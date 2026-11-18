from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from .. import models as m
from ..deps import DB, User
from ..domain.imports import AADHAAR_RE, IFSC_RE, PAN_RE, mask
from ..serial import Lookups, employee_detail, employee_summary, row
from ..services.access import can_see_employee, has, require, scope_employees
from ..services.audit import diff, record, snapshot
from ..services.employees import close_dated, create_employee, in_force, split_gross
from ..services.integrations import read_file, save_file
from ..services.policies import policy
from ..services.security import encrypt

router = APIRouter(prefix="/api/employees", tags=["employees"])

EDITABLE = {"first_name", "last_name", "gender", "dob", "phone", "email", "language", "address", "bank_name", "ifsc", "uan", "esic_no",
            "location_id", "department_id", "designation_id", "grade_id", "manager_id", "shift_code", "pf_applicable", "esi_applicable",
            "pt_applicable", "lwf_applicable", "biometric_id"}


def _get(db: DB, user: User, employee_id: int) -> m.Employee:
    e = db.get(m.Employee, employee_id)
    if not e or not can_see_employee(db, user, employee_id):
        raise HTTPException(404, "Employee not found")
    return e


@router.get("")
def list_employees(user: User, db: DB, q: str | None = None, entity_id: int | None = None, location_id: int | None = None,
                   department_id: int | None = None, status: str | None = None, expiring: bool = False, page: int = 1, size: int = 25) -> dict:
    require(user, "employees.read")
    stmt = scope_employees(select(m.Employee), user)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(m.Employee.code.ilike(like), m.Employee.first_name.ilike(like), m.Employee.last_name.ilike(like), m.Employee.phone.ilike(like)))
    if location_id:
        stmt = stmt.where(m.Employee.location_id == location_id)
    if entity_id:
        stmt = stmt.where(m.Employee.location_id.in_(select(m.Location.id).where(m.Location.entity_id == entity_id)))
    if department_id:
        stmt = stmt.where(m.Employee.department_id == department_id)
    if status:
        stmt = stmt.where(m.Employee.status == status)
    else:
        stmt = stmt.where(m.Employee.status != "exited")
    days = int(policy(db, "doc_expiry_alert_days") or 30)
    soon = date.today() + timedelta(days=days)
    expiring_ids = set(db.scalars(select(m.EmployeeDocument.employee_id).where(m.EmployeeDocument.expiry_date.is_not(None), m.EmployeeDocument.expiry_date <= soon)))
    if expiring:
        stmt = stmt.where(m.Employee.id.in_(list(expiring_ids) or [-1]))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(m.Employee.code).offset((max(page, 1) - 1) * size).limit(min(size, 200))).all()
    lk = Lookups(db)
    pending = set(db.scalars(select(m.ChangeRequest.employee_id).where(m.ChangeRequest.status == "pending")))
    users = set(db.scalars(select(m.AppUser.employee_id).where(m.AppUser.employee_id.is_not(None))))
    items = [{**employee_summary(e, lk), "doc_expiring": e.id in expiring_ids, "change_pending": e.id in pending, "has_user": e.id in users} for e in rows]
    return {"total": total, "page": page, "size": size, "items": items}


class EmployeeIn(BaseModel):
    code: str
    first_name: str
    last_name: str = ""
    gender: str | None = None
    dob: date | None = None
    doj: date
    phone: str | None = None
    email: str | None = None
    language: str = "ta"
    address: str | None = None
    location_id: int
    department_id: int
    designation_id: int | None = None
    grade_id: int | None = None
    manager_id: int | None = None
    shift_code: str = "G"
    pan: str | None = None
    aadhaar: str | None = None
    bank_account: str | None = None
    bank_name: str | None = None
    ifsc: str | None = None
    uan: str | None = None
    esic_no: str | None = None
    monthly_gross: Decimal | None = None
    pf_applicable: bool = True
    esi_applicable: bool = True


@router.post("")
def onboard_employee(body: EmployeeIn, user: User, db: DB) -> dict:
    """Onboarding employee (manual): adds the person to the system. It does not give software access —
    that is a separate step on the Users screen."""
    require(user, "employees.write")
    e = create_employee(db, body.model_dump(), user.email)
    db.commit()
    return employee_detail(db, e, user, Lookups(db))


@router.get("/{employee_id}")
def get_employee(employee_id: int, user: User, db: DB) -> dict:
    e = _get(db, user, employee_id)
    d = employee_detail(db, e, user, Lookups(db))
    d["documents"] = [row(x) for x in db.scalars(select(m.EmployeeDocument).where(m.EmployeeDocument.employee_id == e.id))]
    d["change_requests"] = [row(x) for x in db.scalars(select(m.ChangeRequest).where(m.ChangeRequest.employee_id == e.id).order_by(m.ChangeRequest.created_at.desc()))]
    u = db.scalar(select(m.AppUser).where(m.AppUser.employee_id == e.id))
    d["user"] = {"id": u.id, "email": u.email, "roles": u.roles, "is_active": u.is_active} if u else None
    d["allocations"] = [row(a) for a in db.scalars(select(m.EntityAllocation).where(m.EntityAllocation.employee_id == e.id).order_by(m.EntityAllocation.effective_from.desc()))]
    return d


@router.patch("/{employee_id}")
def update_employee(employee_id: int, body: dict[str, Any], user: User, db: DB) -> dict:
    require(user, "employees.write")
    e = _get(db, user, employee_id)
    before = snapshot(e)
    effective = date.fromisoformat(body.pop("effective_from")) if body.get("effective_from") else date.today()
    for k, v in body.items():
        if k in EDITABLE:
            if k == "dob" and isinstance(v, str):
                v = date.fromisoformat(v) if v else None
            setattr(e, k, v)
        elif k == "pan":
            if v and not PAN_RE.match(v.upper()):
                raise HTTPException(400, "PAN format is wrong")
            e.pan_enc = encrypt(v.upper() if v else None)
        elif k == "bank_account":
            e.bank_account_enc = encrypt(v or None)
        elif k == "aadhaar":
            if v and not AADHAAR_RE.match(str(v).replace(" ", "")):
                raise HTTPException(400, "Aadhaar must be 12 digits")
            e.aadhaar_last4 = str(v).replace(" ", "")[-4:] if v else None
    if e.ifsc and not IFSC_RE.match(e.ifsc.upper()):
        raise HTTPException(400, "IFSC format is wrong")
    after = snapshot(e)
    if any(before[k] != after[k] for k in ("location_id", "department_id", "designation_id", "grade_id")):
        close_dated(db, m.Assignment, e.id, effective)
        db.add(m.Assignment(employee_id=e.id, effective_from=effective, location_id=e.location_id, department_id=e.department_id,
                            designation_id=e.designation_id, grade_id=e.grade_id, status=e.status))
    b, a = diff(before, after)
    if b or a:
        record(db, user.email, "update", "employee", e.id, before=b, after=a, employee_id=e.id)
    db.commit()
    return employee_detail(db, e, user, Lookups(db))


# ---------------------------------------------------------------- salary structures (dated)
class StructureIn(BaseModel):
    effective_from: date
    components: dict[str, Decimal] | None = None
    monthly_gross: Decimal | None = None


@router.get("/{employee_id}/salary")
def salary_history(employee_id: int, user: User, db: DB) -> list[dict]:
    require(user, "payroll.read")
    _get(db, user, employee_id)
    return [row(s) for s in db.scalars(select(m.SalaryStructure).where(m.SalaryStructure.employee_id == employee_id).order_by(m.SalaryStructure.effective_from.desc()))]


@router.post("/{employee_id}/salary")
def salary_add(employee_id: int, body: StructureIn, user: User, db: DB) -> dict:
    require(user, "employees.write")
    _get(db, user, employee_id)
    if body.components:
        comps = {k.upper(): str(v) for k, v in body.components.items() if v is not None}
        gross = sum((Decimal(v) for v in comps.values()), Decimal(0))
    elif body.monthly_gross:
        comps, gross = split_gross(body.monthly_gross), body.monthly_gross
    else:
        raise HTTPException(400, "Give components or a monthly gross")
    close_dated(db, m.SalaryStructure, employee_id, body.effective_from)
    s = m.SalaryStructure(employee_id=employee_id, effective_from=body.effective_from, components=comps, monthly_gross=gross)
    db.add(s)
    db.flush()
    record(db, user.email, "salary_structure", "employee", employee_id, after=row(s), employee_id=employee_id)
    db.commit()
    return row(s)


# ---------------------------------------------------------------- paying entities (split salaries)
class AllocationIn(BaseModel):
    effective_from: date
    parts: list[dict[str, Any]]  # [{entity_id, method: percent|fixed, value, is_primary}]


@router.post("/{employee_id}/allocations")
def allocations_set(employee_id: int, body: AllocationIn, user: User, db: DB) -> list[dict]:
    require(user, "employees.write")
    _get(db, user, employee_id)
    if not body.parts:
        raise HTTPException(400, "At least one paying entity")
    pct = sum(Decimal(str(p["value"])) for p in body.parts if p.get("method", "percent") == "percent")
    if pct > 100:
        raise HTTPException(400, "Percent shares add up to more than 100")
    if sum(1 for p in body.parts if p.get("is_primary")) != 1:
        raise HTTPException(400, "Exactly one primary paying entity")
    close_dated(db, m.EntityAllocation, employee_id, body.effective_from)
    out = []
    for p in body.parts:
        a = m.EntityAllocation(employee_id=employee_id, entity_id=int(p["entity_id"]), effective_from=body.effective_from,
                               method=p.get("method", "percent"), value=Decimal(str(p["value"])), is_primary=bool(p.get("is_primary")))
        db.add(a)
        out.append(a)
    db.flush()
    record(db, user.email, "entity_allocation", "employee", employee_id, after=[row(a) for a in out], employee_id=employee_id)
    db.commit()
    return [row(a) for a in in_force(db, m.EntityAllocation, employee_id, body.effective_from)]


# ---------------------------------------------------------------- documents
@router.post("/{employee_id}/documents")
async def doc_upload(employee_id: int, user: User, db: DB, doc_type: str = Form(...), expiry_date: str | None = Form(None),
                     number: str | None = Form(None), file: UploadFile | None = File(None)) -> dict:
    if not (has(user, "employees.write") or user.employee_id == employee_id):
        raise HTTPException(403, "Not allowed")
    _get(db, user, employee_id)
    key = None
    if file:
        content = await file.read()
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(413, "File larger than 10 MB")
        key = save_file(f"employees/{employee_id}/{date.today():%Y%m%d}-{file.filename}", content, file.content_type or "application/octet-stream")
    d = m.EmployeeDocument(employee_id=employee_id, doc_type=doc_type, number_masked=mask(number) if number else None,
                           expiry_date=date.fromisoformat(expiry_date) if expiry_date else None, file_key=key)
    db.add(d)
    db.flush()
    record(db, user.email, "document_added", "employee", employee_id, after={"doc_type": doc_type, "expiry_date": expiry_date}, employee_id=employee_id)
    db.commit()
    return row(d)


@router.get("/{employee_id}/documents/{doc_id}/file")
def doc_file(employee_id: int, doc_id: int, user: User, db: DB) -> Response:
    _get(db, user, employee_id)
    d = db.get(m.EmployeeDocument, doc_id)
    if not d or d.employee_id != employee_id or not d.file_key:
        raise HTTPException(404, "No file")
    return Response(read_file(d.file_key), media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{d.file_key.rsplit("/", 1)[-1]}"'})


# ---------------------------------------------------------------- change requests (employee asks, HR approves)
class DecideIn(BaseModel):
    approve: bool
    note: str | None = None


@router.get("/change-requests/pending")
def change_requests(user: User, db: DB) -> list[dict]:
    require(user, "employees.write")
    out = []
    for c in db.scalars(select(m.ChangeRequest).where(m.ChangeRequest.status == "pending").order_by(m.ChangeRequest.created_at)):
        e = db.get(m.Employee, c.employee_id)
        out.append(row(c, employee=f"{e.code} {e.first_name} {e.last_name}".strip(),
                       new_value=mask(c.new_value) if c.field in ("bank_account", "pan") else c.new_value))
    return out


@router.post("/change-requests/{cr_id}/decide")
def change_decide(cr_id: int, body: DecideIn, user: User, db: DB) -> dict:
    from datetime import datetime, timezone

    require(user, "employees.write")
    c = db.get(m.ChangeRequest, cr_id)
    if not c or c.status != "pending":
        raise HTTPException(404, "No pending request")
    e = db.get(m.Employee, c.employee_id)
    if body.approve:
        before = snapshot(e)
        if c.field == "bank_account":
            e.bank_account_enc = encrypt(c.new_value)
        elif c.field == "pan":
            e.pan_enc = encrypt(c.new_value.upper())
        elif c.field in EDITABLE:
            setattr(e, c.field, c.new_value)
        b, a = diff(before, snapshot(e))
        record(db, user.email, "change_request_approved", "employee", e.id, before=b or {c.field: "***"}, after=a or {c.field: "***"}, employee_id=e.id)
    else:
        record(db, user.email, "change_request_rejected", "employee", e.id, after={"field": c.field, "note": body.note}, employee_id=e.id)
    c.status = "approved" if body.approve else "rejected"
    c.decided_by, c.decided_at = user.email, datetime.now(timezone.utc)
    db.commit()
    return row(c)


# ---------------------------------------------------------------- timeline and audit
@router.get("/{employee_id}/timeline")
def timeline(employee_id: int, user: User, db: DB) -> dict:
    require(user, "audit.read")
    e = _get(db, user, employee_id)
    events = db.scalars(select(m.AuditLog).where(m.AuditLog.employee_id == employee_id).order_by(m.AuditLog.at)).all()
    lk = Lookups(db)
    assignments = db.scalars(select(m.Assignment).where(m.Assignment.employee_id == employee_id).order_by(m.Assignment.effective_from)).all()
    return {"employee": employee_summary(e, lk),
            "assignments": [row(a, location=lk.loc[a.location_id].name, department=lk.dept.get(a.department_id)) for a in assignments],
            "events": [row(x) for x in events]}
