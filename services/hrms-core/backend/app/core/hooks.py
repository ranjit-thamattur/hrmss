"""Validation that is specific to one entity. The generic rules (codes, references, overlaps, scope, dating)
are in engine.py; each hook adds what only its entity needs.

Signature: hook(ctx, spec, values, start, end, rid, op) -> values
    values  full plain values of the version being written (hooks may fill system fields)
    start   first day the version applies; end: last day (None = open)
    rid     the record (None while creating)        op: "create" | "change" | "reactivate"
Raise HTTPException(422 or 409) with a message a person can act on.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

from .. import models as m
from . import numbering
from .context import Ctx, current, overlapping
from .records import active_at, at
from .specs import ACTIONS, EXTRA_RESOURCES, REQUEST_TYPES, SCOPE_MODES, SPECS, STATUTORY_TYPES, WEEKDAYS, Spec

Hook = Callable[[Ctx, Spec, dict[str, Any], date, "date | None", "int | None", str], dict[str, Any]]


def bad(msg: str, code: int = 422) -> HTTPException:
    return HTTPException(code, msg)


def legal_entity(ctx: Ctx, spec: Spec, v: dict, start: date, end: date | None, rid: int | None, op: str) -> dict:
    sig = v.get("signatories")
    if sig is not None:
        if not isinstance(sig, list) or not all(isinstance(s, dict) and s.get("name") for s in sig):
            raise bad("Signatories must be a list of {name, designation, valid_from, valid_to}.")
        for s in sig:
            for k in ("valid_from", "valid_to"):
                if s.get(k):
                    try:
                        date.fromisoformat(str(s[k]))
                    except ValueError as e:
                        raise bad(f"Signatory {s['name']}: {k} must be a date (YYYY-MM-DD).") from e
    return v


def department(ctx: Ctx, spec: Spec, v: dict, start: date, end: date | None, rid: int | None, op: str) -> dict:
    parent = v.get("parent_rid")
    seen = {rid} if rid else set()
    hops = 0
    while parent is not None:
        if parent in seen:
            raise bad("A department cannot be its own parent, directly or through other departments.")
        seen.add(parent)
        row = at(ctx, spec, parent, start)
        parent = row.parent_rid if row is not None else None
        hops += 1
        if hops > 50:
            raise bad("The department tree is too deep (more than 50 levels).")
    return v


def person(ctx: Ctx, spec: Spec, v: dict, start: date, end: date | None, rid: int | None, op: str) -> dict:
    from .records import secret_hash

    p = m.Person
    if v.get("pan"):
        dup = ctx.db.scalar(select(p.rid).where(p.client_id == ctx.client_id, p.pan_hash == secret_hash(v["pan"]), p.rid != (rid or -1)).limit(1))
        if dup:
            raise bad(f"A person with this PAN already exists (person {dup}).", 409)
    if v.get("date_of_birth") and v.get("first_name"):
        same = select(p.rid).where(p.client_id == ctx.client_id, p.date_of_birth == v["date_of_birth"], p.rid != (rid or -1),
                                   p.first_name.ilike(v["first_name"]), p.is_active.is_(True))
        if v.get("last_name"):
            same = same.where(p.last_name.ilike(v["last_name"]))
        dup = ctx.db.scalar(same.limit(1))
        if dup:
            raise bad(f"A person with the same name and date of birth already exists (person {dup}).", 409)
    docs = v.get("identity_documents")
    if docs is not None and not all(isinstance(d, dict) and d.get("type") and d.get("number") for d in docs):
        raise bad("Identity documents must be a list of {type, number, valid_to}.")
    return v


def statutory(ctx: Ctx, spec: Spec, v: dict, start: date, end: date | None, rid: int | None, op: str) -> dict:
    if v.get("type") == "OTHER" and not v.get("other_name"):
        raise bad("Give other_name when the type is OTHER.")
    if v.get("type") in ("PT", "LWF") and not v.get("state_rid"):
        raise bad(f"{v['type']} is a state law: give state_rid.")
    if v.get("status") == "active" and not v.get("number"):
        raise bad("An active registration needs its number (use status 'applied' or 'exempt' otherwise).")
    return v


def holiday_calendar(ctx: Ctx, spec: Spec, v: dict, start: date, end: date | None, rid: int | None, op: str) -> dict:
    year = v.get("year")
    hols = v.get("holidays")
    if not isinstance(hols, list):
        raise bad("Holidays must be a list of {date, name, kind}.")
    seen = set()
    for h in hols:
        if not isinstance(h, dict) or not h.get("date") or not h.get("name"):
            raise bad("Each holiday needs a date and a name.")
        try:
            d = date.fromisoformat(str(h["date"]))
        except ValueError as e:
            raise bad(f"Holiday '{h.get('name')}': date must be YYYY-MM-DD.") from e
        if d.year != year:
            raise bad(f"Holiday '{h['name']}' ({d}) is not in {year}.")
        if d in seen:
            raise bad(f"{d} is listed twice.")
        seen.add(d)
        if h.get("kind", "fixed") not in ("fixed", "optional"):
            raise bad(f"Holiday '{h['name']}': kind must be fixed or optional.")
    hc = m.HolidayCalendar
    for loc in v.get("location_rids") or []:
        others = ctx.db.scalars(select(hc).where(hc.client_id == ctx.client_id, hc.year == year, hc.rid != (rid or -1), hc.is_active.is_(True),
                                                 overlapping(hc, start, end)))
        for o in others:
            if loc in (o.location_rids or []):
                raise bad(f"Location {loc} already has the {year} calendar '{o.code}'. A location has one calendar per year.", 409)
    return v


def payroll_calendar(ctx: Ctx, spec: Spec, v: dict, start: date, end: date | None, rid: int | None, op: str) -> dict:
    if v.get("attendance_cutoff") and v.get("pay_date") and v["attendance_cutoff"] > v["pay_date"]:
        raise bad("The attendance cut-off must be on or before the pay date.")
    if rid is not None and op == "change":
        cur = at(ctx, spec, rid, start)
        if cur is not None and cur.locked:
            raise bad("This payroll period is locked; it cannot be changed.", 409)
    return v


def grade(ctx: Ctx, spec: Spec, v: dict, start: date, end: date | None, rid: int | None, op: str) -> dict:
    lo, hi = v.get("pay_min"), v.get("pay_max")
    if lo is not None and hi is not None and Decimal(lo) > Decimal(hi):
        raise bad("pay_min must not be more than pay_max.")
    return v


def employment_type(ctx: Ctx, spec: Spec, v: dict, start: date, end: date | None, rid: int | None, op: str) -> dict:
    st = v.get("statutory_types") or []
    if not isinstance(st, list) or not set(st) <= set(STATUTORY_TYPES):
        raise bad(f"statutory_types must be a list from {', '.join(STATUTORY_TYPES)}.")
    return v


def shift(ctx: Ctx, spec: Spec, v: dict, start: date, end: date | None, rid: int | None, op: str) -> dict:
    v["crosses_midnight"] = v["end_time"] <= v["start_time"]
    for k in ("break_minutes", "grace_minutes", "half_day_minutes"):
        if v.get(k) is not None and v[k] < 0:
            raise bad(f"{k} cannot be negative.")
    return v


def weekly_off(ctx: Ctx, spec: Spec, v: dict, start: date, end: date | None, rid: int | None, op: str) -> dict:
    days = v.get("days_off")
    if not isinstance(days, list) or not days or not {str(d).lower() for d in days} <= set(WEEKDAYS):
        raise bad(f"days_off must be a list of weekdays ({', '.join(WEEKDAYS)}).")
    v["days_off"] = [str(d).lower() for d in days]
    return v


def policy(ctx: Ctx, spec: Spec, v: dict, start: date, end: date | None, rid: int | None, op: str) -> dict:
    ap = v.get("applies_to") or {}
    allowed = {"legal_entity_rids", "location_rids", "department_rids", "grade_rids"}
    if not isinstance(ap, dict) or not set(ap) <= allowed or not all(isinstance(x, list) for x in ap.values()):
        raise bad(f"applies_to must be an object with lists: {', '.join(sorted(allowed))} (empty = all).")
    return v


def number_series(ctx: Ctx, spec: Spec, v: dict, start: date, end: date | None, rid: int | None, op: str) -> dict:
    if (v.get("padding") or 0) < 0 or (v.get("start_number") or 0) < 0:
        raise bad("padding and start_number cannot be negative.")
    return v


def approval_workflow(ctx: Ctx, spec: Spec, v: dict, start: date, end: date | None, rid: int | None, op: str) -> dict:
    steps = v.get("steps")
    if not isinstance(steps, list) or not steps:
        raise bad("steps must be a non-empty list of {approver_type: role | reporting_level, value}.")
    for s in steps:
        t = s.get("approver_type") if isinstance(s, dict) else None
        val = s.get("value") if isinstance(s, dict) else None
        if t == "role" and (isinstance(val, str) or (isinstance(val, list) and val and all(isinstance(x, str) for x in val))):
            continue
        if t == "reporting_level" and isinstance(val, int) and val >= 1:
            continue
        raise bad("Each step is {approver_type: 'role', value: role or [roles]} or {approver_type: 'reporting_level', value: 1, 2 ...}.")
    if v.get("request_type") not in REQUEST_TYPES:
        raise bad("Unknown request_type.")
    return v


def role_permission(ctx: Ctx, spec: Spec, v: dict, start: date, end: date | None, rid: int | None, op: str) -> dict:
    acts = v.get("actions")
    if not isinstance(acts, list) or not set(acts) <= set(ACTIONS):
        raise bad(f"actions must be a list from {', '.join(ACTIONS)}.")
    res = v.get("resource")
    if res != "*" and res not in SPECS and res not in EXTRA_RESOURCES:
        raise bad(f"Unknown resource '{res}'. Use an entity key, {', '.join(EXTRA_RESOURCES)} or *.")
    if v.get("scope") not in SCOPE_MODES:
        raise bad(f"scope must be one of {', '.join(SCOPE_MODES)}.")
    mf = v.get("masked_fields") or []
    if not isinstance(mf, list) or not all(isinstance(x, str) for x in mf):
        raise bad("masked_fields must be a list of field names.")
    return v


def assignment(ctx: Ctx, spec: Spec, v: dict, start: date, end: date | None, rid: int | None, op: str) -> dict:
    le, loc, dep = v.get("legal_entity_rid"), v.get("location_rid"), v.get("department_rid")
    el, de = m.EntityLocation, m.DepartmentEntity
    if not ctx.db.scalar(select(el.rid).where(el.client_id == ctx.client_id, current(el, start), el.is_active.is_(True),
                                              el.legal_entity_rid == le, el.location_rid == loc).limit(1)):
        raise bad(f"Legal entity {le} does not operate at location {loc} on {start}. Link them first (entity at location).")
    if not ctx.db.scalar(select(de.rid).where(de.client_id == ctx.client_id, current(de, start), de.is_active.is_(True),
                                              de.department_rid == dep, de.legal_entity_rid == le).limit(1)):
        raise bad(f"Department {dep} is not part of legal entity {le} on {start}. Link them first (department in entity).")
    cc = active_at(ctx, "cost-centres", v.get("cost_centre_rid"), start)
    if cc is not None and cc.legal_entity_rid != le:
        raise bad("The cost centre belongs to another legal entity.")
    sh = active_at(ctx, "shifts", v.get("shift_rid"), start)
    if sh is not None and sh.location_rid not in (None, loc):
        raise bad("The shift belongs to another location.")
    share = Decimal(str(v.get("pay_share") if v.get("pay_share") is not None else 100))
    if share < 0 or share > 100:
        raise bad("pay_share must be between 0 and 100.")
    v["pay_share"] = share
    ea = m.EmploymentAssignment
    others = list(ctx.db.scalars(select(ea).where(ea.client_id == ctx.client_id, ea.person_rid == v["person_rid"], ea.rid != (rid or -1),
                                                  ea.is_active.is_(True), overlapping(ea, start, end))))
    total = share + sum((Decimal(str(o.pay_share or 0)) for o in others), Decimal(0))
    if total > 100:
        raise bad(f"Pay shares of this person's jobs would add up to {total}%, more than 100%.", 409)
    if v.get("is_primary") and any(o.is_primary for o in others):
        raise bad("This person already has a primary job in that period. Only one job can be primary.", 409)
    if op == "create":
        v["employee_number"] = numbering.allocate(ctx, "employee", le)
    return v


def reporting_line(ctx: Ctx, spec: Spec, v: dict, start: date, end: date | None, rid: int | None, op: str) -> dict:
    job = active_at(ctx, "employment-assignments", v.get("assignment_rid"), start)
    if job is not None and job.person_rid == v.get("reports_to_person_rid"):
        raise bad("A person cannot report to themselves.")
    return v


HOOKS: dict[str, Hook] = {
    "legal_entity": legal_entity, "department": department, "person": person, "statutory": statutory,
    "holiday_calendar": holiday_calendar, "payroll_calendar": payroll_calendar, "grade": grade, "employment_type": employment_type,
    "shift": shift, "weekly_off": weekly_off, "policy": policy, "number_series": number_series, "approval_workflow": approval_workflow,
    "role_permission": role_permission, "assignment": assignment, "reporting_line": reporting_line,
}
