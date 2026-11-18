"""Monitoring of the 5 core services and alert rules (SCRUM-130). Core only: no client package needed."""
import os
import tempfile

import pytest

_db = os.path.join(tempfile.mkdtemp(), "monitor.db")
os.environ.update({"DATABASE_URL": f"sqlite:///{_db}", "AUTH_MODE": "local", "ENVIRONMENT": "test", "MONITOR_INTERVAL_SECONDS": "0",
                   "MONITOR_WEB_URL": "", "BIOMETRIC_ADAPTER": "excel", "STORAGE_DIR": tempfile.mkdtemp()})

from fastapi.testclient import TestClient  # noqa: E402

from app import models as m  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services import monitoring  # noqa: E402
from app.services.security import hash_password  # noqa: E402

PW = "Monitor@123"


@pytest.fixture(scope="module")
def client():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        for email, roles in (("ops@example.test", ["master_admin"]), ("staff@example.test", ["employee"])):
            db.add(m.AppUser(email=email, display_name=email, roles=roles, password_hash=hash_password(PW), must_change_password=False))
        db.commit()
    with TestClient(app) as c:
        yield c


def auth(c, email):
    r = c.post("/api/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_status_lists_five_services(client):
    h = auth(client, "ops@example.test")
    r = client.get("/api/monitor/status?refresh=true", headers=h)
    assert r.status_code == 200, r.text
    st = {s["service"]: s for s in r.json()["services"]}
    assert set(st) == {"web", "api", "database", "signin", "biometric"}
    assert st["database"]["status"] == "up"
    assert st["signin"]["status"] == "up"
    assert st["web"]["status"] == "unknown"  # MONITOR_WEB_URL not set
    assert st["biometric"]["status"] == "degraded"  # no punches yet


def test_only_master_admin(client):
    assert client.get("/api/monitor/status", headers=auth(client, "staff@example.test")).status_code == 403


def test_warning_after_three_bad_checks_then_ack(client):
    h = auth(client, "ops@example.test")
    with SessionLocal() as db:
        for _ in range(3):
            monitoring.run_checks(db)
    open_ = client.get("/api/monitor/alerts?state=open", headers=h).json()
    bio = [a for a in open_ if a["service"] == "biometric"]
    assert len(bio) == 1 and bio[0]["severity"] == "warning"
    assert client.post(f"/api/monitor/alerts/{bio[0]['id']}/ack", headers=h).json()["acknowledged_by"] == "ops@example.test"
    assert client.get("/api/dashboard", headers=h).json()["monitor_alerts"] >= 1


def test_critical_when_down_twice_and_resolved_when_up(client, monkeypatch):
    h = auth(client, "ops@example.test")
    monkeypatch.setitem(monitoring.CHECKS, "database", lambda db: monitoring._result("down", None, "Not reachable: test"))
    with SessionLocal() as db:
        monitoring.run_checks(db)
        monitoring.run_checks(db)
    crit = [a for a in client.get("/api/monitor/alerts?state=open", headers=h).json() if a["service"] == "database"]
    assert len(crit) == 1 and crit[0]["severity"] == "critical"
    monkeypatch.undo()
    with SessionLocal() as db:
        monitoring.run_checks(db)
    assert not [a for a in client.get("/api/monitor/alerts?state=open", headers=h).json() if a["service"] == "database"]


def test_api_error_rate_counts_requests():
    stats = monitoring.RequestStats()
    for _ in range(19):
        stats.add(200, 10)
    stats.add(500, 10)
    s = stats.summary()
    assert s["requests_15m"] == 20 and s["errors_15m"] == 1 and s["error_rate"] == 0.05
