"""Test set-up: SQLite file, local sign-in, ENVIRONMENT=test, test client A from tests/clients/client_a.yaml.
Pure tests (dating, schemas, catalogue, rules) need no database; the API tests use the fixtures below.
"""
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
_tmp = tempfile.mkdtemp(prefix="hrms-test-")
os.environ.update({
    "ENVIRONMENT": "test", "AUTH_MODE": "local", "CLIENT_CONFIG": str(HERE / "clients" / "client_a.yaml"),
    "DATABASE_URL": f"sqlite:///{_tmp}/test.db", "STORAGE_DIR": f"{_tmp}/files", "SEED_DEMO": "false",
    "JWT_SECRET": "test-secret", "COGNITO_BOOTSTRAP": "false",
})

import pytest  # noqa: E402

PW = "Test@12345"


@pytest.fixture(scope="session")
def app_client():
    from fastapi.testclient import TestClient

    from app import models  # noqa: F401
    from app.db import Base, engine
    from app.main import app
    from app.startup import prepare

    Base.metadata.create_all(engine)
    prepare()
    with TestClient(app) as c:
        yield c


def make_user(email: str, roles: list[str], client_code: str = "TA", person_rid: int | None = None, **scope) -> None:
    from sqlalchemy import select

    from app import models as m
    from app.core.identity import LocalIdentity
    from app.db import SessionLocal

    with SessionLocal() as db:
        client = db.scalar(select(m.Client).where(m.Client.code == client_code))
        u = db.scalar(select(m.AppUser).where(m.AppUser.email == email))
        if u is None:
            u = m.AppUser(client_id=client.id, email=email, display_name=email.split("@")[0], roles=roles, person_rid=person_rid, created_by="test",
                          **{k: v for k, v in scope.items()})
            db.add(u)
        LocalIdentity().set_permanent_password(db, u, PW)
        db.commit()


def token(c, email: str) -> dict:
    r = c.post("/api/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def admin(app_client):
    make_user("admin@a.test", ["master_admin"])
    return token(app_client, "admin@a.test")


@pytest.fixture(scope="session")
def admin2(app_client):
    make_user("admin2@a.test", ["master_admin"])
    return token(app_client, "admin2@a.test")
