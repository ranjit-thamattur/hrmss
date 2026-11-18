from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select, text

from .. import models as m
from ..config import get_settings
from ..deps import DB, User
from ..serial import user_dict
from ..services.access import PERMISSIONS, ROLES, has, scope_employees
from ..services.identity import get_identity
from ..services.policies import policy
from ..tenant import tenant_code, tenant_name

router = APIRouter(prefix="/api", tags=["core"])
settings = get_settings()


@router.get("/health")
def health(db: DB) -> dict:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "app": settings.app_name, "tenant": tenant_code(), "version": settings.version, "environment": settings.environment,
            "auth_mode": settings.auth_mode, "database": "postgres" if not settings.is_sqlite else "sqlite", "biometric": settings.biometric_adapter}


class LoginIn(BaseModel):
    email: str
    password: str


class NewPasswordIn(BaseModel):
    email: str
    new_password: str
    session: str


@router.post("/auth/login")
def login(body: LoginIn, db: DB) -> dict:
    res = get_identity().authenticate(db, body.email, body.password)
    if "token" in res:
        u = db.scalar(select(m.AppUser).where(m.AppUser.email == body.email.lower().strip()))
        if u:
            u.last_login_at = datetime.now(timezone.utc)
            db.commit()
    return res


@router.post("/auth/new-password")
def new_password(body: NewPasswordIn, db: DB) -> dict:
    return get_identity().complete_new_password(db, body.email, body.new_password, body.session)


@router.get("/auth/me")
def me(user: User, db: DB) -> dict:
    d = user_dict(user)
    d["permissions"] = sorted(p for p in PERMISSIONS if has(user, p))
    d["role_labels"] = [ROLES.get(r, r) for r in user.roles or []]
    d["company"] = tenant_name()
    d["tenant"] = tenant_code()
    if user.employee_id:
        e = db.get(m.Employee, user.employee_id)
        d["employee"] = {"id": e.id, "code": e.code, "name": f"{e.first_name} {e.last_name}".strip(), "language": e.language} if e else None
    return d


@router.get("/dashboard")
def dashboard(user: User, db: DB) -> dict:
    today = date.today()
    emp_q = scope_employees(select(func.count(m.Employee.id)).where(m.Employee.status != "exited"), user)
    headcount = db.scalar(emp_q) or 0
    present = db.scalar(select(func.count(m.AttendanceDay.id)).where(m.AttendanceDay.work_date == today, m.AttendanceDay.status == "present")) or 0
    open_missed = db.scalar(select(func.count(m.AttendanceDay.id)).where(m.AttendanceDay.status == "missed_punch",
                                                                       m.AttendanceDay.work_date >= today.replace(day=1) - timedelta(days=31))) or 0
    expiry_days = int(policy(db, "doc_expiry_alert_days") or 30)
    docs = db.scalar(select(func.count(m.EmployeeDocument.id)).where(m.EmployeeDocument.expiry_date.is_not(None),
                                                                    m.EmployeeDocument.expiry_date <= today + timedelta(days=expiry_days))) or 0
    pending_leave = db.scalar(select(func.count(m.LeaveRequest.id)).where(m.LeaveRequest.status.in_(["pending_hod", "pending_hr"]))) or 0
    pending_reg = db.scalar(select(func.count(m.Regularisation.id)).where(m.Regularisation.status == "pending")) or 0
    pending_cr = db.scalar(select(func.count(m.ChangeRequest.id)).where(m.ChangeRequest.status == "pending")) or 0
    runs = db.scalars(select(m.PayrollRun).order_by(m.PayrollRun.created_at.desc()).limit(3)).all()
    exits = db.scalars(select(m.ExitCase).where(m.ExitCase.status != "closed").order_by(m.ExitCase.last_working_day)).all()
    by_loc = db.execute(scope_employees(select(m.Location.name, func.count(m.Employee.id)).join(m.Location, m.Location.id == m.Employee.location_id)
                                        .where(m.Employee.status != "exited").group_by(m.Location.name), user)).all()
    brief = []
    alerts = 0
    if has(user, "monitor.read"):
        alerts = db.scalar(select(func.count(m.MonitorAlert.id)).where(m.MonitorAlert.resolved_at.is_(None))) or 0
        if alerts:
            brief.append({"label": f"{alerts} system alerts open", "to": "/monitor"})
    if open_missed:
        brief.append({"label": f"{open_missed} missed punches open", "to": "/attendance"})
    if pending_leave + pending_reg + pending_cr:
        brief.append({"label": f"{pending_leave + pending_reg + pending_cr} approvals waiting", "to": "/approvals"})
    if docs:
        brief.append({"label": f"{docs} documents expiring", "to": "/employees?expiring=1"})
    for x in exits[:3]:
        brief.append({"label": f"F&F due {x.fnf_due_on or x.last_working_day}", "to": f"/exits/{x.id}"})
    brief.append({"label": f"Payroll day {policy(db, 'payroll_day')}", "to": "/payroll"})
    ents = {e.id: e.code for e in db.scalars(select(m.Entity))}
    names = {e.id: f"{e.code} {e.first_name} {e.last_name}".strip()
             for e in db.scalars(select(m.Employee).where(m.Employee.id.in_([x.employee_id for x in exits] or [-1])))}
    return {
        "headcount": headcount, "present_today": present, "open_missed_punches": open_missed, "documents_expiring": docs,
        "pending_approvals": pending_leave + pending_reg + pending_cr,
        "payroll_runs": [{"id": r.id, "period": r.period, "entity_id": r.entity_id, "entity": ents.get(r.entity_id), "status": r.status} for r in runs],
        "exits": [{"id": x.id, "employee_id": x.employee_id, "employee": names.get(x.employee_id), "last_working_day": x.last_working_day.isoformat(), "status": x.status} for x in exits],
        "headcount_by_location": [{"location": n, "count": c} for n, c in by_loc],
        "missed_punch_rule_set": policy(db, "missed_punch_rule") is not None,
        "brief": brief,
        "monitor_alerts": alerts,
    }
