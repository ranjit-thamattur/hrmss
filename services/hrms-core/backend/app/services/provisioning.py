"""Provisioning to the identity provider (Cognito) and the biometric device.

- Every employee is enrolled on the biometric device (attendance), whether or not they use the software.
- Only people given software access get a user, provisioned to Cognito with their role groups.
Each target has its own task with status, attempts and last error, and can be retried.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from .audit import record
from .identity import get_identity
from .integrations import BiometricError, get_biometric

log = logging.getLogger("hrms.provisioning")


def run_task(db: Session, task: m.ProvisioningTask, *, temp_password: str | None = None) -> m.ProvisioningTask:
    task.attempts += 1
    try:
        if task.target == "identity":
            user = db.get(m.AppUser, task.user_id)
            idp = get_identity()
            if task.action == "create":
                user.identity_sub = idp.create_user(db, user, temp_password or "")
            elif task.action == "groups":
                idp.set_groups(db, user)
            elif task.action in ("disable", "enable"):
                idp.set_enabled(db, user, task.action == "enable")
            task.status = "done"
        elif task.target == "biometric":
            emp = db.get(m.Employee, task.employee_id)
            adapter = get_biometric()
            if task.action == "create":
                emp.biometric_id = adapter.provision(emp)
                task.status = "manual" if adapter.manual else "done"
            elif task.action == "disable":
                adapter.deprovision(emp)
                task.status = "manual" if adapter.manual else "done"
        task.last_error = None
    except (BiometricError, Exception) as e:  # noqa: BLE001 - recorded on the task, retried from the screen
        log.warning("provisioning %s/%s failed: %s", task.target, task.action, e)
        task.status = "failed"
        task.last_error = str(e)[:1000]
    db.flush()
    return task


def queue(db: Session, *, target: str, action: str, user_id: int | None = None, employee_id: int | None = None,
          temp_password: str | None = None, actor: str = "system") -> m.ProvisioningTask:
    t = m.ProvisioningTask(target=target, action=action, user_id=user_id, employee_id=employee_id)
    db.add(t)
    db.flush()
    run_task(db, t, temp_password=temp_password)
    record(db, actor, f"provision_{target}_{action}", "provisioning", t.id, after={"status": t.status, "error": t.last_error},
           employee_id=employee_id)
    return t


def tasks_for(db: Session, *, user_id: int | None = None, employee_id: int | None = None) -> list[m.ProvisioningTask]:
    stmt = select(m.ProvisioningTask).order_by(m.ProvisioningTask.id.desc())
    if user_id:
        stmt = stmt.where(m.ProvisioningTask.user_id == user_id)
    if employee_id:
        stmt = stmt.where(m.ProvisioningTask.employee_id == employee_id)
    return list(db.scalars(stmt))
