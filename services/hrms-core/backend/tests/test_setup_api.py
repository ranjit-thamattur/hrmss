"""Acceptance tests for the eleven rules of the Company Setup design (18-Nov), through the REST API.
Synthetic data only. Runs in CI (and on a laptop: pytest -q)."""
import io
from datetime import date, timedelta

import pytest

from .conftest import make_user, token

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)


@pytest.fixture(scope="module")
def base(app_client, admin):
    c = app_client
    states = c.get("/api/setup/states", params={"code": "TN"}, headers=admin).json()["items"]
    tn = states[0]["rid"]
    le = c.post("/api/setup/legal-entities", headers=admin, json={"code": "E1", "registered_name": "Entity One Pvt Ltd", "pan": "aaace1111a",
                                                                   "state_rid": tn, "valid_from": "2024-04-01"})
    assert le.status_code == 201, le.text
    l1 = c.post("/api/setup/locations", headers=admin, json={"code": "L1", "name": "Location One", "state_rid": tn, "valid_from": "2024-04-01"}).json()
    l2 = c.post("/api/setup/locations", headers=admin, json={"code": "L2", "name": "Location Two", "state_rid": tn, "valid_from": "2024-04-01"}).json()
    return {"tn": tn, "e1": le.json()["rid"], "l1": l1["rid"], "l2": l2["rid"]}


def test_health_and_sign_in(app_client, admin):
    assert app_client.get("/api/health").json()["client"] == "TA"
    me = app_client.get("/api/auth/me", headers=admin).json()
    assert me["client"]["code"] == "TA" and "master_admin" in me["roles"]
    assert app_client.get("/api/setup/locations").status_code == 401


def test_rule1_client_comes_from_the_login(app_client, admin, base):
    r = app_client.post("/api/setup/designations", headers=admin, json={"code": "D1", "title": "Designer", "client_id": 999})
    assert r.status_code == 201
    from app import models as m
    from app.db import SessionLocal

    with SessionLocal() as db:
        row = db.get(m.Designation, r.json()["version_id"])
        assert db.get(m.Client, row.client_id).code == "TA"


def test_rule2_effective_dating_keeps_history(app_client, admin, base):
    c, rid = app_client, base["l1"]
    later = (TODAY + timedelta(days=30)).isoformat()
    r = c.put(f"/api/setup/locations/{rid}", headers=admin, json={"name": "Location One (renamed)", "effective_from": later, "change_reason": "Rename"})
    assert r.status_code == 200, r.text
    assert c.get(f"/api/setup/locations/{rid}", headers=admin).json()["name"] == "Location One"
    assert c.get(f"/api/setup/locations/{rid}", headers=admin, params={"as_of": later}).json()["name"] == "Location One (renamed)"
    hist = c.get(f"/api/setup/locations/{rid}/history", headers=admin).json()
    assert [h["version"] for h in hist] == [1, 2] and hist[0]["valid_to"] == (TODAY + timedelta(days=29)).isoformat()


def test_rule3_no_overlaps_and_backdating_needs_another_person(app_client, admin, admin2, base):
    c = app_client
    link = {"legal_entity_rid": base["e1"], "location_rid": base["l2"], "valid_from": "2024-04-01"}
    assert c.post("/api/setup/entity-locations", headers=admin, json=link).status_code == 201
    assert c.post("/api/setup/entity-locations", headers=admin, json=link).status_code == 409
    # backdated change: waits for approval, never approved by the person who asked
    r = c.put(f"/api/setup/locations/{base['l2']}", headers=admin, json={"city": "Old City", "effective_from": YESTERDAY.isoformat(), "change_reason": "Fix"})
    assert r.status_code == 202, r.text
    pc = r.json()["pending_change"]["id"]
    assert c.get(f"/api/setup/locations/{base['l2']}", headers=admin).json()["city"] is None
    assert c.post(f"/api/setup/changes/{pc}/approve", headers=admin, json={}).status_code == 403
    assert c.post(f"/api/setup/changes/{pc}/approve", headers=admin2, json={"note": "ok"}).json()["status"] == "approved"
    assert c.get(f"/api/setup/locations/{base['l2']}", headers=admin).json()["city"] == "Old City"


