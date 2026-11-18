"""Company setup: entities, locations, departments, designations, grades, shifts, holidays,
leave types, dated policies and versioned statutory rules. Every change is audited."""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from .. import models as m
from ..deps import DB, User
from ..domain.attendance_engine import MISSED_PUNCH_RULES
from ..serial import row
from ..services.access import require
from ..services.audit import record, snapshot
from ..services.policies import POLICY_DEFAULTS, POLICY_HELP, all_policies, rules_for

router = APIRouter(prefix="/api/org", tags=["organisation"])

TABLES: dict[str, type] = {
    "entities": m.Entity, "locations": m.Location, "departments": m.Department, "designations": m.Designation,
    "grades": m.Grade, "shifts": m.Shift, "holidays": m.Holiday, "leave-types": m.LeaveType,
}
ORDER = {"holidays": m.Holiday.day, "leave-types": m.LeaveType.code}


def _model(kind: str) -> type:
    if kind not in TABLES:
        raise HTTPException(404, "Unknown setup table")
    return TABLES[kind]


def _coerce(model: type, data: dict[str, Any]) -> dict[str, Any]:
    cols = {c.key: c for c in model.__table__.columns}
    out: dict[str, Any] = {}
    for k, v in data.items():
        if k not in cols or (k == "id" and v is None):
            continue
        if v is not None and cols[k].type.python_type is date and isinstance(v, str):
            v = date.fromisoformat(v)
        out[k] = v
    return out


@router.get("/all")
def all_setup(user: User, db: DB) -> dict:
    """Everything the screens need for dropdowns in one call."""
    return {k: [row(x) for x in db.scalars(select(t).order_by(ORDER.get(k, list(t.__table__.primary_key.columns)[0])))] for k, t in TABLES.items()}


@router.get("/tables/{kind}")
def list_rows(kind: str, user: User, db: DB) -> list[dict]:
    t = _model(kind)
    return [row(x) for x in db.scalars(select(t).order_by(ORDER.get(kind, list(t.__table__.primary_key.columns)[0])))]


@router.post("/tables/{kind}")
def create_row(kind: str, body: dict[str, Any], user: User, db: DB) -> dict:
    require(user, "org.manage")
    t = _model(kind)
    obj = t(**_coerce(t, body))
    db.add(obj)
    db.flush()
    record(db, user.email, "create", kind, getattr(obj, "id", getattr(obj, "code", None)), after=snapshot(obj))
    db.commit()
    return row(obj)


@router.put("/tables/{kind}/{key}")
def update_row(kind: str, key: str, body: dict[str, Any], user: User, db: DB) -> dict:
    require(user, "org.manage")
    t = _model(kind)
    obj = db.get(t, key if kind == "leave-types" else int(key))
    if not obj:
        raise HTTPException(404, "Not found")
    before = snapshot(obj)
    for k, v in _coerce(t, body).items():
        if k not in ("id",):
            setattr(obj, k, v)
    record(db, user.email, "update", kind, key, before=before, after=snapshot(obj))
    db.commit()
    return row(obj)


@router.delete("/tables/{kind}/{key}")
def delete_row(kind: str, key: str, user: User, db: DB) -> dict:
    require(user, "org.manage")
    t = _model(kind)
    if kind in ("entities", "locations", "departments"):
        raise HTTPException(400, "Entities, locations and departments are deactivated, not deleted.")
    obj = db.get(t, key if kind == "leave-types" else int(key))
    if not obj:
        raise HTTPException(404, "Not found")
    record(db, user.email, "delete", kind, key, before=snapshot(obj))
    db.delete(obj)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- dated policies
class PolicyIn(BaseModel):
    key: str
    value: Any
    effective_from: date
    note: str | None = None


@router.get("/policies/current")
def policies_current(user: User, db: DB, on: date | None = None) -> dict:
    vals = all_policies(db, on)
    history = db.scalars(select(m.PolicyVersion).order_by(m.PolicyVersion.key, m.PolicyVersion.effective_from.desc())).all()
    return {"values": vals, "help": POLICY_HELP, "history": [row(h) for h in history], "missed_punch_options": list(MISSED_PUNCH_RULES)}


@router.post("/policies")
def policies_add(body: PolicyIn, user: User, db: DB) -> dict:
    require(user, "org.manage")
    if body.key not in POLICY_DEFAULTS:
        raise HTTPException(400, f"Unknown policy '{body.key}'")
    if body.key == "missed_punch_rule" and body.value not in (*MISSED_PUNCH_RULES, None):
        raise HTTPException(400, "missed_punch_rule must be present, lop or hold")
    pv = m.PolicyVersion(key=body.key, value=body.value, effective_from=body.effective_from, note=body.note, created_by=user.email)
    db.add(pv)
    db.flush()
    record(db, user.email, "policy_version", "policy", body.key, after=row(pv))
    db.commit()
    return row(pv)


# ---------------------------------------------------------------- statutory rule versions
class RulesIn(BaseModel):
    rules: dict[str, Any]
    effective_from: date
    entity_id: int | None = None
    note: str | None = None


@router.get("/statutory-rules")
def rules_list(user: User, db: DB, on: date | None = None, entity_id: int | None = None) -> dict:
    current = rules_for(db, entity_id, on or date.today())
    versions = db.scalars(select(m.StatutoryRuleVersion).order_by(m.StatutoryRuleVersion.effective_from.desc())).all()
    return {"current": current, "versions": [row(v, ["id", "entity_id", "effective_from", "note", "created_by", "created_at"]) for v in versions]}


@router.post("/statutory-rules")
def rules_add(body: RulesIn, user: User, db: DB) -> dict:
    require(user, "org.manage")
    for k in ("pf", "esi", "pt", "lwf", "tds", "ot", "version"):
        if k not in body.rules:
            raise HTTPException(400, f"Rule set is missing '{k}'")
    v = m.StatutoryRuleVersion(entity_id=body.entity_id, rules=body.rules, effective_from=body.effective_from, note=body.note, created_by=user.email)
    db.add(v)
    db.flush()
    record(db, user.email, "statutory_rules_version", "statutory_rules", v.id, after={"effective_from": body.effective_from, "version": body.rules.get("version")})
    db.commit()
    return {"id": v.id}
