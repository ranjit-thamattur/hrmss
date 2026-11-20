"""Admin commands (run inside the API container, or natively with CLIENT_CONFIG set).

    python -m app.admin create-admin EMAIL "Full Name"   first master admin; prints a one-time temporary password
    python -m app.admin load-demo                        synthetic demo data from the client package (laptops only)

In QA/production run create-admin once (how to reach the container is up to the infrastructure owner,
PEAKHRMS-132); then set up the company through the APIs or the Excel imports.
"""
from __future__ import annotations

import sys

from sqlalchemy import select

from . import models as m
from .config import get_settings
from .core.context import system_ctx
from .core.identity import get_identity
from .db import SessionLocal

USAGE = __doc__


def _client(db) -> m.Client:  # noqa: ANN001
    code = str(get_settings().client.get("client", {}).get("code", "")).upper()
    c = db.scalar(select(m.Client).where(m.Client.code == code))
    if c is None:
        sys.exit(f"Client {code or '?'} is not in this database yet. Start the API once (it runs app.startup) or run python -m app.startup.")
    return c


def create_admin(email: str, name: str) -> None:
    from .services.users import temp_password

    email = email.lower().strip()
    with SessionLocal() as db:
        client = _client(db)
        get_identity().bootstrap(db)
        if db.scalar(select(m.AppUser.id).where(m.AppUser.email == email)):
            sys.exit(f"{email} already exists")
        u = m.AppUser(client_id=client.id, email=email, display_name=name, roles=["master_admin"], created_by="admin-cli")
        db.add(u)
        db.flush()
        pw = temp_password()
        u.identity_sub = get_identity().create_user(db, u, pw)
        from .core.audit import record

        record(system_ctx(db, client.id, "admin-cli"), "create", "users", u.id, None, {"email": email, "roles": ["master_admin"]})
        db.commit()
        print(f"Master admin {email} created. Temporary password (change at first sign-in): {pw}")


def load_demo() -> None:
    from .client_package import get_client_package

    if not get_settings().demo_data_allowed:
        sys.exit("load-demo is synthetic data for laptops only (ENVIRONMENT local/dev/test).")
    pkg = get_client_package()
    if not pkg or not hasattr(pkg, "load_demo"):
        sys.exit("This client package has no demo data.")
    with SessionLocal() as db:
        pkg.load_demo(db, _client(db))
        db.commit()
    print("Demo data loaded (or already present).")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["create-admin"] and len(args) == 3:
        create_admin(args[1], args[2])
    elif args[:1] == ["load-demo"]:
        load_demo()
    else:
        print(USAGE)
        sys.exit(1)
