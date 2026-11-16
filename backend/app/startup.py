"""Container start-up: wait for the database, apply migrations, seed demo data (if SEED_DEMO=true).

With several API containers starting together (AWS), a Postgres advisory lock makes sure only one of them
migrates and seeds at a time.
"""
from __future__ import annotations

import sys
import time

from sqlalchemy import create_engine, text

from .config import get_settings

LOCK_ID = 726_2026


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
            if settings.seed_demo:
                from . import seed

                seed.run()
        finally:
            if pg:
                lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_ID})


if __name__ == "__main__":
    main()
