"""Roles, permissions, data scope and field masking. Enforced here on the back end, not only in screens."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import Select, or_, select

from .. import models as m

ROLES = {
    "master_admin": "Master admin",
    "hr": "HR",
    "payroll_preparer": "Payroll preparer",
    "finance_approver": "Finance approver",
    "hod": "Head of department",
    "employee": "Employee",
}

# permission -> roles that have it
PERMISSIONS: dict[str, set[str]] = {
    "org.manage": {"master_admin", "hr"},
    "employees.read": {"master_admin", "hr", "payroll_preparer", "finance_approver", "hod"},
    "employees.write": {"master_admin", "hr"},
    "employees.import": {"master_admin", "hr"},
    "users.manage": {"master_admin"},
    "attendance.read": {"master_admin", "hr", "payroll_preparer", "hod"},
    "attendance.manage": {"master_admin", "hr", "payroll_preparer"},
    "attendance.approve": {"master_admin", "hr", "hod"},
    "leave.approve": {"master_admin", "hr", "hod"},
    "payroll.read": {"master_admin", "hr", "payroll_preparer", "finance_approver"},
    "payroll.prepare": {"master_admin", "payroll_preparer", "hr"},
    "payroll.approve_hr": {"master_admin", "hr"},
    "payroll.approve_finance": {"master_admin", "finance_approver"},
    "statutory.manage": {"master_admin", "hr", "payroll_preparer", "finance_approver"},
    "exits.manage": {"master_admin", "hr"},
    "performance.manage": {"master_admin", "hr"},
    "performance.review": {"master_admin", "hr", "hod"},
    "increments.gm": {"master_admin"},
    "reports.read": {"master_admin", "hr", "payroll_preparer", "finance_approver", "hod"},
    "comms.send": {"master_admin", "hr"},
    "audit.read": {"master_admin", "hr"},
}

SENSITIVE_ROLES = {"master_admin", "hr", "payroll_preparer", "finance_approver"}  # salary, PAN, Aadhaar, bank


def has(user: m.AppUser, perm: str) -> bool:
    return bool(set(user.roles or []) & PERMISSIONS.get(perm, set()))


def require(user: m.AppUser, perm: str) -> None:
    if not has(user, perm):
        raise HTTPException(status_code=403, detail=f"Your role cannot do this ({perm}).")


def sees_sensitive(user: m.AppUser, employee_id: int | None = None) -> bool:
    if set(user.roles or []) & SENSITIVE_ROLES:
        return True
    return employee_id is not None and user.employee_id == employee_id


def scope_employees(stmt: Select, user: m.AppUser) -> Select:
    """Restrict an Employee query to what this user may see."""
    roles = set(user.roles or [])
    if roles & {"master_admin", "hr", "payroll_preparer", "finance_approver"}:
        if user.location_scope:
            stmt = stmt.where(m.Employee.location_id.in_(user.location_scope))
        if user.entity_scope:
            stmt = stmt.where(m.Employee.location_id.in_(select(m.Location.id).where(m.Location.entity_id.in_(user.entity_scope))))
        return stmt
    if "hod" in roles and user.employee_id:
        team = select(m.Employee.id).where(m.Employee.manager_id == user.employee_id)
        return stmt.where(or_(m.Employee.id == user.employee_id, m.Employee.id.in_(team)))
    return stmt.where(m.Employee.id == (user.employee_id or -1))


def can_see_employee(db, user: m.AppUser, employee_id: int) -> bool:
    stmt = scope_employees(select(m.Employee.id).where(m.Employee.id == employee_id), user)
    return db.execute(stmt).first() is not None


def is_manager_of(db, user: m.AppUser, employee_id: int) -> bool:
    if not user.employee_id:
        return False
    e = db.get(m.Employee, employee_id)
    return bool(e and e.manager_id == user.employee_id)
