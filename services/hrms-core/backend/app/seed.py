"""Demo data for laptops: synthetic only, never real client data (decision 0006).

The client package (TENANT_PACKAGE) supplies the organisation and synthetic employees; this module adds
the parts common to every client: synthetic punches and the demo sign-in users. Refuses to run outside
ENVIRONMENT=local/dev/test. Safe to run more than once: does nothing if entities already exist.

    python -m app.seed            # seed if empty
    python -m app.seed --punches  # also (re)generate punches for last month and this month
"""
from __future__ import annotations

import random
import sys
from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from . import models as m
from .config import get_settings
from .db import SessionLocal
from .services.identity import CognitoIdentity, get_identity
from .services.provisioning import queue
from .tenant import get_tenant

settings = get_settings()
rnd = random.Random(20261120)


def seed_punches(db, months: tuple[tuple[int, int], ...]) -> int:
    """Synthetic punches incl. night shifts across midnight, late arrivals, some missed punches and OT."""
    shifts = {s.code: s for s in db.scalars(select(m.Shift))}
    locs = {x.id: x for x in db.scalars(select(m.Location))}
    n = 0
    for e in db.scalars(select(m.Employee).where(m.Employee.status != "exited")):
        sh = shifts.get(e.shift_code) or next(iter(shifts.values()))
        if sh.is_off:
            continue
        for y, mo in months:
            d = date(y, mo, 1)
            while d.month == mo and d <= date.today():
                if d < e.doj or d.weekday() == locs[e.location_id].weekly_off or rnd.random() < 0.04:
                    d += timedelta(days=1)
                    continue
                start = datetime.combine(d, time.fromisoformat(sh.start_time)) + timedelta(minutes=rnd.choice([-12, -8, -5, -3, 0, 2, 6, 25]))
                end_t = datetime.combine(d, time.fromisoformat(sh.end_time))
                if end_t <= datetime.combine(d, time.fromisoformat(sh.start_time)):
                    end_t += timedelta(days=1)
                end = end_t + timedelta(minutes=rnd.choice([0, 3, 7, 12, 40, 95]))
                pts = [start] if rnd.random() < 0.02 else [start, end]  # ~2% missed punches
                for p in pts:
                    if not db.scalar(select(m.Punch.id).where(m.Punch.employee_id == e.id, m.Punch.punched_at == p)):
                        db.add(m.Punch(employee_id=e.id, punched_at=p, device_id=f"{locs[e.location_id].code}-1", source="excel"))
                        n += 1
                d += timedelta(days=1)
    db.flush()
    return n


def seed_users(db, special: dict[str, int]) -> list[tuple[str, str]]:
    idp = get_identity()
    idp.bootstrap(db)
    out = []
    for email, name, roles, link in get_tenant().DEMO_USERS:
        if db.scalar(select(m.AppUser.id).where(m.AppUser.email == email)):
            continue
        u = m.AppUser(email=email, display_name=name, roles=roles, employee_id=special.get(link) if link else None)
        db.add(u)
        db.flush()
        task = queue(db, target="identity", action="create", user_id=u.id, temp_password=settings.demo_password, actor="seed")
        # demo users: accept the demo password as permanent so the walkthrough needs no password change
        u.must_change_password = False
        if task.status == "done" and isinstance(idp, CognitoIdentity):
            pool, _ = idp.ids(db)
            try:
                idp.client.admin_set_user_password(UserPoolId=pool, Username=email, Password=settings.demo_password, Permanent=True)
            except Exception:  # noqa: BLE001 - cognito-local may not support it; then first sign-in asks for a new password
                u.must_change_password = True
        out.append((email, task.status))
    return out


def run(with_punches: bool = False) -> None:
    if not settings.demo_data_allowed:
        raise SystemExit(f"Demo data is only allowed on laptops (ENVIRONMENT=local/dev/test), not '{settings.environment}'.")
    tenant = get_tenant()
    today = date.today()
    prev = today.replace(day=1) - timedelta(days=1)
    months = ((prev.year, prev.month), (today.year, today.month))
    with SessionLocal() as db:
        if db.scalar(select(m.Entity.id)):
            print("Seed: data already present.")
            if with_punches:
                print("Punches added:", seed_punches(db, months))
                db.commit()
            return
        tenant.seed_org(db)
        special = tenant.seed_employees(db, settings.demo_employee_count)
        punches = seed_punches(db, months)
        users = seed_users(db, special)
        db.commit()
        print(f"Seed ({tenant.CODE}): {settings.demo_employee_count} synthetic employees, {punches} punches, users: {users}")
        if tenant.DEMO_USERS:
            print(f"Demo sign-in: {tenant.DEMO_USERS[0][0]} / {settings.demo_password}")


if __name__ == "__main__":
    run(with_punches="--punches" in sys.argv)
