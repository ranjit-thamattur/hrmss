"""Hotel Vivek employee APIs (business operations of this client; the core provides the building blocks).

  POST /api/employee/add                                    onboard: person + job(s) + optional login, all or nothing
  GET  /api/employee                                        list (filters: legal_entity_rid, location_rid, department_rid, designation_rid, q)
  GET  /api/employee/{person_rid}                           profile: person, jobs, managers, login
  PUT  /api/employee/{person_rid}                           change person details (from effective_from)
  POST /api/employee/{person_rid}/assignments               add another job (e.g. split pay across two hotels)
  PUT  /api/employee/{person_rid}/assignments/{rid}         change a job (transfer, promotion, pay share)
  POST /api/employee/{person_rid}/assignments/{rid}/end     end a job on a date
  POST /api/employee/{person_rid}/login                     give the person a login (one per person)
  POST /api/employee/{person_rid}/deactivate                deactivate (all jobs must be ended); login is disabled
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.core import engine
from app.core.schemas import EndRecord, change_schema, split_change
from app.core.specs import SPECS
from app.deps import C
from app.services import onboarding, users
from app.services.onboarding import AssignmentIn, LoginIn, OnboardIn

router = APIRouter(prefix="/api/employee", tags=["Hotel Vivek: employees"])
P, A = SPECS["persons"], SPECS["employment-assignments"]
PersonChange = change_schema("persons")
JobChange = change_schema("employment-assignments")


def _job_of(ctx, person_rid: int, rid: int) -> None:  # noqa: ANN001
    rec = engine.get_record(ctx, A, rid)
    if rec.get("person_rid") != person_rid:
        raise HTTPException(404, f"Job {rid} does not belong to person {person_rid}.")


def _done(ctx, response: Response, row, pending, spec) -> dict:  # noqa: ANN001
    ctx.db.commit()
    if pending is not None:
        response.status_code = 202
        return {"message": "Backdated: saved for approval (see /api/setup/changes).", "pending_change": engine.pending_out(pending)}
    return engine.get_record(ctx, spec, row.rid, row.valid_from if row.valid_from > ctx.today else None)


@router.post("/add", status_code=201, summary="Onboard an employee: person + job(s) + optional login, in one go")
def add(body: OnboardIn, ctx: C) -> dict:
    out = onboarding.onboard(ctx, body)
    ctx.db.commit()
    return out


@router.get("", summary="Employees in your data scope, with their current jobs")
def list_(request: Request, ctx: C, q: Optional[str] = None, page: int = 1, size: int = 50, as_of: Optional[date] = None) -> dict:
    return onboarding.list_employees(ctx, dict(request.query_params), q, page, size, as_of)


@router.get("/{person_rid}", summary="Employee profile (as_of a date)")
def get_(person_rid: int, ctx: C, as_of: Optional[date] = None) -> dict:
    return onboarding.profile(ctx, person_rid, as_of)


@router.put("/{person_rid}", summary="Change person details from effective_from (earlier than today = needs approval)")
def change(person_rid: int, body: PersonChange, ctx: C, response: Response) -> dict:  # type: ignore[valid-type]
    data, eff, reason = split_change(body.model_dump(exclude_unset=True))  # type: ignore[attr-defined]
    row, pending = engine.change(ctx, P, person_rid, data, eff, reason)
    return _done(ctx, response, row, pending, P)


@router.post("/{person_rid}/assignments", status_code=201, summary="Add another job (its own entity, location, pay share, manager)")
def add_job(person_rid: int, body: AssignmentIn, ctx: C) -> dict:
    engine.get_record(ctx, P, person_rid)
    out = onboarding.add_assignment(ctx, person_rid, body, bool(body.is_primary), "Additional job")
    ctx.db.commit()
    return out


@router.put("/{person_rid}/assignments/{rid}", summary="Change a job: transfer, promotion, pay share (from effective_from)")
def change_job(person_rid: int, rid: int, body: JobChange, ctx: C, response: Response) -> dict:  # type: ignore[valid-type]
    _job_of(ctx, person_rid, rid)
    data, eff, reason = split_change(body.model_dump(exclude_unset=True))  # type: ignore[attr-defined]
    data.pop("person_rid", None)  # a job never moves to another person
    row, pending = engine.change(ctx, A, rid, data, eff, reason)
    return _done(ctx, response, row, pending, A)


@router.post("/{person_rid}/assignments/{rid}/end", summary="End a job on end_date (exit or end of a second job)")
def end_job(person_rid: int, rid: int, body: EndRecord, ctx: C, response: Response) -> dict:
    _job_of(ctx, person_rid, rid)
    row, pending = engine.end(ctx, A, rid, body.end_date, body.change_reason)
    ctx.db.commit()
    if pending is not None:
        response.status_code = 202
        return {"message": "Backdated: saved for approval.", "pending_change": engine.pending_out(pending)}
    return {"rid": rid, "valid_to": row.valid_to, "message": f"Job ends on {row.valid_to}."}


@router.post("/{person_rid}/login", status_code=201, summary="Give this person a login (temporary password shown once)")
def login(person_rid: int, body: LoginIn, ctx: C) -> dict:
    rec = engine.get_record(ctx, P, person_rid)
    name = " ".join(x for x in (rec.get("first_name"), rec.get("last_name")) if x)
    scope = body.model_dump(include=set(users.SCOPE_KEYS))
    u, pw = users.create_user(ctx, body.email, name, body.roles, person_rid, scope)
    ctx.db.commit()
    return {**users.user_out(u), "temporary_password": pw}


class Reason(BaseModel):
    change_reason: Optional[str] = Field(None, max_length=300)


@router.post("/{person_rid}/deactivate", summary="Deactivate the person (end the jobs first); the login is disabled")
def deactivate(person_rid: int, body: Reason, ctx: C) -> dict:
    out = onboarding.deactivate_person(ctx, person_rid, body.change_reason)
    ctx.db.commit()
    return out


@router.delete("/{person_rid}", status_code=405, summary="Not allowed: deactivate instead")
def delete(person_rid: int, ctx: C) -> dict:
    raise HTTPException(405, "Employees are never deleted. End the jobs, then POST /api/employee/{person_rid}/deactivate.")
