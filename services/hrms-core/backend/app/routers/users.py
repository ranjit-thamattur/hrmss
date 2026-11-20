"""16 Users and roles: one login per person. Roles and data scope are checked on every call."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from .. import models as m
from ..core import access
from ..deps import C
from ..services import users

router = APIRouter(prefix="/api/users", tags=["16 Users and roles"])


class UserIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    email: str = Field(..., max_length=200)
    display_name: str = Field(..., min_length=1, max_length=200)
    roles: list[str] = Field(..., min_length=1)
    person_rid: Optional[int] = None
    scope_entity_rids: list[int] = []
    scope_location_rids: list[int] = []
    scope_department_rids: list[int] = []


class UserChange(BaseModel):
    model_config = ConfigDict(extra="ignore")
    display_name: Optional[str] = Field(None, min_length=1, max_length=200)
    roles: Optional[list[str]] = Field(None, min_length=1)
    scope_entity_rids: Optional[list[int]] = None
    scope_location_rids: Optional[list[int]] = None
    scope_department_rids: Optional[list[int]] = None


@router.get("", summary="List logins")
def list_users(ctx: C, include_inactive: bool = False, q: Optional[str] = None) -> list:
    access.require(ctx, "users", "view")
    s = select(m.AppUser).where(m.AppUser.client_id == ctx.client_id).order_by(m.AppUser.email)
    if not include_inactive:
        s = s.where(m.AppUser.is_active.is_(True))
    if q:
        s = s.where(m.AppUser.email.ilike(f"%{q}%") | m.AppUser.display_name.ilike(f"%{q}%"))
    return [users.user_out(u) for u in ctx.db.scalars(s)]


@router.post("", status_code=201, summary="Create a login (temporary password shown once)")
def create(body: UserIn, ctx: C) -> dict:
    scope = body.model_dump(include=set(users.SCOPE_KEYS))
    u, pw = users.create_user(ctx, body.email, body.display_name, body.roles, body.person_rid, scope)
    ctx.db.commit()
    return {**users.user_out(u), "temporary_password": pw}


@router.get("/{user_id}", summary="One login")
def get_user(user_id: int, ctx: C) -> dict:
    access.require(ctx, "users", "view")
    return users.user_out(users.get_user(ctx, user_id))


@router.put("/{user_id}", summary="Change name, roles or data scope")
def change(user_id: int, body: UserChange, ctx: C) -> dict:
    u = users.update_user(ctx, user_id, body.model_dump(exclude_unset=True))
    ctx.db.commit()
    return users.user_out(u)


@router.post("/{user_id}/deactivate", summary="Disable the login (never deleted)")
def deactivate(user_id: int, ctx: C) -> dict:
    u = users.set_active(ctx, user_id, False)
    ctx.db.commit()
    return users.user_out(u)


@router.post("/{user_id}/activate", summary="Enable the login again")
def activate(user_id: int, ctx: C) -> dict:
    u = users.set_active(ctx, user_id, True)
    ctx.db.commit()
    return users.user_out(u)


@router.post("/{user_id}/reset-password", summary="New temporary password (shown once)")
def reset_password(user_id: int, ctx: C) -> dict:
    pw = users.reset_password(ctx, user_id)
    ctx.db.commit()
    return {"user_id": user_id, "temporary_password": pw, "note": "Shown once. Must be changed at next sign-in."}


@router.delete("/{user_id}", status_code=405, summary="Not allowed: deactivate instead")
def delete(user_id: int, ctx: C) -> dict:
    from fastapi import HTTPException

    users.get_user(ctx, user_id)
    raise HTTPException(405, "Logins are never deleted. Use POST /api/users/{id}/deactivate.")
