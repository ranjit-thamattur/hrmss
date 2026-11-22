"""Onboarding and employee CRUD through the Hotel Vivek APIs (/api/employee/...), on SYNTHETIC demo data."""
from datetime import date, timedelta

from .conftest import login

YESTERDAY = (date.today() - timedelta(days=1)).isoformat()


def rid_of(c, h, key, code):
    return c.get(f"/api/setup/{key}", headers=h, params={"code": code}).json()["items"][0]["rid"]


def job(c, h, ent, loc, dep, desg, **kw):
    return {"legal_entity_rid": rid_of(c, h, "legal-entities", ent), "location_rid": rid_of(c, h, "locations", loc),
            "department_rid": rid_of(c, h, "departments", dep), "designation_rid": rid_of(c, h, "designations", desg), **kw}


PERSON = {"first_name": "Test", "last_name": "Joiner", "date_of_birth": "1995-03-04", "gender": "male", "phone": "+91 90000 55555"}


def test_demo_data_is_loaded(c):
    h = login(c, "admin")
    assert c.get("/api/health").json()["client"] == "HV"
    assert c.get("/api/employee", headers=h).json()["total"] == 27
    assert c.get("/api/setup/legal-entities", headers=h).json()["total"] == 3


def test_onboard_with_two_jobs_and_a_login(c):
    h = login(c, "hr")
    body = {"person": {**PERSON, "pan": "abcpz9999q"},
            "assignments": [job(c, h, "HVH", "CHN", "FO", "FOE", pay_share=70, valid_from="2025-01-01"),
                            job(c, h, "HVR", "OOT", "FO", "FOE", pay_share=30, valid_from="2025-01-01")],
            "login": {"email": "test.joiner@hotelvivek.local", "roles": ["employee"]}}
    r = c.post("/api/employee/add", headers=h, json=body)
    assert r.status_code == 201, r.text
    out = r.json()
    assert [a["employee_number"][:4] for a in out["assignments"]] == ["HVH-", "HVR-"]
    assert out["login"]["temporary_password"]
    prof = c.get(f"/api/employee/{out['person_rid']}", headers=h).json()
    assert prof["total_pay_share"] == "100.00" or float(prof["total_pay_share"]) == 100
    assert prof["login"]["email"] == "test.joiner@hotelvivek.local"
    # same PAN again: refused, nothing saved
    again = c.post("/api/employee/add", headers=h, json={**body, "person": {**PERSON, "first_name": "Other", "pan": "ABCPZ9999Q"}, "login": None})
    assert again.status_code == 409


def test_onboarding_rules(c):
    h = login(c, "hr")
    over = {"person": {**PERSON, "first_name": "Over"}, "assignments": [job(c, h, "HVH", "CHN", "FO", "FOE", pay_share=80),
                                                                         job(c, h, "HVR", "OOT", "FO", "FOE", pay_share=40)]}
    assert c.post("/api/employee/add", headers=h, json=over).status_code == 422
    missing = {"person": {"first_name": "NoPhone", "last_name": "X", "date_of_birth": "1990-01-01", "gender": "male"},
               "assignments": [job(c, h, "HVH", "CHN", "FO", "FOE")]}
    assert "phone" in c.post("/api/employee/add", headers=h, json=missing).json()["detail"]
    wrong = {"person": {**PERSON, "first_name": "Wrong"}, "assignments": [job(c, h, "HVF", "OOT", "KIT", "CMS")]}  # HVF has no Ooty site
    assert c.post("/api/employee/add", headers=h, json=wrong).status_code == 422


def test_transfer_is_dated(c):
    h = login(c, "admin")
    r = c.post("/api/employee/add", headers=h, json={"person": {**PERSON, "first_name": "Mover"},
                                                     "assignments": [job(c, h, "HVH", "CHN", "HK", "RA", valid_from="2025-01-01")]})
    assert r.status_code == 201, r.text
    pr, ar = r.json()["person_rid"], r.json()["assignments"][0]["assignment_rid"]
    later = (date.today() + timedelta(days=10)).isoformat()
    mdu = rid_of(c, h, "locations", "MDU")
    t = c.put(f"/api/employee/{pr}/assignments/{ar}", headers=h, json={"location_rid": mdu, "effective_from": later, "change_reason": "Transfer to Madurai"})
    assert t.status_code == 200, t.text
    assert len(c.get(f"/api/hr/employment-assignments/{ar}/history", headers=h).json()) == 2
    now = c.get(f"/api/employee/{pr}", headers=h).json()["assignments"][0]
    then = c.get(f"/api/employee/{pr}", headers=h, params={"as_of": later}).json()["assignments"][0]
    assert now["location_rid"] != mdu and then["location_rid"] == mdu
    # backdated change to a job: waits for another person's approval
    back = c.put(f"/api/employee/{pr}/assignments/{ar}", headers=h, json={"designation_rid": rid_of(c, h, "designations", "HKS"), "effective_from": "2025-06-01"})
    assert back.status_code == 202