def test_rule4_deactivate_never_delete(app_client, admin, base):
    c = app_client
    rid = c.post("/api/hr/grades", headers=admin, json={"code": "GX", "name": "Grade X"}).json()["rid"]
    assert c.delete(f"/api/hr/grades/{rid}", headers=admin).status_code == 405
    r = c.post(f"/api/hr/grades/{rid}/deactivate", headers=admin, json={"change_reason": "Not used"})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert rid not in [g["rid"] for g in c.get("/api/hr/grades", headers=admin).json()["items"]]
    assert rid in [g["rid"] for g in c.get("/api/hr/grades", headers=admin, params={"include_inactive": True}).json()["items"]]
    assert c.post(f"/api/hr/grades/{rid}/reactivate", headers=admin, json={}).json()["is_active"] is True


def test_rule5_codes_unique_case_insensitive(app_client, admin, base):
    r = app_client.post("/api/setup/locations", headers=admin, json={"code": "l1", "name": "Dup", "state_rid": base["tn"]})
    assert r.status_code == 409


def test_rule6_audit_log(app_client, admin, base):
    items = app_client.get("/api/setup/audit", headers=admin, params={"resource": "legal-entities"}).json()["items"]
    assert any(i["action"] == "create" for i in items)
    after = next(i for i in items if i["action"] == "create")["after"]
    assert after["pan"] != "AAACE1111A"  # secrets are masked in the audit log


def test_rule7_data_scope(app_client, admin, base):
    make_user("hr.l1@a.test", ["hr"], scope_location_rids=[base["l1"]])
    hr = token(app_client, "hr.l1@a.test")
    seen = [x["rid"] for x in app_client.get("/api/setup/locations", headers=hr).json()["items"]]
    assert base["l1"] in seen and base["l2"] not in seen
    assert app_client.get(f"/api/setup/locations/{base['l2']}", headers=hr).status_code == 404


def test_rule8_masking_is_set_in_role_permissions(app_client, admin, base):
    c = app_client
    r = c.post("/api/setup/role-permissions", headers=admin, json={"role": "auditor", "resource": "legal-entities", "actions": ["view"], "scope": "all",
                                                                    "masked_fields": ["pan"]})
    assert r.status_code == 201, r.text
    make_user("auditor@a.test", ["auditor"])
    aud = token(c, "auditor@a.test")
    assert c.get(f"/api/setup/legal-entities/{base['e1']}", headers=aud).json()["pan"].startswith("X")
    assert c.get(f"/api/setup/legal-entities/{base['e1']}", headers=admin).json()["pan"] == "AAACE1111A"
    assert c.post("/api/hr/grades", headers=aud, json={"code": "NO", "name": "No"}).status_code == 403


