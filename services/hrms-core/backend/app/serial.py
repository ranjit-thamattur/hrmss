"""Turn database rows into JSON-safe dicts, applying field masking for the viewer."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .domain.imports import mask
from .services.access import sees_sensitive
from .services.security import decrypt


def plain(v: Any) -> Any:
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    return v


def row(obj: Any, fields: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    cols = fields or [c.key for c in obj.__table__.columns]
    d = {c: plain(getattr(obj, c)) for c in cols}
    d.update(extra)
    return d


class Lookups:
    """Small per-request cache of organisation names."""

    def __init__(self, db: Session):
        self.loc = {x.id: x for x in db.scalars(select(m.Location))}
        self.ent = {x.id: x for x in db.scalars(select(m.Entity))}
        self.dept = {x.id: x.name for x in db.scalars(select(m.Department))}
        self.desig = {x.id: x.name for x in db.scalars(select(m.Designation))}
        self.grade = {x.id: x.code for x in db.scalars(select(m.Grade))}

    def entity_of_location(self, location_id: int) -> m.Entity | None:
        loc = self.loc.get(location_id)
        return self.ent.get(loc.entity_id) if loc else None


def employee_summary(e: m.Employee, lk: Lookups) -> dict[str, Any]:
    loc = lk.loc.get(e.location_id)
    ent = lk.entity_of_location(e.location_id)
    return {"id": e.id, "code": e.code, "name": f"{e.first_name} {e.last_name}".strip(), "status": e.status,
            "location": loc.name if loc else None, "location_id": e.location_id, "entity": ent.code if ent else None,
            "department": lk.dept.get(e.department_id), "department_id": e.department_id, "designation": lk.desig.get(e.designation_id or 0),
            "grade": lk.grade.get(e.grade_id or 0), "doj": plain(e.doj), "phone": e.phone, "language": e.language, "has_bank": bool(e.bank_account_enc)}


def employee_detail(db: Session, e: m.Employee, viewer: m.AppUser, lk: Lookups) -> dict[str, Any]:
    d = employee_summary(e, lk)
    sensitive = sees_sensitive(viewer, e.id)
    pan, bank = decrypt(e.pan_enc), decrypt(e.bank_account_enc)
    d.update({
        "first_name": e.first_name, "last_name": e.last_name, "gender": e.gender, "dob": plain(e.dob), "dol": plain(e.dol), "email": e.email,
        "address": e.address if sensitive else None, "designation_id": e.designation_id, "grade_id": e.grade_id, "manager_id": e.manager_id,
        "shift_code": e.shift_code, "uan": e.uan, "esic_no": e.esic_no, "ifsc": e.ifsc if sensitive else None, "bank_name": e.bank_name,
        "pan": pan if sensitive else mask(pan, 2), "bank_account": bank if sensitive else mask(bank),
        "aadhaar": ("XXXX XXXX " + e.aadhaar_last4) if e.aadhaar_last4 else None, "biometric_id": e.biometric_id,
        "pf_applicable": e.pf_applicable, "esi_applicable": e.esi_applicable, "pt_applicable": e.pt_applicable, "lwf_applicable": e.lwf_applicable,
        "can_see_sensitive": sensitive,
    })
    if sensitive:
        st = db.scalar(select(m.SalaryStructure).where(m.SalaryStructure.employee_id == e.id).order_by(m.SalaryStructure.effective_from.desc()))
        d["salary"] = row(st) if st else None
    else:
        d["salary"] = None
    mgr = db.get(m.Employee, e.manager_id) if e.manager_id else None
    d["manager"] = f"{mgr.first_name} {mgr.last_name}".strip() if mgr else None
    return d


def user_dict(u: m.AppUser) -> dict[str, Any]:
    return row(u, ["id", "email", "display_name", "employee_id", "roles", "entity_scope", "location_scope", "is_active", "identity_sub",
                   "must_change_password", "last_login_at", "created_at"])