def test_change_end_and_deactivate(c):
    h = login(c, "admin")
    r = c.post("/api/employee/add", headers=h, json={"person": {**PERSON, "first_name": "Leaver"},
                                                     "assignments": [job(c, h, "HVH", "CHN", "HK", "RA", valid_from="2025-01-01")]})
    pr, ar = r.json()["person_rid"], r.json()["assignments"][0]["assignment_rid"]
    assert c.put(f"/api/employee/{pr}", headers=h, json={"phone": "+91 90000 66666"}).json()["phone"] == "+91 90000 66666"
    assert c.post(f"/api/employee/{pr}/deactivate", headers=h, json={}).status_code == 409  # still has a job
    assert c.post(f"/api/employee/{pr}/assignments/{ar}/end", headers=h, json={"end_date": YESTERDAY}).status_code == 200
    assert c.post(f"/api/employee/{pr}/deactivate", headers=h, json={"change_reason": "Left"}).json()["is_active"] is False
    assert c.delete(f"/api/employee/{pr}", headers=h).status_code == 405


def test_scope_and_masking(c):
    ooty = login(c, "hr.ooty")
    people = c.get("/api/employee", headers=ooty).json()["items"]
    assert people and all(any(a["location_rid"] == rid_of(c, login(c, "admin"), "locations", "OOT") for a in p["assignments"]) or not p["assignments"]
                          for p in people)
    hod = login(c, "hod")
    team = c.get("/api/employee", headers=hod).json()["items"]
    assert 0 < len(team) < 27
    assert all((p.get("pan") or "X").startswith("X") for p in team)


# ---------------------------------------------------------------- employee master import (PEAKHRMS-125, PEAKHRMS-42)
def _sheet(rows, headers=None):
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(headers or ["person_ref", "first_name", "last_name", "date_of_birth", "gender", "phone", "legal_entity_code", "location_code",
                          "department_code", "designation_code", "pay_share", "joining_date"])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return {"file": ("employees.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}


ROWS = [
    ["", "Imp", "One", "1991-01-01", "male", "9000080001", "HVH", "CHN", "FO", "FOE", 100, "2026-04-01"],
    ["T2", "Imp", "Two", "1991-01-02", "female", "9000080002", "HVH", "CHN", "FB", "STW", 60, "2026-04-01"],
    ["T2", None, None, None, None, None, "HVR", "OOT", "FB", "STW", 40, "2026-04-01"],
    ["", "Imp", "Bad", "1991-01-03", "male", "9000080003", "HVF", "OOT", "KIT", "CMS", 100, "2026-04-01"],  # HVF has no Ooty site
    ["", "Imp", "NoPhone", "1991-01-04", "male", None, "HVH", "CHN", "FO", "FOE", 100, "2026-04-01"],
]


def test_employee_import_dry_run_then_real(c):
    h = login(c, "hr")
    assert c.get("/api/employee/import/template.xlsx", headers=h).status_code == 200
    before = c.get("/api/employee", headers=h).json()["total"]
    dry = c.post("/api/employee/import", headers=h, files=_sheet(ROWS), data={"dry_run": "true"}).json()
    assert (dry["total"], dry["imported"], dry["rejected"], dry["people_imported"]) == (5, 3, 2, 2) and dry["counts_reconcile"]
    assert c.get("/api/employee", headers=h).json()["total"] == before  # dry run saved nothing
    real = c.post("/api/employee/import", headers=h, files=_sheet(ROWS)).json()
    assert real["imported"] == 3 and real["people_imported"] == 2
    two = next(p for p in real["people"] if p["person"] == "Imp Two")
    assert [n[:4] for n in two["employee_numbers"]] == ["HVH-", "HVR-"]
    assert c.get("/api/employee", headers=h).json()["total"] == before + 2
    again = c.post("/api/employee/import", headers=h, files=_sheet(ROWS[:1]), data={"dry_run": "true"}).json()
    assert again["rejected"] == 1  # same name + date of birth: already a person


def test_employee_import_with_column_mapping(c):
    h = login(c, "hr")
    headers = ["Emp First", "Surname", "DOB", "Sex", "Mobile", "Company", "Site", "Dept", "Role"]
    rows = [["Map", "Ped", "1992-03-03", "female", "9000080009", "HVH", "MDU", "HK", "RA"]]
    mapping = {"Emp First": "first_name", "Surname": "last_name", "DOB": "date_of_birth", "Sex": "gender", "Mobile": "phone",
               "Company": "legal_entity_code", "Site": "location_code", "Dept": "department_code", "Role": "designation_code"}
    import json

    r = c.post("/api/employee/import", headers=h, files=_sheet(rows, headers), data={"dry_run": "true", "mapping": json.dumps(mapping)})
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 1
    bad = c.post("/api/employee/import", headers=h, files=_sheet(rows, headers), data={"mapping": '{"Emp First": "nope"}'})
    assert bad.status_code == 422


def test_employee_import_csv_and_permissions(c):
    csv = "first_name,last_name,date_of_birth,gender,phone,legal_entity_code,location_code,department_code,designation_code\n" \
          "Csv,Person,1993-04-04,male,9000080010,HVH,CHN,FO,FOE\n"
    files = {"file": ("employees.csv", csv.encode(), "text/csv")}
    assert c.post("/api/employee/import", headers=login(c, "hr"), files=files, data={"dry_run": "true"}).json()["imported"] == 1
    assert c.post("/api/employee/import", headers=login(c, "employee"), files=files, data={"dry_run": "true"}).status_code == 403