def test_rule9_excel_import_reconciles(app_client, admin, base):
    from openpyxl import Workbook, load_workbook

    c = app_client
    t = c.get("/api/setup/departments/template.xlsx", headers=admin)
    assert t.status_code == 200
    headers = [x.value for x in load_workbook(io.BytesIO(t.content))["Data"][1]]
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    row = {h: None for h in headers}
    for code, name in (("D-A", "Dept A"), ("D-B", "Dept B"), ("d-a", "Duplicate of A"), ("", "No code")):
        ws.append([{**row, "code": code, "name": name}[h] for h in headers])
    buf = io.BytesIO()
    wb.save(buf)
    files = {"file": ("d.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    dry = c.post("/api/setup/departments/import", headers=admin, files=files, data={"dry_run": "true"}).json()
    assert dry["imported"] == 2 and dry["rejected"] == 2 and dry["counts_reconcile"]
    assert c.get("/api/setup/departments", headers=admin, params={"code": "D-A"}).json()["total"] == 0  # dry run saved nothing
    rep = c.post("/api/setup/departments/import", headers=admin, files=files).json()
    assert rep["imported"] == 2 and rep["total"] == 4


def test_rule10_dependency_checks(app_client, admin, base):
    c = app_client
    assert c.post("/api/setup/locations", headers=admin, json={"code": "LX", "name": "X", "state_rid": 999999}).status_code == 422
    r = c.post(f"/api/setup/locations/{base['l2']}/deactivate", headers=admin, json={})
    assert r.json()["still_referenced_by"].get("entity-locations.location_rid") == 1
    assert c.post("/api/setup/biometric-devices", headers=admin, json={"code": "B1", "location_rid": base["l2"], "connection": "file"}).status_code == 422
    c.post(f"/api/setup/locations/{base['l2']}/reactivate", headers=admin, json={})


def test_rule11_client_isolation(app_client, admin, base):
    from app.config import load_client_yaml
    from app.core.bootstrap import bootstrap_client
    from app.db import SessionLocal
    from .conftest import HERE

    with SessionLocal() as db:
        bootstrap_client(db, load_client_yaml(str(HERE / "clients" / "client_b.yaml")))
        db.commit()
    make_user("admin@b.test", ["master_admin"], client_code="TB")
    b = token(app_client, "admin@b.test")
    assert app_client.get(f"/api/setup/locations/{base['l1']}", headers=b).status_code == 404
    assert app_client.get("/api/setup/locations", headers=b).json()["total"] == 0
    # the same code is free in another client
    tn_b = app_client.get("/api/setup/states", params={"code": "TN"}, headers=b).json()["items"][0]["rid"]
    assert app_client.post("/api/setup/locations", headers=b, json={"code": "L1", "name": "B's L1", "state_rid": tn_b}).status_code == 201


def test_special_reads(app_client, admin, base):
    c = app_client
    r = c.post("/api/setup/holiday-calendars", headers=admin, json={"code": f"TN-{TODAY.year}", "name": "TN", "year": TODAY.year, "location_rids": [base["l1"]],
                                                                     "holidays": [{"date": f"{TODAY.year}-01-26", "name": "Republic Day"}]})
    assert r.status_code == 201, r.text
    assert c.get(f"/api/setup/locations/{base['l1']}/holidays", headers=admin).json()["holidays"][0]["name"] == "Republic Day"
    ns = c.post("/api/setup/number-series", headers=admin, json={"code": "EMP", "object": "employee", "prefix": "TA-", "padding": 4, "start_number": 1}).json()
    assert c.get(f"/api/setup/number-series/{ns['rid']}/preview", headers=admin).json()["next"] == "TA-0001"
    doc = c.post("/api/setup/documents/upload-base64", headers=admin, json={"owner_type": "legal-entities", "owner_rid": base["e1"], "doc_type": "PAN card",
                                                                            "file_name": "pan.txt", "content_type": "text/plain", "content_base64": "aGVsbG8="})
    assert doc.status_code == 201, doc.text
    assert c.get(f"/api/setup/documents/{doc.json()['rid']}/file", headers=admin).content == b"hello"
    assert c.get("/api/setup/client", headers=admin).json()["code"] == "TA"


def test_users_one_login_per_person(app_client, admin, base):
    c = app_client
    p = c.post("/api/setup/persons", headers=admin, json={"first_name": "Uma", "last_name": "Test", "date_of_birth": "1990-01-01"}).json()
    u = c.post("/api/users", headers=admin, json={"email": "uma@a.test", "display_name": "Uma", "roles": ["employee"], "person_rid": p["rid"]})
    assert u.status_code == 201 and u.json()["temporary_password"]
    again = c.post("/api/users", headers=admin, json={"email": "uma2@a.test", "display_name": "Uma", "roles": ["employee"], "person_rid": p["rid"]})
    assert again.status_code == 409
    assert c.post(f"/api/users/{u.json()['id']}/deactivate", headers=admin).json()["is_active"] is False
    assert c.delete(f"/api/users/{u.json()['id']}", headers=admin).status_code == 405
