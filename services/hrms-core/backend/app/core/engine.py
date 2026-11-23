"""The generic operations every catalogue entity gets, with the eleven rules built in once:

  1 client from the login      every query is limited to ctx.client_id; a client_id in a request is ignored
  2 effective dating           a change adds a version from its effective date; reads take ?as_of=
  3 no overlaps, backdating    versions never overlap; dated unique keys refused if they overlap;
                               changes dated before today wait for approval (pending changes)
  4 deactivate, never delete   DELETE is refused; deactivate / reactivate add a version
  5 unique codes               per client, not case-sensitive
  6 audit log                  every create / change / deactivation / approval, before and after, masked
  7 data scope                 lists and writes limited by the role's scope (access.py)
  8 masking                    sensitive fields masked by role (access.masked_fields)
  9 Excel import               importer.py, row by row, through create()
 10 dependency checks          references must point to an active record on the effective date
 11 client isolation           one client per AWS account and database; inside the database, rule 1 again

Functions do not commit: the caller (a router or a service) commits once, so a request is all or nothing.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_, select

from .. import models as m
from . import access, dating
from .audit import diff, jsonable, record
from .context import Ctx, current, overlapping
from .hooks import HOOKS
from .masking import mask_documents, mask_value
from .records import at, display, encode, model, must_exist, plain
from .security import decrypt, encrypt
from .specs import SPECS, Spec

SYSTEM_COLS = ("rid", "valid_from", "valid_to", "is_active")


# ---------------------------------------------------------------- reading
def out_record(ctx: Ctx, spec: Spec, row: Any, masked: set[str], refs: dict[tuple[str, int], dict] | None = None,
               version_no: int | None = None) -> dict[str, Any]:
    vals = plain(spec, row)
    out: dict[str, Any] = {
        "rid": row.rid, "version_id": row.id, "valid_from": row.valid_from, "valid_to": row.valid_to, "is_active": row.is_active,
        "status": dating.status(row.valid_from, row.valid_to, row.is_active, ctx.today),
        "created_by": row.created_by, "created_at": row.created_at, "change_reason": row.change_reason,
    }
    if version_no is not None:
        out["version"] = version_no
    for f in spec.fields:
        v = vals[f.name]
        if f.name in masked and v:
            v = mask_documents(v) if f.kind == "secret_json" else mask_value(v)
        out[f.name] = v
        if f.kind == "ref" and refs is not None:
            out[f.name.removesuffix("_rid")] = refs.get((f.ref, v)) if v is not None else None
    if spec.key == "persons":
        out["display_name"] = display(spec, row)
    return out


def ref_map(ctx: Ctx, spec: Spec, rows: list[Any], on: date) -> dict[tuple[str, int], dict]:
    """{(target key, rid): {rid, code, name}} for every reference in `rows`, read in one query per target."""
    wanted: dict[str, set[int]] = {}
    for r in rows:
        for f in spec.ref_fields:
            v = getattr(r, f.name)
            if f.kind == "ref" and v is not None:
                wanted.setdefault(f.ref, set()).add(v)
    out: dict[tuple[str, int], dict] = {}
    for key, rids in wanted.items():
        t = SPECS[key]
        md = model(t)
        for row in ctx.db.scalars(select(md).where(md.client_id == ctx.client_id, md.rid.in_(sorted(rids)), current(md, on))):
            out[(key, row.rid)] = {"rid": row.rid, "code": getattr(row, t.code_field) if t.code_field else None, "name": display(t, row)}
    return out


def _filters(spec: Spec, md: Any, filters: dict[str, str]) -> list[Any]:
    conds = []
    for name, raw in filters.items():
        if raw in (None, "") or name not in [f.name for f in spec.fields]:
            continue
        f = spec.f(name)
        col = getattr(md, name)
        if f.kind in ("ref", "int", "year"):
            try:
                conds.append(col == int(raw))
            except ValueError as e:
                raise HTTPException(422, f"Filter {name} must be a number.") from e
        elif f.kind == "bool":
            conds.append(col.is_(str(raw).lower() in ("1", "true", "yes")))
        elif f.kind in ("str", "enum", "period", "email") and name == spec.code_field:
            conds.append(func.lower(col) == str(raw).lower())
        elif f.kind in ("str", "enum", "period", "email", "time"):
            conds.append(col == raw)
    return conds


def list_records(ctx: Ctx, spec: Spec, *, on: date | None = None, include_inactive: bool = False, filters: dict[str, str] | None = None,
                 q: str | None = None, page: int = 1, size: int = 50) -> dict[str, Any]:
    mode = access.require(ctx, spec.key, "view")
    sc = access.resolve_scope(ctx, mode)
    on = on or ctx.today
    md = model(spec)
    conds = [md.client_id == ctx.client_id, current(md, on), *_filters(spec, md, filters or {}), *access.scope_conditions(ctx, spec, md, sc)]
    if not include_inactive:
        conds.append(md.is_active.is_(True))
    if q:
        cols = [getattr(md, c) for c in (spec.code_field, spec.name_field) if c]
        if spec.key == "persons":
            cols += [md.last_name, md.email]
        if cols:
            conds.append(or_(*[c.ilike(f"%{q}%") for c in cols]))
    order = [getattr(md, c) for c in (spec.code_field, spec.name_field) if c] + [md.rid]
    stmt = select(md).where(*conds).order_by(*order)
    size = max(1, min(size, 500))
    if spec.scope_special == "location_list":  # JSON list: filter in Python
        rows = [r for r in ctx.db.scalars(stmt) if access.keep_row(spec, r, sc)]
        total, rows = len(rows), rows[(page - 1) * size: page * size]
    else:
        total = ctx.db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
        rows = list(ctx.db.scalars(stmt.offset((max(page, 1) - 1) * size).limit(size)))
    masked = access.masked_fields(ctx, spec.key)
    refs = ref_map(ctx, spec, rows, on)
    return {"total": total, "page": page, "size": size, "as_of": on, "items": [out_record(ctx, spec, r, masked, refs) for r in rows]}


def _visible(ctx: Ctx, spec: Spec, rid: int, mode: str) -> None:
    """404 (not 403) for a record outside the user's scope, so other records' existence is not revealed."""
    sc = access.resolve_scope(ctx, mode)
    md = model(spec)
    conds = access.scope_conditions(ctx, spec, md, sc)
    hit = ctx.db.scalar(select(md).where(md.client_id == ctx.client_id, md.rid == rid, *conds).order_by(md.valid_from.desc()).limit(1))
    if hit is None or not access.keep_row(spec, hit, sc):
        raise HTTPException(404, f"{spec.title} {rid} not found.")


def get_record(ctx: Ctx, spec: Spec, rid: int, on: date | None = None) -> dict[str, Any]:
    mode = access.require(ctx, spec.key, "view")
    vs = must_exist(ctx, spec, rid)
    _visible(ctx, spec, rid, mode)
    on = on or ctx.today
    idx = next((i for i, r in enumerate(vs) if dating.covers(r.valid_from, r.valid_to, on)), None)
    if idx is None:
        raise HTTPException(404, f"{spec.title} {rid} has no version in force on {on} (it runs {vs[0].valid_from} to {vs[-1].valid_to or 'open'}).")
    row = vs[idx]
    return out_record(ctx, spec, row, access.masked_fields(ctx, spec.key), ref_map(ctx, spec, [row], on), version_no=idx + 1)


def history(ctx: Ctx, spec: Spec, rid: int) -> list[dict[str, Any]]:
    mode = access.require(ctx, spec.key, "view")
    vs = must_exist(ctx, spec, rid)
    _visible(ctx, spec, rid, mode)
    masked = access.masked_fields(ctx, spec.key)
    return [out_record(ctx, spec, r, masked, ref_map(ctx, spec, [r], r.valid_from), version_no=i + 1) for i, r in enumerate(vs)]


# ---------------------------------------------------------------- validation (rules 3, 5, 10 and the entity hooks)
def _same(md: Any, name: str, value: Any) -> Any:
    col = getattr(md, name)
    return col.is_(None) if value is None else col == value


def validate(ctx: Ctx, spec: Spec, values: dict[str, Any], start: date, end: date | None, rid: int | None, check_refs: set[str],
             op: str) -> dict[str, Any]:
    md = model(spec)
    other = md.rid != rid if rid is not None else md.rid.isnot(None)
    # 5 unique codes (not case-sensitive), against every other record of the client, active or not
    if spec.code_field and values.get(spec.code_field):
        code = str(values[spec.code_field]).strip()
        values[spec.code_field] = code
        clash = ctx.db.scalar(select(md.rid).where(md.client_id == ctx.client_id, other, func.lower(getattr(md, spec.code_field)) == code.lower()).limit(1))
        if clash is not None:
            raise HTTPException(409, f"{spec.title} code '{code}' is already used by record {clash} (codes are not case-sensitive).")
    # 10 dependency checks: references must point to records that exist and are active on the start date
    for f in spec.ref_fields:
        if f.name not in check_refs:
            continue
        targets = values.get(f.name) or [] if f.kind == "refs" else [values.get(f.name)]
        for t in targets:
            if t is None:
                continue
            row = at(ctx, SPECS[f.ref], t, start)
            if row is None or not row.is_active:
                raise HTTPException(422, f"{f.title}: {SPECS[f.ref].title.lower()} {t} does not exist or is not active on {start}.")
    if spec.key == "documents" and op == "create":
        owner = SPECS[values["owner_type"]]
        row = at(ctx, owner, values.get("owner_rid"), start)
        if row is None or not row.is_active:
            raise HTTPException(422, f"Owner {owner.title.lower()} {values.get('owner_rid')} does not exist or is not active on {start}.")
    # 3 no overlaps: dated unique keys
    for keys in spec.unique_overlap:
        conds = [md.client_id == ctx.client_id, other, md.is_active.is_(True), overlapping(md, start, end)] + [_same(md, k, values.get(k)) for k in keys]
        clash = ctx.db.scalar(select(md).where(*conds).limit(1))
        if clash is not None:
            what = ", ".join(f"{k}={values.get(k)}" for k in keys)
            raise HTTPException(409, f"Overlaps {spec.title.lower()} {clash.rid} ({what}), which runs {clash.valid_from} to "
                                     f"{clash.valid_to or 'open'}. End that one first or choose other dates.")
    for keys in spec.unique_fields:
        conds = [md.client_id == ctx.client_id, other, md.is_active.is_(True)] + [_same(md, k, values.get(k)) for k in keys]
        clash = ctx.db.scalar(select(md.rid).where(*conds).limit(1))
        if clash is not None:
            raise HTTPException(409, f"A {spec.title.lower()} with the same {', '.join(keys)} already exists (record {clash}).")
    if spec.hook:
        values = HOOKS[spec.hook](ctx, spec, values, start, end, rid, op)
    return values


# ---------------------------------------------------------------- writing
def create(ctx: Ctx, spec: Spec, data: dict[str, Any], valid_from: date | None = None, valid_to: date | None = None, reason: str | None = None,
           *, system_values: dict[str, Any] | None = None) -> Any:
    """Create a record (version 1). `data` = validated request values. A start date in the past is allowed
    for new records (initial set-up); only changes to existing history need approval."""
    mode = access.require(ctx, spec.key, "create")
    if not spec.creatable and system_values is None:
        raise HTTPException(405, f"{spec.title} records are created through their own endpoint.")
    start = valid_from or ctx.today
    if valid_to is not None and valid_to < start:
        raise HTTPException(422, "valid_to cannot be before valid_from.")
    values = {f.name: data.get(f.name, f.default) for f in spec.input_fields}
    values.update(system_values or {})
    access.check_write(ctx, spec, mode, values, None)
    values = validate(ctx, spec, values, start, valid_to, None, {f.name for f in spec.ref_fields}, "create")
    md = model(spec)
    row = md(client_id=ctx.client_id, valid_from=start, valid_to=valid_to, is_active=True, created_by=ctx.actor, change_reason=reason,
             **encode(spec, values))
    ctx.db.add(row)
    ctx.db.flush()
    row.rid = row.id
    ctx.db.flush()
    record(ctx, "create", spec.key, row.rid, None, {**values, "valid_from": start, "valid_to": valid_to}, reason, {f.name for f in spec.secret_fields})
    return row


def _apply(ctx: Ctx, spec: Spec, rid: int, updates: dict[str, Any], effective: date, reason: str | None, action: str,
           approved_by: str | None = None) -> Any:
    vs = must_exist(ctx, spec, rid)
    try:
        kind, i = dating.plan_change([(v.valid_from, v.valid_to) for v in vs], effective)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    cur = vs[i]
    before = {**plain(spec, cur), "is_active": cur.is_active}
    new = {**plain(spec, cur), **updates}
    active = {"deactivate": False, "reactivate": True}.get(action, cur.is_active)
    if action == "change":
        changed_refs = {k for k in updates if k in {f.name for f in spec.ref_fields} and updates[k] != before.get(k)}
        new = validate(ctx, spec, new, effective, cur.valid_to, rid, changed_refs, "change")
    elif action == "reactivate":
        new = validate(ctx, spec, new, effective, cur.valid_to, rid, {f.name for f in spec.ref_fields}, "reactivate")
    enc = encode(spec, new)
    if kind == "correct":
        for k, v in enc.items():
            setattr(cur, k, v)
        cur.is_active = active
        cur.change_reason = reason
        row = cur
    else:
        old_to = cur.valid_to
        cur.valid_to = dating.day_before(effective)
        row = model(spec)(client_id=ctx.client_id, rid=rid, valid_from=effective, valid_to=old_to, is_active=active, created_by=ctx.actor,
                          change_reason=reason, **enc)
        ctx.db.add(row)
    ctx.db.flush()
    b, a = diff(before, {**new, "is_active": active})
    record(ctx, action, spec.key, rid, {**b, "effective_from": None}, {**a, "effective_from": effective}, reason,
           {f.name for f in spec.secret_fields}, approved_by)
    return row


def _end(ctx: Ctx, spec: Spec, rid: int, end_date: date, reason: str | None, approved_by: str | None = None) -> Any:
    vs = must_exist(ctx, spec, rid)
    last = vs[-1]
    if end_date < last.valid_from:
        raise HTTPException(422, f"The latest version starts on {last.valid_from}; the end date must be on or after it.")
    before = last.valid_to
    last.valid_to = end_date
    ctx.db.flush()
    record(ctx, "end", spec.key, rid, {"valid_to": before}, {"valid_to": end_date}, reason, approved_by=approved_by)
    return last


def _seal(spec: Spec, payload: dict[str, Any]) -> dict[str, Any]:
    """Pending payloads keep secrets encrypted, like the records themselves."""
    import json

    out = jsonable(payload)
    for f in spec.secret_fields:
        if out.get(f.name):
            out[f.name] = {"enc": encrypt(json.dumps(out[f.name]))}
    return out


def _unseal(spec: Spec, payload: dict[str, Any]) -> dict[str, Any]:
    import json

    out = dict(payload or {})
    for f in spec.secret_fields:
        v = out.get(f.name)
        if isinstance(v, dict) and "enc" in v:
            raw = decrypt(v["enc"])
            out[f.name] = json.loads(raw) if raw else None
    return out


def _pending(ctx: Ctx, spec: Spec, rid: int, action: str, payload: dict[str, Any], effective: date, reason: str | None) -> m.PendingChange:
    pc = m.PendingChange(client_id=ctx.client_id, resource=spec.key, rid=rid, action=action, payload=_seal(spec, payload),
                         effective_from=effective, reason=reason, requested_by=ctx.actor)
    ctx.db.add(pc)
    ctx.db.flush()
    record(ctx, "change_requested", spec.key, rid, None, {"pending_change": pc.id, "action": action, "effective_from": effective, **payload}, reason,
           {f.name for f in spec.secret_fields})
    return pc


def _check_date(vs: list[Any], effective: date) -> None:
    """Refuse at request time (not at approval time) a change from a date the record does not cover."""
    try:
        dating.plan_change([(v.valid_from, v.valid_to) for v in vs], effective)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


def change(ctx: Ctx, spec: Spec, rid: int, data: dict[str, Any], effective: date | None, reason: str | None) -> tuple[Any | None, m.PendingChange | None]:
    """Change from `effective` (default today). Same day or later: applied now. Earlier: waits for approval."""
    mode = access.require(ctx, spec.key, "change")
    vs = must_exist(ctx, spec, rid)
    _visible(ctx, spec, rid, mode)
    effective = effective or ctx.today
    _check_date(vs, effective)
    names = {f.name for f in spec.input_fields}
    updates = {k: v for k, v in data.items() if k in names}
    if not updates:
        raise HTTPException(422, "Nothing to change: send at least one field.")
    cur = at(ctx, spec, rid, effective)
    access.check_write(ctx, spec, mode, {**(plain(spec, cur) if cur is not None else {}), **updates}, rid)
    if dating.is_backdated(effective, ctx.today):
        return None, _pending(ctx, spec, rid, "change", updates, effective, reason)
    return _apply(ctx, spec, rid, updates, effective, reason, "change"), None


def set_active(ctx: Ctx, spec: Spec, rid: int, active: bool, effective: date | None, reason: str | None) -> tuple[Any | None, m.PendingChange | None]:
    mode = access.require(ctx, spec.key, "deactivate")
    vs = must_exist(ctx, spec, rid)
    _visible(ctx, spec, rid, mode)
    effective = effective or ctx.today
    _check_date(vs, effective)
    cur = at(ctx, spec, rid, effective)
    access.check_write(ctx, spec, mode, plain(spec, cur) if cur is not None else {}, rid)
    action = "reactivate" if active else "deactivate"
    if dating.is_backdated(effective, ctx.today):
        return None, _pending(ctx, spec, rid, action, {}, effective, reason)
    return _apply(ctx, spec, rid, {}, effective, reason, action), None


def end(ctx: Ctx, spec: Spec, rid: int, end_date: date, reason: str | None) -> tuple[Any | None, m.PendingChange | None]:
    mode = access.require(ctx, spec.key, "change")
    vs = must_exist(ctx, spec, rid)
    _visible(ctx, spec, rid, mode)
    access.check_write(ctx, spec, mode, plain(spec, vs[-1]), rid)
    if dating.is_backdated(end_date, dating.day_before(ctx.today)):  # ending yesterday or earlier rewrites the past
        return None, _pending(ctx, spec, rid, "end", {"end_date": end_date}, end_date, reason)
    return _end(ctx, spec, rid, end_date, reason), None


def in_use(ctx: Ctx, spec: Spec, rid: int) -> dict[str, int]:
    """How many active records point to this one (shown when deactivating; deactivation is still allowed)."""
    out = {}
    for other in SPECS.values():
        for f in other.fields:
            if f.kind == "ref" and f.ref == spec.key:
                md = model(other)
                n = ctx.db.scalar(select(func.count()).select_from(md).where(
                    md.client_id == ctx.client_id, current(md, ctx.today), md.is_active.is_(True), getattr(md, f.name) == rid)) or 0
                if n:
                    out[f"{other.key}.{f.name}"] = n
    return out


# ---------------------------------------------------------------- approvals of backdated changes
def _workflow(ctx: Ctx) -> m.ApprovalWorkflow | None:
    aw = m.ApprovalWorkflow
    return ctx.db.scalar(select(aw).where(aw.client_id == ctx.client_id, current(aw, ctx.today), aw.is_active.is_(True),
                                          aw.request_type == "backdated_change"))


def _line_manager(ctx: Ctx, person_rid: int | None, level: int) -> int | None:
    ea, rl = m.EmploymentAssignment, m.ReportingLine
    p = person_rid
    for _ in range(level):
        if p is None:
            return None
        job = ctx.db.scalar(select(ea.rid).where(ea.client_id == ctx.client_id, ea.person_rid == p, current(ea, ctx.today), ea.is_active.is_(True))
                            .order_by(ea.is_primary.desc()).limit(1))
        p = ctx.db.scalar(select(rl.reports_to_person_rid).where(rl.client_id == ctx.client_id, rl.assignment_rid == job, rl.type == "line",
                                                                 current(rl, ctx.today), rl.is_active.is_(True))) if job else None
    return p


def _may_approve(ctx: Ctx, pc: m.PendingChange) -> None:
    if pc.requested_by == ctx.actor:
        raise HTTPException(403, "No one approves their own request.")
    wf = _workflow(ctx)
    if wf is None:
        access.require(ctx, pc.resource, "approve")
        return
    steps = wf.steps or []
    step = steps[min(pc.step, len(steps) - 1)]
    roles = set(ctx.user.roles or []) if ctx.user else set()
    if step.get("approver_type") == "role":
        allowed = {step["value"]} if isinstance(step["value"], str) else set(step["value"])
        if not roles & allowed:
            raise HTTPException(403, f"Step {pc.step + 1} of '{wf.name}' needs one of these roles: {', '.join(sorted(allowed))}.")
    else:
        requester = ctx.db.scalar(select(m.AppUser).where(m.AppUser.email == pc.requested_by))
        mgr = _line_manager(ctx, requester.person_rid if requester else None, int(step.get("value") or 1))
        if mgr is None or mgr != ctx.person_rid:
            raise HTTPException(403, f"Step {pc.step + 1} of '{wf.name}' needs the requester's manager (level {step.get('value')}).")


def decide(ctx: Ctx, pc_id: int, approve: bool, note: str | None) -> m.PendingChange:
    from datetime import datetime, timezone

    from .schemas import change_schema

    access.require(ctx, "changes", "view")
    pc = ctx.db.scalar(select(m.PendingChange).where(m.PendingChange.id == pc_id, m.PendingChange.client_id == ctx.client_id))
    if pc is None:
        raise HTTPException(404, "Pending change not found.")
    if pc.status != "pending":
        raise HTTPException(409, f"This change is already {pc.status}.")
    _may_approve(ctx, pc)
    pc.approvals = [*(pc.approvals or []), {"by": ctx.actor, "approve": approve, "note": note, "step": pc.step}]
    if not approve:
        pc.status, pc.decided_by, pc.decided_at, pc.note = "rejected", ctx.actor, datetime.now(timezone.utc), note
        record(ctx, "change_rejected", pc.resource, pc.rid, None, {"pending_change": pc.id}, note)
        return pc
    wf = _workflow(ctx)
    pc.step += 1
    if wf is not None and pc.step < len(wf.steps or []):
        record(ctx, "change_step_approved", pc.resource, pc.rid, None, {"pending_change": pc.id, "step": pc.step}, note)
        return pc
    spec = SPECS[pc.resource]
    # apply as the requester's change, approved by this user
    req = Ctx(db=ctx.db, client_id=ctx.client_id, actor=pc.requested_by, user=None, today=ctx.today)
    if pc.action == "change":
        updates = change_schema(spec.key)(**_unseal(spec, pc.payload)).model_dump(exclude_unset=True)
        updates.pop("effective_from", None)
        updates.pop("change_reason", None)
        _apply(req, spec, pc.rid, updates, pc.effective_from, pc.reason, "change", approved_by=ctx.actor)
    elif pc.action in ("deactivate", "reactivate"):
        _apply(req, spec, pc.rid, {}, pc.effective_from, pc.reason, pc.action, approved_by=ctx.actor)
    elif pc.action == "end":
        _end(req, spec, pc.rid, pc.effective_from, pc.reason, approved_by=ctx.actor)
    pc.status, pc.decided_by, pc.decided_at, pc.note = "approved", ctx.actor, datetime.now(timezone.utc), note
    return pc


def pending_out(pc: m.PendingChange) -> dict[str, Any]:
    spec = SPECS.get(pc.resource)
    payload = dict(pc.payload or {})
    for f in spec.secret_fields if spec else []:
        if f.name in payload:
            payload[f.name] = "XXXX (sensitive)"
    return {"id": pc.id, "resource": pc.resource, "rid": pc.rid, "action": pc.action, "payload": payload, "effective_from": pc.effective_from,
            "reason": pc.reason, "requested_by": pc.requested_by, "requested_at": pc.requested_at, "status": pc.status, "step": pc.step,
            "approvals": pc.approvals, "decided_by": pc.decided_by, "decided_at": pc.decided_at, "note": pc.note}
