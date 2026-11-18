"""Hotel Vivek (HV) end-to-end API tests: hrms-core + the hotel_vivek client package, SQLite, local sign-in. They run in CI on every push (decision 0002).

Flow: sign-in → roles and masking → onboarding + user conversion → import with planted errors →
attendance → payroll (rule gate, decisions, separation of duties, lock, files) → leave → exit → audit.
"""
import io
import os
import tempfile
from datetime import date, timedelta

import pytest

_db = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ.update({"TENANT": "HV", "TENANT_PACKAGE": "hotel_vivek", "MONITOR_INTERVAL_SECONDS": "0", "DATABASE_URL": f"sqlite:///{_db}", "AUTH_MODE": "local", "ENVIRONMENT": "test", "SEED_DEMO": "false",
                   "DEMO_EMPLOYEE_COUNT": "30", "DEMO_PASSWORD": "Peak@12345", "BIOMETRIC_ADAPTER": "excel", "STORAGE_DIR": tempfile.mkdtemp()})

from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import Workbook  # noqa: E402

from app import seed  # noqa: E402
from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

PW = "Peak@12345"


@pytest.fixture(scope="module")
def client():
    Base.metadata.create_all(engine)
    seed.run()
    with TestClient(app) as c:
        yield c


def login(c, email):
    r = c.post("/api/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def prev_period():
    d = date.today().replace(day=1) - timedelta(days=1)
    return d.strftime("%Y-%m"), d.year, d.month


def test_health_and_login(client):
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.post("/api/auth/login", json={"email": "admin@hotelvivek.local", "password": "wrong"}).status_code == 401
    me = client.get("/api/auth/me", headers=login(client, "admin@hotelvivek.local")).json()
    assert "users.manage" in me["permissions"]
    assert client.get("/api/employees").status_code == 401


def test_scope_and_masking(client):
    emp = login(client, "employee@hotelvivek.local")
    assert client.get("/api/employees", headers=emp).status_code == 403
    me = client.get("/api/me/profile", headers=emp).json()
    assert me["code"] == "HV0001" and me["can_see_sensitive"] and len(me["pan"]) == 10
    other = client.get("/api/employees/2", headers=emp)
    assert other.status_code == 404
    hod = login(client, "hod@hotelvivek.local")
    team = client.get("/api/employees", headers=hod).json()
    assert team["total"] >= 1
    sel = client.get(f"/api/employees/{me['id']}", headers=hod).json()
    assert sel["pan"].startswith("XXXXXXXX") and sel["salary"] is None
    hr = login(client, "hr@hotelvivek.local")
    assert client.get(f"/api/employees/{me['id']}", headers=hr).json()["salary"] is not None


def test_onboard_and_convert_to_user(client):
    hr, admin = login(client, "hr@hotelvivek.local"), login(client, "admin@hotelvivek.local")
    setup = client.get("/api/org/all", headers=hr).json()
    body = {"code": "HV9001", "first_name": "Kavya", "last_name": "R", "doj": date.today().isoformat(), "location_id": setup["locations"][0]["id"],
            "department_id": setup["departments"][0]["id"], "pan": "ABCDE9999Z", "bank_account": "12345678901", "ifsc": "SBIN0001234", "monthly_gross": "18500"}
    r = client.post("/api/employees", json=body, headers=hr)
    assert r.status_code == 200, r.text
    eid = r.json()["id"]
    assert client.post("/api/employees", json=body, headers=hr).status_code == 409
    assert client.post("/api/users", json={"email": "kavya@hotelvivek.local", "employee_id": eid, "roles": ["employee"]}, headers=hr).status_code == 403
    u = client.post("/api/users", json={"email": "kavya@hotelvivek.local", "employee_id": eid, "roles": ["employee"]}, headers=admin).json()
    assert u["identity_status"] == "done" and u["temporary_password"]
    first = client.post("/api/auth/login", json={"email": "kavya@hotelvivek.local", "password": u["temporary_password"]}).json()
    assert first["challenge"] == "NEW_PASSWORD_REQUIRED"
    done = client.post("/api/auth/new-password", json={"email": "kavya@hotelvivek.local", "new_password": "Kavya@2026", "session": first["session"]}).json()
    assert "token" in done
    tasks = client.get("/api/users/provisioning", headers=admin).json()
    bio = [t for t in tasks if t["employee_id"] == eid and t["target"] == "biometric"]
    assert bio and bio[0]["status"] == "manual"
    assert client.post(f"/api/users/provisioning/{bio[0]['id']}/confirm", headers=hr).json()["status"] == "done"


def _xlsx(rows):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_import_with_planted_errors(client):
    hr = login(client, "hr@hotelvivek.local")
    content = _xlsx([["Emp Code", "Name", "DOJ", "Entity", "Location", "Department", "PAN", "Bank A/c", "IFSC"],
                     ["HV8001", "Good", "01-11-2026", "VHPL", "OOT", "Kitchen", "ABCDE8001F", "111", "SBIN0001234"],
                     ["HV8002", "NoBank", "01-11-2026", "VHPL", "OOT", "Kitchen", "ABCDE8002F", "", "SBIN0001234"],
                     ["HV8001", "Dup", "01-11-2026", "VHPL", "OOT", "Kitchen", "ABCDE8003F", "333", "SBIN0001234"],
                     ["HV8004", "BadPan", "01-11-2026", "VHPL", "OOT", "Kitchen", "ABC123", "444", "SBIN0001234"],
                     ["HV8005", "NoEntity", "01-11-2026", "XXX", "OOT", "Kitchen", "ABCDE8005F", "555", "SBIN0001234"]])
    files = {"file": ("master.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    check = client.post("/api/imports/employees", files=files, data={"dry_run": "true"}, headers=hr).json()
    assert check["total"] == 5 and check["imported"] == 1 and check["rejected"] == 4 and check["counts_reconcile"]
    real = client.post("/api/imports/employees", files=files, data={"dry_run": "false"}, headers=hr).json()
    assert real["imported"] == 1
    assert client.get(f"/api/imports/{real['batch_id']}/rejected.csv", headers=hr).text.count("\n") == 5
    assert client.get("/api/imports/templates/employees.xlsx", headers=hr).status_code == 200


def test_attendance_and_payroll_flow(client):
    period, y, mo = prev_period()
    prep, hr, fin = login(client, "payroll@hotelvivek.local"), login(client, "hr@hotelvivek.local"), login(client, "finance@hotelvivek.local")
    res = client.post("/api/attendance/process", json={"year": y, "month": mo}, headers=prep).json()
    assert res["days"] > 0
    ent = client.get("/api/org/tables/entities", headers=hr).json()[0]
    # force a negative line: huge advance for HV0002
    emps = client.get("/api/payroll/inputs", params={"period": period}, headers=prep).json()["items"]
    target = next(e for e in emps if e["code"] == "HV0002")
    client.put("/api/payroll/inputs", json={"period": period, "rows": [{"employee_id": target["id"], "code": "ADVANCE", "amount": "500000"}]}, headers=prep)
    r = client.post("/api/payroll/runs", json={"entity_id": ent["id"], "period": period}, headers=prep)
    if r.status_code == 409 and "missed-punch rule" in r.text:
        client.post("/api/org/policies", json={"key": "missed_punch_rule", "value": "lop", "effective_from": f"{period}-01"}, headers=hr)
        r = client.post("/api/payroll/runs", json={"entity_id": ent["id"], "period": period}, headers=prep)
    assert r.status_code == 200, r.text
    run = r.json()
    assert [s["step"] for s in run["steps"]][:2] == ["Lock attendance", "Apply inputs"]
    neg = next(ln for ln in run["lines"] if ln["code"] == "HV0002")
    assert any(f["code"] == "NEGATIVE_NET" for f in neg["flags"])
    assert client.post(f"/api/payroll/lines/{neg['id']}/decide", json={"decision": "accept", "note": "ok"}, headers=prep).status_code == 400
    assert client.post(f"/api/payroll/runs/{run['id']}/submit", headers=prep).status_code == 409
    for ln in run["lines"]:
        if ln["flags"]:
            dec = "hold" if any(f["severity"] == "block" for f in ln["flags"]) else "accept"
            assert client.post(f"/api/payroll/lines/{ln['id']}/decide", json={"decision": dec, "note": "checked"}, headers=prep).status_code == 200
    assert client.post(f"/api/payroll/runs/{run['id']}/submit", headers=prep).status_code == 200
    assert client.post(f"/api/payroll/runs/{run['id']}/approve-finance", headers=fin).status_code == 409  # HR first
    assert client.post(f"/api/payroll/runs/{run['id']}/approve-hr", headers=hr).status_code == 200
    assert client.post(f"/api/payroll/runs/{run['id']}/lock", headers=fin).status_code == 409  # finance not yet
    assert client.post(f"/api/payroll/runs/{run['id']}/approve-finance", headers=fin).status_code == 200
    assert client.post(f"/api/payroll/runs/{run['id']}/lock", headers=fin).json()["status"] == "locked"
    assert client.post(f"/api/payroll/runs/{run['id']}/recalculate", headers=prep).status_code == 409
    assert client.post("/api/payroll/runs", json={"entity_id": ent["id"], "period": period}, headers=prep).status_code == 409
    for f in ("bank.csv", "tally.xml", "epf-ecr.txt", "esi.csv", "register.csv"):
        assert client.get(f"/api/payroll/runs/{run['id']}/{f}", headers=fin).status_code == 200, f
    bank = client.get(f"/api/payroll/runs/{run['id']}/bank.csv", headers=fin).text
    assert "HV0002" not in bank  # held line not paid
    emp = login(client, "employee@hotelvivek.local")
    slips = client.get("/api/me/payslips", headers=emp).json()
    if slips:
        pdf = client.get(f"/api/payroll/runs/{slips[0]['run_id']}/payslips/{client.get('/api/me/profile', headers=emp).json()['id']}.pdf", headers=emp)
        assert pdf.content[:4] == b"%PDF"
    assert any(i["law"] in ("EPF", "ESI") for i in client.get("/api/statutory/calendar", headers=fin).json())


def test_preparer_cannot_approve(client):
    admin = login(client, "admin@hotelvivek.local")
    period = (date.today().replace(day=1) - timedelta(days=40)).strftime("%Y-%m")
    ents = client.get("/api/org/tables/entities", headers=admin).json()
    client.post("/api/org/policies", json={"key": "missed_punch_rule", "value": "lop", "effective_from": "2020-01-01"}, headers=admin)
    run = client.post("/api/payroll/runs", json={"entity_id": ents[1]["id"], "period": period}, headers=admin).json()
    for ln in run["lines"]:
        if ln["flags"]:
            client.post(f"/api/payroll/lines/{ln['id']}/decide", json={"decision": "hold", "note": "x"}, headers=admin)
    client.post(f"/api/payroll/runs/{run['id']}/submit", headers=admin)
    r = client.post(f"/api/payroll/runs/{run['id']}/approve-hr", headers=admin)
    assert r.status_code == 403 and "prepared" in r.text


def test_leave_flow_hod(client):
    emp, hod = login(client, "employee@hotelvivek.local"), login(client, "hod@hotelvivek.local")
    d = date.today() + timedelta(days=20)
    r = client.post("/api/leave/requests", json={"leave_code": "CL", "from_date": d.isoformat(), "to_date": d.isoformat(), "reason": "family"}, headers=emp)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending_hod"
    inbox = client.get("/api/approvals", headers=hod).json()
    assert any(i["type"] == "leave" for i in inbox["items"])
    assert client.post(f"/api/leave/requests/{r.json()['id']}/decide", params={"approve": True}, headers=hod).json()["status"] == "approved"


def test_exit_flow(client):
    hr = login(client, "hr@hotelvivek.local")
    x = client.post("/api/exits", json={"employee_id": 3, "reason": "relocating"}, headers=hr).json()
    assert x["status"] == "notice" and len(x["clearance"]) == 6
    client.post(f"/api/exits/{x['id']}/fnf", json={}, headers=hr)
    assert client.post(f"/api/exits/{x['id']}/fnf/approve", headers=hr).status_code == 409  # clearance pending
    for t in x["clearance"]:
        client.post(f"/api/exits/{x['id']}/clearance/{t['id']}", params={"done": True}, headers=hr)
    assert client.post(f"/api/exits/{x['id']}/fnf/approve", headers=hr).json()["status"] == "fnf_approved"
    assert client.get(f"/api/exits/{x['id']}/letter/relieving.pdf", headers=hr).content[:4] == b"%PDF"
    assert client.post(f"/api/exits/{x['id']}/close", headers=hr).json()["status"] == "closed"


def test_audit_and_timeline(client):
    hr = login(client, "hr@hotelvivek.local")
    log = client.get("/api/audit", headers=hr).json()
    assert any(a["action"] == "payroll_locked" for a in log)
    tl = client.get("/api/employees/1/timeline", headers=hr).json()
    assert tl["events"] and tl["employee"]["code"] == "HV0001"
    assert client.get("/api/audit", headers=login(client, "employee@hotelvivek.local")).status_code == 403


def test_reports_dashboard_circular(client):
    hr = login(client, "hr@hotelvivek.local")
    assert client.get("/api/dashboard", headers=hr).json()["headcount"] > 0
    for k in client.get("/api/reports", headers=hr).json():
        assert client.get(f"/api/reports/{k}", headers=hr).status_code == 200, k
    c = client.post("/api/circulars", json={"title": "Winter uniforms", "body": {"en": "Collect from the linen room."}}, headers=hr).json()
    assert c["recipients"] > 0
    assert client.get("/openapi.json").status_code == 200


def test_client_package_is_hotel_vivek(client):
    from openpyxl import load_workbook

    from app.startup import check_tenant

    assert client.get("/api/health").json()["tenant"] == "HV"
    h = login(client, "admin@hotelvivek.local")
    me = client.get("/api/auth/me", headers=h).json()
    assert me["company"] == "Hotel Vivek" and me["tenant"] == "HV"
    wb = load_workbook(io.BytesIO(client.get("/api/imports/templates/employees.xlsx", headers=h).content))
    assert wb.active["A2"].value == "HV0001"
    check_tenant()  # stamps the database as HV
    check_tenant()  # and accepts it again
