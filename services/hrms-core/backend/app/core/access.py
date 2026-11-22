"""Who may do what, on which records, seeing which fields. All of it is DATA (entity 27, role permissions),
checked on the server on every call. The menu of a future frontend may hide things, but this decides.

Scope modes of a permission row:
    all      every record of the client
    scoped   only the user's legal entities / locations / departments (empty list = no limit on that one).
             Limits flow through the dated links: a user limited to a location sees the entities operating there
             (entity at location) and the departments of those entities (department in entity).
    team     the user's own person and the people who report to them (current reporting lines)
    self     the user's own person only
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, not_, or_, select

from .. import models as m
from .context import Ctx, current

RANK = {"all": 4, "scoped": 3, "team": 2, "self": 1}


def L(values: Any) -> list[int]:
    """SQL IN lists must be lists (never sets); an empty list becomes [-1] so nothing matches."""
    out = sorted(values) if values else []
    return out or [-1]


# ---------------------------------------------------------------- permissions
def _rows(ctx: Ctx) -> list[m.RolePermission]:
    if "perm_rows" not in ctx.cache:
        roles = list(ctx.user.roles or []) if ctx.user else []
        rp = m.RolePermission
        ctx.cache["perm_rows"] = list(ctx.db.scalars(select(rp).where(
            rp.client_id == ctx.client_id, current(rp, ctx.today), rp.is_active.is_(True), rp.role.in_(roles or ["-"]))))
    return ctx.cache["perm_rows"]


def grant(ctx: Ctx, resource: str, action: str) -> str | None:
    """Best scope mode the user's roles give for this action on this resource, or None."""
    if ctx.system:
        return "all"
    best = None
    for r in _rows(ctx):
        if r.resource in (resource, "*") and action in (r.actions or []):
            mode = r.scope or "scoped"
            if best is None or RANK.get(mode, 0) > RANK.get(best, 0):
                best = mode
    return best


def require(ctx: Ctx, resource: str, action: str) -> str:
    mode = grant(ctx, resource, action)
    if not mode:
        raise HTTPException(403, f"Your role cannot {action} {resource}.")
    return mode


def masked_fields(ctx: Ctx, resource: str) -> set[str]:
    """A field is shown masked unless one of the user's roles that can view the resource shows it in full."""
    if ctx.system:
        return set()
    sets = [set(r.masked_fields or []) for r in _rows(ctx) if r.resource in (resource, "*") and "view" in (r.actions or [])]
    if not sets:
        return set()
    out = sets[0]
    for s in sets[1:]:
        out &= s
    return out


def permissions_summary(ctx: Ctx) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for r in _rows(ctx):
        cur = out.setdefault(r.resource, {"actions": set(), "scope": r.scope})
        cur["actions"] |= set(r.actions or [])
        if RANK.get(r.scope, 0) > RANK.get(cur["scope"], 0):
            cur["scope"] = r.scope
    return {k: {"actions": sorted(v["actions"]), "scope": v["scope"]} for k, v in sorted(out.items())}


# ---------------------------------------------------------------- data scope
@dataclass
class Scope:
    mode: str
    entities: set[int] | None = None  # None = no limit
    locations: set[int] | None = None
    departments: set[int] | None = None
    persons: set[int] | None = None  # team / self modes

    def allowed(self, dim: str) -> set[int] | None:
        return {"entity": self.entities, "location": self.locations, "department": self.departments}[dim]


def resolve_scope(ctx: Ctx, mode: str) -> Scope:
    key = f"scope:{mode}"
    if key in ctx.cache:
        return ctx.cache[key]
    if mode == "all" or ctx.system:
        sc = Scope("all")
    elif mode == "scoped":
        u = ctx.user
        ents = set(u.scope_entity_rids or []) or None
        locs = set(u.scope_location_rids or []) or None
        deps = set(u.scope_department_rids or []) or None
        el, de = m.EntityLocation, m.DepartmentEntity
        live_el = and_(el.client_id == ctx.client_id, current(el, ctx.today), el.is_active.is_(True))
        if ents is None and locs is not None:
            ents = set(ctx.db.scalars(select(el.legal_entity_rid).where(live_el, el.location_rid.in_(L(locs)))))
        if locs is None and ents is not None:
            locs = set(ctx.db.scalars(select(el.location_rid).where(live_el, el.legal_entity_rid.in_(L(ents)))))
        if deps is None and ents is not None:
            deps = set(ctx.db.scalars(select(de.department_rid).where(
                de.client_id == ctx.client_id, current(de, ctx.today), de.is_active.is_(True), de.legal_entity_rid.in_(L(ents)))))
        sc = Scope("scoped", ents, locs, deps)
    else:
        me = ctx.person_rid
        persons: set[int] = {me} if me else set()
        if mode == "team" and me:
            rl, ea = m.ReportingLine, m.EmploymentAssignment
            team = ctx.db.scalars(select(ea.person_rid).where(
                ea.client_id == ctx.client_id, current(ea, ctx.today), ea.is_active.is_(True),
                ea.rid.in_(select(rl.assignment_rid).where(rl.client_id == ctx.client_id, current(rl, ctx.today), rl.is_active.is_(True),
                                                           rl.reports_to_person_rid == me))))
            persons |= set(team)
        sc = Scope(mode, persons=persons)
    ctx.cache[key] = sc
    return sc


