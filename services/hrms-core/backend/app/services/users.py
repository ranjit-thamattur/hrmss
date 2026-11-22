"""16 User and role: one login per person, whatever the number of employments. Identity lives in Cognito
(cognito-local on laptops); roles and data scope live here and are checked on every call.
"""
from __future__ import annotations

import secrets
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

from .. import models as m
from ..core import access
from ..core.audit import record
from ..core.context import Ctx, current
from ..core.identity import get_identity
from ..core.records import active_at

SCOPE_KEYS = ("scope_entity_rids", "scope_location_rids", "scope_department_rids")


def temp_password() -> str:
    return "Hr" + secrets.token_urlsafe(6).replace("-", "x").replace("_", "y") + "9a"


def user_out(u: m.AppUser) -> dict[str, Any]:
    return {"id": u.id, "email": u.email, "display_name": u.display_name, "person_rid": u.person_rid, "roles": u.roles or [],
            "scope_entity_rids": u.scope_entity_rids or [], "scope_location_rids": u.scope_location_rids or [],
            "scope_department_rids": u.scope_department_rids or [], "is_active": u.is_active, "must_change_password": u.must_change_password,
            "last_login_at": u.last_login_at, "created_by": u.created_by, "created_at": u.created_at}


def _known_roles(ctx: Ctx) -> set[str]:
    rp = m.RolePermission
    return set(ctx.db.scalars(select(rp.role).where(rp.client_id == ctx.client_id, current(rp, ctx.today), rp.is_active.is_(True))))


def _check(ctx: Ctx, roles: list[str] | None, scope: dict[str, Any]) -> None:
    if roles is not None:
        if "master_admin" in roles and ctx.user is not None and "master_admin" not in (ctx.user.roles or []):
            raise HTTPException(403, "Only a master admin can give the master_admin role.")
        unknown = set(roles) - _known_roles(ctx)
        if unknown:
            raise HTTPException(422, f"Unknown roles: {', '.join(sorted(unknown))}. Roles are defined in role permissions.")
    for key, spec_key in zip(SCOPE_KEYS, ("legal-entities", "locations", "departments"), strict=True):
        for rid in scope.get(key) or []:
            if active_at(ctx, spec_key, rid, ctx.today) is None:
                raise HTTPException(422, f"{key}: {spec_key} {rid} does not exist or is not active.")


def get_user(ctx: Ctx, user_id: int) -> m.AppUser:
    u = ctx.db.scalar(select(m.AppUser).where(m.AppUser.id == user_id, m.AppUser.client_id == ctx.client_id))
    if u is None:
        raise HTTPException(404, "User not found.")
    return u


def create_user(ctx: Ctx, email: str, display_name: str, roles: list[str], person_rid: int | None = None,
                scope: dict[str, Any] | None = None) -> tuple[m.AppUser, str]:
    access.require(ctx, "users", "create")
    email = email.strip().lower()
    scope = scope or {}
    if ctx.db.scalar(select(m.AppUser.id).where(m.AppUser.email == email)):
        raise HTTPException(409, f"A login for {email} already exists.")
    if person_rid is not None:
        if active_at(ctx, "persons", person_rid, ctx.today) is None:
            raise HTTPException(422, f"Person {person_rid} does not exist or is not active.")
        other = ctx.db.scalar(select(m.AppUser.email).where(m.AppUser.client_id == ctx.client_id, m.AppUser.person_rid == person_rid))
        if other:
            raise HTTPException(409, f"Person {person_rid} already has a login ({other}). One login per person.")
    if not roles:
        raise HTTPException(422, "Give at least one role.")
    _check(ctx, roles, scope)
    u = m.AppUser(client_id=ctx.client_id, email=email, display_name=display_name.strip(), person_rid=person_rid, roles=list(roles),
                  created_by=ctx.actor, **{k: list(scope.get(k) or []) for k in SCOPE_KEYS})
    ctx.db.add(u)
    ctx.db.flush()
    pw = temp_password()
    u.identity_sub = get_identity().create_user(ctx.db, u, pw)
    record(ctx, "create", "users", u.id, None, {"email": email, "roles": roles, "person_rid": person_rid, **scope})
    return u, pw


def update_user(ctx: Ctx, user_id: int, changes: dict[str, Any]) -> m.AppUser:
    access.require(ctx, "users", "change")
    u = get_user(ctx, user_id)
    _check(ctx, changes.get("roles"), changes)
    before = {k: getattr(u, k) for k in changes}
    for k, v in changes.items():
        setattr(u, k, v)
    if "roles" in changes:
        get_identity().set_groups(ctx.db, u)
    record(ctx, "change", "users", u.id, before, changes)
    return u


def set_active(ctx: Ctx, user_id: int, active: bool) -> m.AppUser:
    access.require(ctx, "users", "deactivate")
    u = get_user(ctx, user_id)
    if ctx.user is not None and u.id == ctx.user.id and not active:
        raise HTTPException(409, "You cannot deactivate your own login.")
    u.is_active = active
    get_identity().set_enabled(ctx.db, u, active)
    record(ctx, "activate" if active else "deactivate", "users", u.id, None, {"is_active": active})
    return u


def reset_password(ctx: Ctx, user_id: int) -> str:
    access.require(ctx, "users", "change")
    u = get_user(ctx, user_id)
    pw = temp_password()
    idp = get_identity()
    if idp.mode == "local":
        idp.create_user(ctx.db, u, pw)
    else:
        pool, _ = idp.ids(ctx.db)
        idp.client.admin_set_user_password(UserPoolId=pool, Username=u.email, Password=pw, Permanent=False)
    u.must_change_password = True
    record(ctx, "reset_password", "users", u.id, None, {"email": u.email})
    return pw
