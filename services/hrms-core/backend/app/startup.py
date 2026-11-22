"""Container start-up: wait for the database, apply migrations, create/update the client from its YAML,
check the database belongs to this client, set up Cognito (cognito-local) and load synthetic demo data
(SEED_DEMO=true, laptops only).

With several API containers starting together (AWS), a Postgres advisory lock makes sure only one of them
migrates and seeds at a time.
"""
from __future__ import annotations

import logging
import sys
import time

from sqlalchemy import create_engine, text

from .config import get_settings

LOCK_ID = 726_2026
log = logging.getLogger("hrms.startup")


def wait_for_db(url: str) -> None:
    eng = create_engine(url)
    for _ in range(60):
        try:
            with eng.connect() as c:
                c.execute(text("SELECT 1"))
            return
        except Exception as e:  # noqa: BLE001 - keep waiting
            print("waiting for database...", e.__class__.__name__, flush=True)
            time.sleep(2)
    sys.exit("database not reachable")


def prepare() -> None:
    """Everything after the migrations; also used by tests and by `python -m app.admin`."""
    from . import models as m
    from .client_package import get_client_package
    from .core.bootstrap import bootstrap_client
    from .core.identity import get_identity
    from .db import SessionLocal

    s = get_settings()
    conf = s.client
    if not conf:
        sys.exit("CLIENT_CONFIG is not set: give the path of the client YAML file (e.g. hotel_vivek_backend/client.yaml).")
    with SessionLocal() as db:
        code = str(conf["client"]["code"]).upper()
        stamp = db.get(m.AppSetting, "client_code")
        if stamp is not None and stamp.value != code:
            sys.exit(f"This database belongs to client {stamp.value}, but this deployment is client {code}. Use that client's own database.")
        client = bootstrap_client(db, conf)
        if stamp is None:
            db.add(m.AppSetting(key="client_code", value=code))
        db.commit()
        print(f"Client {client.code} ({client.name}) ready in database {s.db_name}.", flush=True)

        if s.auth_mode == "cognito" and s.cognito_bootstrap:
            try:
                get_identity().bootstrap(db)
            except Exception as e:  # noqa: BLE001 - the API still starts; sign-in shows the problem
                log.error("Cognito bootstrap failed: %s", e)

        if s.seed_demo and s.demo_data_allowed:
            pkg = get_client_package()
            loader = getattr(pkg, "load_demo", None) if pkg else None
            if loader:
                try:
                    loader(db, client)
                    db.commit()
                except Exception as e:  # noqa: BLE001 - demo data must never stop the API
                    db.rollback()
                    log.exception("Demo data not loaded: %s", e)
        elif s.seed_demo:
            print(f"SEED_DEMO ignored: ENVIRONMENT={s.environment} holds real client data only.", flush=True)


def main() -> None:
    s = get_settings()
    wait_for_db(s.database_url)
    from alembic import command
    from alembic.config import Config

    eng = create_engine(s.database_url)
    with eng.connect() as lock_conn:
        pg = eng.dialect.name == "postgresql"
        if pg:
            lock_conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": LOCK_ID})
        try:
            command.upgrade(Config("alembic.ini"), "head")
            prepare()
        finally:
            if pg:
                lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_ID})


if __name__ == "__main__":
    main()
