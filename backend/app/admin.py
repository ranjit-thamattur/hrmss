"""Admin commands for a fresh environment without demo data (QA with real-looking setup, or production).

    python -m app.admin setup-org                       # entities, locations, shifts, leave types, sample statutory rules
    python -m app.admin create-admin EMAIL "Full Name"  # first master admin; prints a one-time temporary password

On AWS run them inside the API container:
    aws ecs execute-command --cluster <cluster> --task <task-id> --container api --interactive --command "python -m app.admin create-admin ..."
"""
from __future__ import annotations

import sys

from sqlalchemy import select

from . import models as m
from .db import SessionLocal
from .routers.users import temp_password
from .seed import seed_org
from .services.identity import get_identity
from .services.provisioning import queue

USAGE = __doc__


def setup_org() -> None:
    with SessionLocal() as db:
        if db.scalar(select(m.Entity.id)):
            print("Organisation data already present; nothing changed.")
            return
        seed_org(db)
        db.commit()
        print("Organisation masters created. Review them in Company setup before go-live.")


def create_admin(email: str, name: str) -> None:
    email = email.lower().strip()
    with SessionLocal() as db:
        get_identity().bootstrap(db)
        if db.scalar(select(m.AppUser.id).where(m.AppUser.email == email)):
            sys.exit(f"{email} already exists")
        u = m.AppUser(email=email, display_name=name, roles=["master_admin"])
        db.add(u)
        db.flush()
        pw = temp_password()
        task = queue(db, target="identity", action="create", user_id=u.id, temp_password=pw, actor="admin-cli")
        db.commit()
        if task.status != "done":
            sys.exit(f"User saved but sign-in account failed: {task.last_error}. Retry it from Users & access → Provisioning.")
        print(f"Master admin {email} created. Temporary password (change at first sign-in): {pw}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["setup-org"]:
        setup_org()
    elif args[:1] == ["create-admin"] and len(args) == 3:
        create_admin(args[1], args[2])
    else:
        print(USAGE)
        sys.exit(1)
