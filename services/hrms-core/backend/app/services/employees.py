from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..domain.imports import AADHAAR_RE, IFSC_RE, PAN_RE
from .audit import record, snapshot
from .security import encrypt

DEFAULT_SPLIT = {"BASIC": Decimal("0.5"), "HRA": Decimal("0.2")}
CONVEYANCE = Decimal("1600")


def split_gross(gross: Decimal) -> dict[str, str]:
    """Default structure when only a gross figure is known: Basic 50%, HRA 20%, Conveyance 1,600, rest Special."""
    basic = (gross * DEFAULT_SPLIT["BASIC"]).quantize(Decimal("1"))
    hra = (gross * DEFAULT_SPLIT["HRA"]).quantize(Decimal("1"))
    conv = min(CONVEYANCE, max(Decimal(0), gross - basic - hra))
    special = gross - basic - hra - conv
    return {"BASIC": str(basic), "HRA": str(hra), "CONV": str(conv), "SPECIAL": str(special)}


def _id_by(db: Session, model: type, field: str, value: Any, label: str, required: bool = True) -> int | None:
    if value in (None, ""):
        if required:
            raise HTTPException(400, f"{label} is required")
        return None
    if isinstance(value, int):
        return value
    col = getattr(model, field)
    obj = db.scalar(select(model).where(col.ilike(str(value))))
    if not obj:
        raise HTTPException(400, f"Unknown {label} '{value}'")
    return obj.id


def create_employee(db: Session, data: dict[str, Any], actor: str) -> m.Employee:
    code = str(data.get("code", "")).strip().upper()
    if not code:
        raise HTTPException(400, "Employee code is required")
    if db.scalar(select(m.Employee.id).where(m.Employee.code == code)):
        raise HTTPException(409, f"Employee code {code} already exists")
    pan = (data.get("pan") or "").upper().strip()
    if pan and not PAN_RE.match(pan):
        raise HTTPException(400, "PAN format is wrong (ABCDE1234F)")
    ifsc = (data.get("ifsc") or "").upper().strip()
    if ifsc and not IFSC_RE.match(ifsc):
        raise HTTPException(400, "IFSC format is wrong")
    aadhaar = str(data.get("aadhaar") or "").replace(" ", "")
    if aadhaar and not AADHAAR_RE.match(aadhaar):
        raise HTTPException(400, "Aadhaar must be 12 digits")
    loc_id = _id_by(db, m.Location, "code", data.get("location_id") or data.get("location"), "location")
    dept_id = _id_by(db, m.Department, "name", data.get("department_id") or data.get("department"), "department")
    desig_id = _id_by(db, m.Designation, "name", data.get("designation_id") or data.get("designation"), "designation", required=False)
    grade_id = _id_by(db, m.Grade, "code", data.get("grade_id") or data.get("grade"), "grade", required=False)
    doj = data.get("doj")
    if isinstance(doj, str):
        doj = date.fromisoformat(doj)
    if not doj:
        raise HTTPException(400, "Date of joining is required")
    dob = data.get("dob")
    if isinstance(dob, str) and dob:
        dob = date.fromisoformat(dob)
    e = m.Employee(
        code=code, first_name=str(data.get("first_name", "")).strip(), last_name=str(data.get("last_name") or "").strip(),
        gender=data.get("gender") or None, dob=dob or None, doj=doj, phone=data.get("phone") or None, email=(data.get("email") or None),
        language=data.get("language") or "ta", address=data.get("address") or None, pan_enc=encrypt(pan), aadhaar_last4=aadhaar[-4:] if aadhaar else None,
        bank_account_enc=encrypt(str(data.get("bank_account") or "").strip() or None), bank_name=data.get("bank_name") or None, ifsc=ifsc or None,
        uan=data.get("uan") or None, esic_no=data.get("esic_no") or None, location_id=loc_id, department_id=dept_id, designation_id=desig_id,
        grade_id=grade_id, manager_id=data.get("manager_id") or None, shift_code=(data.get("shift") or data.get("shift_code") or "G").upper(),
        pf_applicable=bool(data.get("pf_applicable", True)), esi_applicable=bool(data.get("esi_applicable", True)),
    )
    if not e.first_name:
        raise HTTPException(400, "Name is required")
    db.add(e)
    db.flush()
    db.add(m.Assignment(employee_id=e.id, effective_from=doj, location_id=loc_id, department_id=dept_id, designation_id=desig_id, grade_id=grade_id))
    entity_id = db.get(m.Location, loc_id).entity_id
    ent_override = data.get("entity")
    if ent_override:
        entity_id = _id_by(db, m.Entity, "code", ent_override, "entity")
    db.add(m.EntityAllocation(employee_id=e.id, entity_id=entity_id, effective_from=doj, method="percent", value=Decimal(100), is_primary=True))
    gross = data.get("monthly_gross")
    if gross:
        gross = Decimal(str(gross))
        db.add(m.SalaryStructure(employee_id=e.id, effective_from=doj, components=split_gross(gross), monthly_gross=gross, source=data.get("source", "manual")))
    for y in sorted({doj.year, date.today().year}):
        for lt in db.scalars(select(m.LeaveType)):
            if not db.scalar(select(m.LeaveBalance.id).where(m.LeaveBalance.employee_id == e.id, m.LeaveBalance.leave_code == lt.code, m.LeaveBalance.year == y)):
                db.add(m.LeaveBalance(employee_id=e.id, leave_code=lt.code, year=y, opening=lt.annual_quota))
    db.flush()
    record(db, actor, "create", "employee", e.id, after=snapshot(e), employee_id=e.id)
    from .provisioning import queue  # every employee is enrolled for attendance, with or without software access

    queue(db, target="biometric", action="create", employee_id=e.id, actor=actor)
    return e


def close_dated(db: Session, model: type, employee_id: int, new_from: date) -> None:
    """End the open version the day before a new one starts."""
    for r in db.scalars(select(model).where(model.employee_id == employee_id, model.effective_to.is_(None), model.effective_from < new_from)):
        r.effective_to = new_from - timedelta(days=1)


def in_force(db: Session, model: type, employee_id: int, on: date) -> list[Any]:
    from sqlalchemy import or_

    return list(db.scalars(select(model).where(model.employee_id == employee_id, model.effective_from <= on,
                                                or_(model.effective_to.is_(None), model.effective_to >= on)).order_by(model.effective_from.desc())))
