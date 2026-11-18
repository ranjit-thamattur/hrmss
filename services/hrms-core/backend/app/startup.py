"""Container start-up: wait for the database, apply migrations, check the client stamp, seed demo data
(SEED_DEMO=true, laptops only).

With several API containers starting together (AWS), a Postgres advisory lock makes sure only one of them
migrates and seeds at a time.
"""
from __future__ import annotations

import sys
import time

from sqlalchemy import create_engine, text

from .config import get_settings

LOCK_ID = 726_2026


def check_tenant() -> None:
    """One database per client: stamp the database with the client code, refuse another client's database."""
    from . import models as m
    from .db import SessionLocal
    from .tenant import tenant_code

    code = tenant_code()
    with SessionLocal() as db:
        row = db.get(m.AppSetting, "tenant_code")
        if row is None:
            db.add(m.AppSetting(key="tenant_code", value=code))
            db.commit()
            print(f"Database {settings.db_name} assigned to client {code}.", flush=True)
        elif row.value != code:
            sys.exit(f"This database belongs to client {row.value}, but this deployment is client {code}. Use that client's own database.")


def main() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    for _ in range(60):
        try:
            with engine.connect() as c:
                c.execute(text("SELECT 1"))
            break
        except Exception as e:  # noqa: BLE001
            print("waiting for database...", e.__class__.__name__, flush=True)
            time.sleep(2)
    else:
        sys.exit("database not reachable")

    from alembic import command
    from alembic.config import Config

    with engine.connect() as lock_conn:
        pg = engine.dialect.name == "postgresql"
        if pg:
            lock_conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": LOCK_ID})
        try:
            command.upgrade(Config("alembic.ini"), "head")
            check_tenant()
            if settings.seed_demo and settings.demo_data_allowed:
                from . import seed

                seed.run()
            elif settings.seed_demo:
                print(f"SEED_DEMO ignored: ENVIRONMENT={settings.environment} holds real client data only.", flush=True)
        finally:
            if pg:
                lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_ID})


if __name__ == "__main__":
    main()
