"""Onboarding an employee (basic operation in the core; each client backend exposes it as its own API).

One person, one or more employment assignments (each with its pay share, legal entity, location,
department, designation and manager), and at most one login. All or nothing: one transaction.
Client rules come from the client YAML (onboarding.required_person_fields), not from code.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select

from .. import models as m
from ..core import access, engine
from ..core.context import Ctx, current
from ..core.records import at
from ..core.schemas import create_schema
from ..core.specs import SPECS
from . import users

P, A, R = SPECS["persons"], SPECS["employment-assignments"], SPECS["reporting-lines"]


class AssignmentIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    legal_entity_rid: int
    location_rid: int
    department_rid: int
    designation_rid: int
    grade_rid: int | None = None
    employment_type_rid: int | None = None
    cost_centre_rid: int | None = None
    shift_rid: int | None = None
    weekly_off_rid: int | None = None
    pay_share: Decimal = Field(Decimal(100), ge=0, le=100)
    is_primary: bool | None = None
    valid_from: date | None = Field(None, description="Joining date for this job (default: today)")
    reports_to_person_rid: int | None = Field(None, description="Line manager (a person)")
    functional_manager_person_rid: int | None = None


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    email: str
    roles: list[str] = ["employee"]
    scope_entity_rids: list[int] = []
    scope_location_rids: list[int] = []
    scope_department_rids: list[int] = []


class OnboardIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    person: dict[str, Any] = Field(..., description="Person fields (first_name, last_name, date_of_birth, phone, pan ...)")
    assignments: list[AssignmentIn] = Field(..., min_length=1)
    login: LoginIn | None = None
    change_reason: str | None = "Onboarding"


def required_person_fields(client: m.Client | None) -> list[str]:
    conf = (client.settings or {}).get("onboarding") if client else None
    return list((conf or {}).get("required_person_fields") or ["first_name"])


def _primary_flags(jobs: list[AssignmentIn]) -> list[bool]:
    flags = [j.is_primary for j in jobs]
    if sum(1 for f in flags if f) > 1:
        raise HTTPException(422, "Only one job can be primary.")
    if not any(flags):
        flags = [i == 0 for i in range(len(jobs))]  # first job is primary unless one is marked
    return [bool(f) for f in flags]


def add_assignment(ctx: Ctx, person_rid: int, job: AssignmentIn, primary: bool, reason: str | None) -> dict[str, Any]:
    start = job.valid_from or ctx.today
    data = job.model_dump(exclude={"valid_from", "reports_to_person_rid", "functional_manager_person_rid", "is_primary"})
    data.update(person_rid=person_rid, is_primary=primary)
    row = engine.create(ctx, A, data, start, None, reason)
    lines = []
    for kind, mgr in (("line", job.reports_to_person_rid), ("functional", job.functional_manager_person_rid)):
        if mgr is not None:
            rl = engine.create(ctx, R, {"assignment_rid": row.rid, "reports_to_person_rid": mgr, "type": kind}, start, None, reason)
            lines.append(rl.rid)
    return {"assignment_rid": row.rid, "employee_number": row.employee_number, "reporting_line_rids": lines}


def onboard(ctx: Ctx, body: OnboardIn) -> dict[str, Any]:
    access.require(ctx, "persons", "create")
    access.require(ctx, "employment-assignments", "create")
    client = ctx.db.get(m.Client, ctx.client_id)
    missing = [f for f in required_person_fields(client) if not body.person.get(f)]
    if missing:
        raise HTTPException(422, f"{client.name if client else 'This client'} needs these person fields at onboarding: {', '.join(missing)}.")
    total = sum((j.pay_share for j in body.assignments), Decimal(0))
    if total > 100:
        raise HTTPException(422, f"Pay shares add up to {total}%, more than 100%.")
    flags = _primary_flags(body.assignments)
    person_data = create_schema("persons").model_validate(body.person).model_dump()
    start = min(j.valid_from or ctx.today for j in body.assignments)
    person = engine.create(ctx, P, {k: v for k, v in person_data.items() if k not in ("valid_from", "valid_to", "change_reason")},
                           person_data.get("valid_from") or start, None, body.change_reason)
    jobs = [add_assignment(ctx, person.rid, j, flags[i], body.change_reason) for i, j in enumerate(body.assignments)]
    login = None
    if body.login:
        u, pw = users.create_user(ctx, body.login.email, " ".join(x for x in (person.first_name, person.last_name) if x), body.login.roles,
                                  person.rid, body.login.model_dump(include={"scope_entity_rids", "scope_location_rids", "scope_department_rids"}))
        login = {"user_id": u.id, "email": u.email, "roles": u.roles, "temporary_password": pw,
                 "note": "Shown once. The person sets their own password at first sign-in."}
    return {"person_rid": person.rid, "assignments": jobs, "login": login}


def profile(ctx: Ctx, person_rid: int, on: date | None = None) -> dict[str, Any]:
    """Person with their jobs (current and past), managers and login."""
    on = on or ctx.today
    person = engine.get_record(ctx, P, person_rid, on)
    ea = m.EmploymentAssignment
    job_rids = list(dict.fromkeys(ctx.db.scalars(select(ea.rid).where(ea.client_id == ctx.client_id, ea.person_rid == person_rid).order_by(ea.valid_from))))
    jobs = []
    for rid in job_rids:
        if at(ctx, A, rid, on) is None:
            jobs.append({"rid": rid, "status": "not in force on this date", "history": engine.history(ctx, A, rid)})
            continue
        job = engine.get_record(ctx, A, rid, on)
        rl = m.ReportingLine
        job["reporting_lines"] = [engine.get_record(ctx, R, x, on) for x in ctx.db.scalars(
            select(rl.rid).where(rl.client_id == ctx.client_id, rl.assignment_rid == rid, current(rl, on), rl.is_active.is_(True)))]
        jobs.append(job)
    u = ctx.db.scalar(select(m.AppUser).where(m.AppUser.client_id == ctx.client_id, m.AppUser.person_rid == person_rid))
    login = {"user_id": u.id, "email": u.email, "roles": u.roles, "is_active": u.is_active} if u else None
    total = sum((Decimal(str(j.get("pay_share") or 0)) for j in jobs if j.get("is_active") and j.get("status") == "active"), Decimal(0))
    return {"person": person, "assignments": jobs, "total_pay_share": total, "login": login, "as_of": on}


def list_employees(ctx: Ctx, filters: dict[str, Any], q: str | None, page: int, size: int, on: date | None) -> dict[str, Any]:
    """People with their current jobs, limited to the user's scope. Filters: legal_entity_rid, location_rid,
    department_rid, designation_rid (people with a current job matching all of them); q: name, email or employee number."""
    on = on or ctx.today
    psc = access.resolve_scope(ctx, access.require(ctx, P.key, "view"))
    asc = access.resolve_scope(ctx, access.require(ctx, A.key, "view"))
    pm, am = m.Person, m.EmploymentAssignment
    jconds = [am.client_id == ctx.client_id, current(am, on), am.is_active.is_(True), *access.scope_conditions(ctx, A, am, asc)]
    fconds = []
    for k in ("legal_entity_rid", "location_rid", "department_rid", "designation_rid"):
        if filters.get(k):
            fconds.append(getattr(am, k) == int(filters[k]))
    pconds = [pm.client_id == ctx.client_id, current(pm, on), pm.is_active.is_(True), *access.scope_conditions(ctx, P, pm, psc)]
    if fconds:
        pconds.append(pm.rid.in_(select(am.person_rid).where(*jconds, *fconds)))
    if q:
        like = f"%{q}%"
        pconds.append(or_(pm.first_name.ilike(like), pm.last_name.ilike(like), pm.email.ilike(like),
                          pm.rid.in_(select(am.person_rid).where(am.client_id == ctx.client_id, am.employee_number.ilike(like)))))
    size = max(1, min(size, 500))
    stmt = select(pm).where(*pconds).order_by(pm.first_name, pm.last_name, pm.rid)
    total = ctx.db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(ctx.db.scalars(stmt.offset((max(page, 1) - 1) * size).limit(size)))
    people = [engine.out_record(ctx, P, r, access.masked_fields(ctx, P.key)) for r in rows]
    ids = [p["rid"] for p in people]
    jobs_rows = list(ctx.db.scalars(select(am).where(*jconds, am.person_rid.in_(ids or [-1])).order_by(am.is_primary.desc())))
    refs = engine.ref_map(ctx, A, jobs_rows, on)
    masked = access.masked_fields(ctx, A.key)
    by_person: dict[int, list] = {}
    for r in jobs_rows:
        by_person.setdefault(r.person_rid, []).append(engine.out_record(ctx, A, r, masked, refs))
    for p in people:
        p["assignments"] = by_person.get(p["rid"], [])
    return {"total": total, "page": page, "size": size, "as_of": on, "items": people}


def deactivate_person(ctx: Ctx, person_rid: int, reason: str | None) -> dict[str, Any]:
    ea = m.EmploymentAssignment
    live = ctx.db.scalar(select(ea.rid).where(ea.client_id == ctx.client_id, ea.person_rid == person_rid, current(ea, ctx.today),
                                              ea.is_active.is_(True)).limit(1))
    if live is not None:
        raise HTTPException(409, f"Person {person_rid} still has an active job ({live}). End the jobs first.")
    engine.set_active(ctx, P, person_rid, False, ctx.today, reason)
    u = ctx.db.scalar(select(m.AppUser).where(m.AppUser.client_id == ctx.client_id, m.AppUser.person_rid == person_rid))
    if u is not None and u.is_active:
        users.set_active(ctx, u.id, False)
    return {"person_rid": person_rid, "is_active": False, "login_disabled": bool(u)}