def _assignments_in_scope(ctx: Ctx, sc: Scope) -> Any:
    """Subquery: rids of current assignments inside the scope."""
    ea = m.EmploymentAssignment
    conds = [ea.client_id == ctx.client_id, current(ea, ctx.today)]
    if sc.mode == "scoped":
        for col, allowed in ((ea.legal_entity_rid, sc.entities), (ea.location_rid, sc.locations), (ea.department_rid, sc.departments)):
            if allowed is not None:
                conds.append(col.in_(L(allowed)))
    else:
        conds.append(ea.person_rid.in_(L(sc.persons)))
    return select(ea.rid).where(*conds)


def _persons_in_scope(ctx: Ctx, sc: Scope) -> Any:
    ea = m.EmploymentAssignment
    if sc.mode != "scoped":
        return None
    inside = select(ea.person_rid).where(ea.rid.in_(_assignments_in_scope(ctx, sc)))
    any_job = select(ea.person_rid).where(ea.client_id == ctx.client_id)
    return (inside, any_job)


def scope_conditions(ctx: Ctx, spec: Any, model: Any, sc: Scope) -> list[Any]:
    """SQL conditions that keep a list inside the user's data scope."""
    if sc.mode == "all":
        return []
    special = spec.scope_special
    if special == "person":
        if sc.mode == "scoped":
            if sc.entities is None and sc.locations is None and sc.departments is None:
                return []
            inside, any_job = _persons_in_scope(ctx, sc)
            # people with a job inside the scope, plus people not yet given any job (being onboarded)
            return [or_(model.rid.in_(inside), not_(model.rid.in_(any_job)))]
        return [model.rid.in_(L(sc.persons))]
    if special == "assignment":
        return [model.assignment_rid.in_(_assignments_in_scope(ctx, sc))]
    if special == "owner":
        if sc.mode != "scoped":
            return [or_(and_(model.owner_type == "persons", model.owner_rid.in_(L(sc.persons))),
                        and_(model.owner_type == "employment-assignments", model.owner_rid.in_(_assignments_in_scope(ctx, sc))))]
        parts = [model.owner_type.notin_(["legal-entities", "locations", "persons", "employment-assignments"])]
        parts.append(and_(model.owner_type == "legal-entities", true_or_in(model.owner_rid, sc.entities)))
        parts.append(and_(model.owner_type == "locations", true_or_in(model.owner_rid, sc.locations)))
        persons = _persons_in_scope(ctx, sc)
        if persons is None or (sc.entities is None and sc.locations is None and sc.departments is None):
            parts.append(model.owner_type.in_(["persons", "employment-assignments"]))
        else:
            parts.append(and_(model.owner_type == "persons", or_(model.owner_rid.in_(persons[0]), not_(model.owner_rid.in_(persons[1])))))
            parts.append(and_(model.owner_type == "employment-assignments", model.owner_rid.in_(_assignments_in_scope(ctx, sc))))
        return [or_(*parts)]
    if special == "location_list":
        return []  # filtered after loading (JSON list), see keep_row()
    conds = []
    if spec.key == "employment-assignments" and sc.mode != "scoped":
        return [model.person_rid.in_(L(sc.persons))]
    if sc.mode != "scoped":
        return conds  # team/self roles see reference data (if they may view it) without a location limit
    for fname, dim in spec.scope.items():
        allowed = sc.allowed(dim)
        if allowed is None:
            continue
        col = model.rid if fname == "rid" else getattr(model, fname)
        optional = fname != "rid" and not spec.f(fname).required
        conds.append(or_(col.is_(None), col.in_(L(allowed))) if optional else col.in_(L(allowed)))
    return conds


def true_or_in(col: Any, allowed: set[int] | None) -> Any:
    return col.isnot(None) if allowed is None else col.in_(L(allowed))


def keep_row(spec: Any, row: Any, sc: Scope) -> bool:
    """Python-side scope filter for JSON lists (holiday calendars' locations)."""
    if spec.scope_special != "location_list" or sc.mode != "scoped" or sc.locations is None:
        return True
    locs = set(row.location_rids or [])
    return not locs or bool(locs & sc.locations)


def check_write(ctx: Ctx, spec: Any, mode: str, values: dict[str, Any], rid: int | None) -> None:
    """A user may only create or change records inside their scope."""
    if mode == "all" or ctx.system:
        return
    sc = resolve_scope(ctx, mode)
    out = HTTPException(403, f"This {spec.title.lower()} is outside your data scope.")
    if sc.mode in ("team", "self"):
        if spec.key == "persons" and rid in (sc.persons or set()):
            return
        if spec.key == "employment-assignments" and values.get("person_rid") in (sc.persons or set()):
            return
        raise out
    for fname, dim in spec.scope.items():
        allowed = sc.allowed(dim)
        if allowed is None:
            continue
        if fname == "rid":
            if rid is None or rid not in allowed:
                raise out
            continue
        v = values.get(fname)
        if v is not None and v not in allowed:
            raise out
    if spec.scope_special == "location_list" and sc.locations is not None:
        if not set(values.get("location_rids") or []) <= sc.locations:
            raise out
    if spec.scope_special == "assignment" and values.get("assignment_rid") is not None:
        ok = ctx.db.scalar(select(m.EmploymentAssignment.rid).where(m.EmploymentAssignment.rid == values["assignment_rid"],
                                                                     m.EmploymentAssignment.rid.in_(_assignments_in_scope(ctx, sc))).limit(1))
        if ok is None:
            raise out
    if spec.key == "persons" and rid is not None:
        conds = scope_conditions(ctx, spec, m.Person, sc)
        if conds and ctx.db.scalar(select(m.Person.rid).where(m.Person.client_id == ctx.client_id, m.Person.rid == rid, *conds).limit(1)) is None:
            raise out
