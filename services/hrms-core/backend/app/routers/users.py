"""Users and access. Converting an employee to a user is a separate, explicit step."""
from __future__ import annotations

import secrets
import string

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from .. import models as m
from ..deps import DB, User
from ..serial import row, user_dict
from ..services.access import ROLES, require
from ..services.audit import record
from ..services.provisioning import queue, run_task, tasks_for

router = APIRouter(prefix="/api/users", tags=["users"])


def temp_password() -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        p = "".join(secrets.choice(alphabet) for _ in range(10)) + "a1A"
        if any(c.isupper() for c in p) and any(c.islower() for c in p) and any(c.isdigit() for c in p):
            return p


class UserIn(BaseModel):
    email: str
    display_name: str | None = None
    employee_id: int | None = None
    roles: list[str]
    entity_scope: list[int] = []
    location_scope: list[int] = []


class UserPatch(BaseModel):
    roles: list[str] | None = None
    entity_scope: list[int] | None = None
    location_scope: list[int] | None = None
    display_name: str | None = None


def _check_roles(roles: list[str]) -> None:
    bad = [r for r in roles if r not in ROLES]
    if bad or not roles:
        raise HTTPException(400, f"Unknown or missing roles: {bad or 'none given'}. Use: {', '.join(ROLES)}")


@router.get("/roles")
def roles(user: User) -> dict:
    return ROLES


@router.get("")
def list_users(user: User, db: DB) -> list[dict]:
    require(user, "users.manage")
    out = []
    for u in db.scalars(select(m.AppUser).order_by(m.AppUser.email)):
        t = tasks_for(db, user_id=u.id)
        out.append({**user_dict(u), "identity_status": t[0].status if t else None, "identity_error": t[0].last_error if t else None})
    return out


@router.post("")
def create_user(body: UserIn, user: User, db: DB) -> dict:
    """Create a user (from an employee or standalone) and provision it to the identity provider.
    Returns the temporary password once; the person must set their own at first sign-in."""
    require(user, "users.manage")
    _check_roles(body.roles)
    email = body.email.lower().strip()
    if "@" not in email:
        raise HTTPException(400, "A valid email is needed for sign-in")
    if db.scalar(select(m.AppUser.id).where(m.AppUser.email == email)):
        raise HTTPException(409, "A user with this email already exists")
    name = body.display_name
    if body.employee_id:
        e = db.get(m.Employee, body.employee_id)
        if not e:
            raise HTTPException(404, "Employee not found")
        if e.status == "exited":
            raise HTTPException(400, "Employee has exited")
        if db.scalar(select(m.AppUser.id).where(m.AppUser.employee_id == e.id)):
            raise HTTPException(409, "This employee already has a user")
        name = name or f"{e.first_name} {e.last_name}".strip()
        if not e.email:
            e.email = email
    u = m.AppUser(email=email, display_name=name or email, employee_id=body.employee_id, roles=body.roles,
                  entity_scope=body.entity_scope, location_scope=body.location_scope)
    db.add(u)
    db.flush()
    pw = temp_password()
    task = queue(db, target="identity", action="create", user_id=u.id, employee_id=body.employee_id, temp_password=pw, actor=user.email)
    record(db, user.email, "user_created", "user", u.id, after={"email": email, "roles": body.roles, "employee_id": body.employee_id},
           employee_id=body.employee_id)
    db.commit()
    return {**user_dict(u), "temporary_password": pw if task.status == "done" else None, "identity_status": task.status, "identity_error": task.last_error}


@router.patch("/{user_id}")
def update_user(user_id: int, body: UserPatch, user: User, db: DB) -> dict:
    require(user, "users.manage")
    u = db.get(m.AppUser, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    before = user_dict(u)
    if body.roles is not None:
        _check_roles(body.roles)
        if u.id == user.id and "master_admin" not in body.roles:
            raise HTTPException(400, "You cannot remove your own master admin role")
        u.roles = body.roles
    if body.entity_scope is not None:
        u.entity_scope = body.entity_scope
    if body.location_scope is not None:
        u.location_scope = body.location_scope
    if body.display_name:
        u.display_name = body.display_name
    if body.roles is not None:
        queue(db, target="identity", action="groups", user_id=u.id, actor=user.email)
    record(db, user.email, "user_updated", "user", u.id, before=before, after=user_dict(u), employee_id=u.employee_id)
    db.commit()
    return user_dict(u)


@router.post("/{user_id}/active")
def set_active(user_id: int, active: bool, user: User, db: DB) -> dict:
    require(user, "users.manage")
    u = db.get(m.AppUser, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    if u.id == user.id and not active:
        raise HTTPException(400, "You cannot deactivate yourself")
    u.is_active = active
    queue(db, target="identity", action="enable" if active else "disable", user_id=u.id, actor=user.email)
    record(db, user.email, "user_activated" if active else "user_deactivated", "user", u.id, employee_id=u.employee_id)
    db.commit()
    return user_dict(u)


@router.post("/{user_id}/reset-password")
def reset_password(user_id: int, user: User, db: DB) -> dict:
    """Local mode: new temporary password. Cognito mode: recreate the temporary password via admin API."""
    require(user, "users.manage")
    u = db.get(m.AppUser, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    from ..services.identity import CognitoIdentity, get_identity

    pw = temp_password()
    idp = get_identity()
    if isinstance(idp, CognitoIdentity):
        pool, _ = idp.ids(db)
        idp.client.admin_set_user_password(UserPoolId=pool, Username=u.email, Password=pw, Permanent=False)
    else:
        idp.create_user(db, u, pw)
    record(db, user.email, "password_reset", "user", u.id, employee_id=u.employee_id)
    db.commit()
    return {"temporary_password": pw}


@router.get("/provisioning")
def provisioning_tasks(user: User, db: DB, status: str | None = None) -> list[dict]:
    require(user, "users.manage")
    stmt = select(m.ProvisioningTask).order_by(m.ProvisioningTask.id.desc()).limit(300)
    if status:
        stmt = stmt.where(m.ProvisioningTask.status == status)
    out = []
    for t in db.scalars(stmt):
        e = db.get(m.Employee, t.employee_id) if t.employee_id else None
        u = db.get(m.AppUser, t.user_id) if t.user_id else None
        out.append(row(t, employee=f"{e.code} {e.first_name}" if e else None, user=u.email if u else None))
    return out


@router.post("/provisioning/{task_id}/retry")
def retry(task_id: int, user: User, db: DB) -> dict:
    require(user, "users.manage")
    t = db.get(m.ProvisioningTask, task_id)
    if not t:
        raise HTTPException(404, "Task not found")
    if t.status == "done":
        raise HTTPException(400, "Already done")
    pw = temp_password() if (t.target == "identity" and t.action == "create") else None
    run_task(db, t, temp_password=pw)
    record(db, user.email, "provision_retry", "provisioning", t.id, after={"status": t.status, "error": t.last_error}, employee_id=t.employee_id)
    db.commit()
    return {**row(t), "temporary_password": pw if t.status == "done" else None}


@router.post("/provisioning/{task_id}/confirm")
def confirm_manual(task_id: int, user: User, db: DB) -> dict:
    """Biometric without an API: HR confirms the person was enrolled on the device."""
    require(user, "employees.write")
    t = db.get(m.ProvisioningTask, task_id)
    if not t or t.status != "manual":
        raise HTTPException(400, "Only manual tasks can be confirmed")
    t.status = "done"
    record(db, user.email, "biometric_enrolment_confirmed", "provisioning", t.id, employee_id=t.employee_id)
    db.commit()
    return row(t)
