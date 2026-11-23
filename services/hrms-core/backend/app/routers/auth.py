"""Health, sign-in, and who am I."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from .. import models as m
from ..config import get_settings
from ..core import access
from ..core.identity import get_identity
from ..deps import DB, C, touch_login

router = APIRouter(tags=["Sign-in"])
settings = get_settings()


class LoginIn(BaseModel):
    email: str
    password: str


class NewPasswordIn(BaseModel):
    email: str
    new_password: str
    session: str


@router.get("/api/health")
def health(db: DB) -> dict[str, Any]:
    db.execute(text("SELECT 1"))
    conf = settings.client.get("client") or {}
    return {"status": "ok", "app": settings.app_name, "version": settings.version, "client": conf.get("code"), "environment": settings.environment}


@router.post("/api/auth/login")
def login(body: LoginIn, db: DB) -> dict[str, Any]:
    res = get_identity().authenticate(db, body.email, body.password)
    if "token" in res:
        touch_login(db, body.email)
    return res


@router.post("/api/auth/new-password")
def new_password(body: NewPasswordIn, db: DB) -> dict[str, Any]:
    res = get_identity().complete_new_password(db, body.email, body.new_password, body.session)
    touch_login(db, body.email)
    return res


@router.get("/api/auth/me")
def me(ctx: C) -> dict[str, Any]:
    u = ctx.user
    client = ctx.db.get(m.Client, ctx.client_id)
    if client is None:
        raise HTTPException(500, "The user's client is missing.")
    return {"id": u.id, "email": u.email, "display_name": u.display_name, "person_rid": u.person_rid, "roles": u.roles or [],
            "scope": {"legal_entity_rids": u.scope_entity_rids or [], "location_rids": u.scope_location_rids or [],
                      "department_rids": u.scope_department_rids or []},
            "client": {"code": client.code, "name": client.name, "country": client.country, "currency": client.default_currency},
            "permissions": access.permissions_summary(ctx)}
