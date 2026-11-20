"""Hotel Vivek backend tests: the HRMS core + this client's YAML and package, with the SYNTHETIC demo data."""
import os
import sys
import tempfile
from pathlib import Path

HV = Path(__file__).resolve().parents[1]
CORE = HV.parent / "hrms-core" / "backend"
sys.path[:0] = [str(CORE), str(HV)]
_tmp = tempfile.mkdtemp(prefix="hrms-hv-test-")
os.environ.update({
    "ENVIRONMENT": "test", "AUTH_MODE": "local", "CLIENT_CONFIG": str(HV / "client.yaml"), "CLIENT_PACKAGE_PATH": str(HV),
    "DATABASE_URL": f"sqlite:///{_tmp}/hv.db", "STORAGE_DIR": f"{_tmp}/files", "SEED_DEMO": "true", "DEMO_PASSWORD": "Peak@12345",
    "JWT_SECRET": "test-secret", "COGNITO_BOOTSTRAP": "false",
})

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def c():
    from fastapi.testclient import TestClient

    from app import models  # noqa: F401
    from app.db import Base, engine
    from app.main import app
    from app.startup import prepare

    Base.metadata.create_all(engine)
    prepare()
    with TestClient(app) as client:
        yield client


def login(c, who: str) -> dict:
    r = c.post("/api/auth/login", json={"email": f"{who}@hotelvivek.local", "password": "Peak@12345"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}
