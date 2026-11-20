"""Generate the Postman collection + environment for the HRMS core and Hotel Vivek APIs (backend first, 18-Nov).

    python scripts/make_postman.py        -> postman/Peak-HRMS-Core.postman_collection.json
                                             postman/local.postman_environment.json
                                             postman/samples/departments-import.xlsx

Run order = folder order. Every request has tests, so "Run collection" in Postman (or newman in CI) shows
pass/fail per call. Works against the SYNTHETIC demo data (SEED_DEMO=true) on a laptop; safe to run again
(new codes each run).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "postman"
sys.path.insert(0, str(ROOT / "services" / "hrms-core" / "backend"))
from app.core.specs import SPECS  # noqa: E402  (paths come from the catalogue: /api/setup/... or /api/hr/...)


def P(key: str) -> str:
    return SPECS[key].path

# ---------------------------------------------------------------- helpers
def tests(*lines: str) -> list[dict]:
    return [{"listen": "test", "script": {"type": "text/javascript", "exec": list(lines)}}]


def expect(code: int | str, *more: str) -> list[dict]:
    codes = code if isinstance(code, str) else f"[{code}]"
    return tests(f"pm.test('status {codes}', () => pm.expect({codes}).to.include(pm.response.code));", *more)


def req(name: str, method: str, path: str, body: dict | None = None, token: str = "token_admin", ev: list | None = None,
        query: dict | None = None, desc: str = "", formdata: list | None = None) -> dict:
    url = {"raw": "{{baseUrl}}" + path, "host": ["{{baseUrl}}"], "path": [p for p in path.split("?")[0].strip("/").split("/")]}
    if query:
        url["query"] = [{"key": k, "value": str(v)} for k, v in query.items()]
        url["raw"] += "?" + "&".join(f"{k}={v}" for k, v in query.items())
    r: dict = {"method": method, "header": [], "url": url, "description": desc}
    if token:
        r["auth"] = {"type": "bearer", "bearer": [{"key": "token", "value": "{{" + token + "}}", "type": "string"}]}
    else:
        r["auth"] = {"type": "noauth"}
    if body is not None:
        r["header"].append({"key": "Content-Type", "value": "application/json"})
        r["body"] = {"mode": "raw", "raw": json.dumps(body, indent=2), "options": {"raw": {"language": "json"}}}
    if formdata is not None:
        r["body"] = {"mode": "formdata", "formdata": formdata}
    return {"name": name, "request": r, "event": ev or expect(200)}


def folder(name: str, items: list, desc: str = "") -> dict:
    return {"name": name, "item": items, "description": desc}


def save(var: str, expr: str = "pm.response.json().rid") -> str:
    return f"if (pm.response.code < 300) pm.collectionVariables.set('{var}', {expr});"


# ---------------------------------------------------------------- 0 sign in
def login(who: str, email_var: str) -> dict:
    return req(f"Sign in: {who}", "POST", "/api/auth/login", {"email": "{{" + email_var + "}}", "password": "{{password}}"}, token="",
               ev=expect(200, "pm.test('got a token', () => pm.expect(pm.response.json().token).to.be.a('string'));",
                         f"pm.collectionVariables.set('token_{who}', pm.response.json().token);"))


signin = folder("00 Health and sign-in", [
    {**req("Health", "GET", "/api/health", token="", ev=expect(200, "pm.test('client HV', () => pm.expect(pm.response.json().client).to.eql('HV'));")),
     "event": [{"listen": "prerequest", "script": {"type": "text/javascript", "exec": [
         "const d = new Date(); const f = new Date(Date.now() + 7*864e5); const y = new Date(Date.now() - 864e5);",
         "const iso = x => x.toISOString().slice(0,10);",
         "pm.collectionVariables.set('today', iso(d)); pm.collectionVariables.set('future', iso(f)); pm.collectionVariables.set('yesterday', iso(y));",
         "pm.collectionVariables.set('run', String(Date.now()).slice(-6)); pm.collectionVariables.set('run4', String(Date.now()).slice(-4));"]}},
         *expect(200, "pm.test('client HV', () => pm.expect(pm.response.json().client).to.eql('HV'));")]},
    login("admin", "adminEmail"), login("hr", "hrEmail"), login("ooty", "hrOotyEmail"), login("hod", "hodEmail"), login("employee", "employeeEmail"),
    req("Who am I", "GET", "/api/auth/me", ev=expect(200, "pm.test('master admin', () => pm.expect(pm.response.json().roles).to.include('master_admin'));")),
    req("No token = 401", "GET", "/api/setup/locations", token="", ev=expect(401)),
], "Sign in as the synthetic demo users. Tokens are kept in collection variables.")

# ---------------------------------------------------------------- lookups from the demo data
def lookup(name: str, path: str, var: str, code: str) -> dict:
    return req(f"Find {name} {code}", "GET", path, query={"code": code},
               ev=expect(200, f"pm.collectionVariables.set('{var}', pm.response.json().items[0].rid);"))


lookups = folder("01 Look up demo records", [
    lookup("state", "/api/setup/states", "state_tn", "TN"),
    lookup("legal entity", "/api/setup/legal-entities", "le_hvh", "HVH"),
    lookup("legal entity", "/api/setup/legal-entities", "le_hvr", "HVR"),
    lookup("location", "/api/setup/locations", "loc_chn", "CHN"),
    lookup("location", "/api/setup/locations", "loc_oot", "OOT"),
    lookup("department", "/api/setup/departments", "dep_fo", "FO"),
    lookup("designation", "/api/setup/designations", "des_foe", "FOE"),
    lookup("grade", P("grades"), "grade_g1", "G1"),
    lookup("employment type", P("employment-types"), "et_perm", "PERM"),
    lookup("leave type", P("leave-types"), "lt_cl", "CL"),
    lookup("shift", P("shifts"), "shift_gen", "GEN"),
    lookup("weekly off", P("weekly-offs"), "wo_sun", "SUN"),
])

# ---------------------------------------------------------------- 02 company setup: CRUD for every entity
R = "{{run}}"
# key: (title, create body, change body or None, var name)
ENTITIES = [
    ("legal-entities", "Legal entity", {"code": f"PE{R}", "registered_name": f"Postman Entity {R} Pvt Ltd", "pan": "aaacp1234q", "state_rid": "{{state_tn}}",
                                        "gstin": "33AAACP1234Q1Z5", "registered_address": "1 Test Street, Chennai"},
     {"short_name": "Postman Co"}),
    ("locations", "Location", {"code": f"PL{R}", "name": f"Postman Location {R}", "state_rid": "{{state_tn}}", "city": "Chennai", "pincode": "600002"},
     {"name": f"Postman Location {R} (renamed)"}),
    ("entity-locations", "Entity at location", {"legal_entity_rid": "{{legal-entities_rid}}", "location_rid": "{{locations_rid}}"}, None),
    ("departments", "Department", {"code": f"PD{R}", "name": f"Postman Dept {R}"}, {"name": f"Postman Department {R}"}),
    ("department-entities", "Department in entity", {"department_rid": "{{departments_rid}}", "legal_entity_rid": "{{legal-entities_rid}}"}, None),
    ("designations", "Designation", {"code": f"PG{R}", "title": "Postman Tester", "job_family": "QA"}, {"title": "Senior Postman Tester"}),
    ("cost-centres", "Cost centre", {"code": f"PC{R}", "name": "Postman ops", "legal_entity_rid": "{{legal-entities_rid}}"}, {"name": "Postman operations"}),
    ("statutory-registrations", "Statutory registration", {"legal_entity_rid": "{{legal-entities_rid}}", "type": "PF", "number": "TN/MAS/0099999"},
     {"number": "TN/MAS/0099998"}),
    ("holiday-calendars", "Holiday calendar", {"code": f"PH{R}", "name": "Postman holidays", "year": 2027, "location_rids": ["{{locations_rid}}"],
                                                "holidays": [{"date": "2027-01-26", "name": "Republic Day", "kind": "fixed"}]},
     None),
    ("biometric-devices", "Biometric device", {"code": f"PB{R}", "make": "DemoMake", "location_rid": "{{locations_rid}}", "connection": "file"},
     {"model": "X200"}),
    ("payroll-calendars", "Payroll calendar", {"legal_entity_rid": "{{legal-entities_rid}}", "period": "2027-01", "attendance_cutoff": "2027-01-25",
                                                "pay_date": "2027-01-31"}, {"pay_date": "2027-01-30"}),
    ("grades", "Grade", {"code": f"PR{R}", "name": "Postman grade", "level": 9, "pay_min": 10000, "pay_max": 20000}, {"pay_max": 25000}),
    ("leave-types", "Leave type", {"code": f"PV{R}", "name": "Postman leave", "paid": True, "accrual_days_per_year": 6, "accrual_frequency": "yearly"},
     {"accrual_days_per_year": 8}),
    ("employment-types", "Employment type", {"code": f"PT{R}", "name": "Postman type", "statutory_types": ["PF", "PT"], "leave_type_rids": ["{{leave-types_rid}}"]},
     {"statutory_types": ["PT"]}),
    ("shifts", "Shift", {"code": f"PS{R}", "name": "Postman night", "start_time": "22:00", "end_time": "06:00", "break_minutes": 30}, {"grace_minutes": 15}),
    ("weekly-offs", "Weekly off", {"code": f"PW{R}", "name": "Postman weekend", "days_off": ["saturday", "sunday"]}, {"days_off": ["sunday"]}),
    ("bank-accounts", "Bank account", {"legal_entity_rid": "{{legal-entities_rid}}", "bank_name": "Demo Bank", "ifsc": "DEMO0004321",
                                       "account_number": "123456789012", "purpose": "salary"}, {"branch": "Anna Nagar"}),
    ("policies", "Policy", {"code": f"PP{R}", "name": "Postman policy", "applies_to": {"legal_entity_rids": ["{{legal-entities_rid}}"]},
                            "settings": {"late_marks_per_half_day": 3}}, {"settings": {"late_marks_per_half_day": 2}}),
    ("number-series", "Number series", {"code": f"PN{R}", "object": "employee", "legal_entity_rid": "{{legal-entities_rid}}", "prefix": "PM-",
                                        "padding": 5, "start_number": 1}, {"prefix": "PMX-"}),
    ("approval-workflows", "Approval workflow", {"code": f"PA{R}", "name": "Postman leave approval", "request_type": "leave",
                                                 "steps": [{"approver_type": "reporting_level", "value": 1}]}, {"name": "Leave approval"}),
    ("role-permissions", "Role permission", {"role": f"viewer_{R}", "resource": "locations", "actions": ["view"], "scope": "all", "masked_fields": []},
     {"actions": ["view", "export"]}),
    ("persons", "Person", {"first_name": f"Postman{R}", "last_name": "Person", "date_of_birth": "1992-02-02", "gender": "female",
                           "phone": "+91 90000 77777", "pan": "abcpq{{run4}}r"}, {"phone": "+91 90000 77778"}),
    ("employment-assignments", "Employment assignment", {"person_rid": "{{persons_rid}}", "legal_entity_rid": "{{legal-entities_rid}}",
                                                         "location_rid": "{{locations_rid}}", "department_rid": "{{departments_rid}}",
                                                         "designation_rid": "{{designations_rid}}", "grade_rid": "{{grades_rid}}", "pay_share": 100,
                                                         "is_primary": True}, {"pay_share": 90}),
    ("reporting-lines", "Reporting line", {"assignment_rid": "{{employment-assignments_rid}}", "reports_to_person_rid": "{{manager_rid}}", "type": "line"},
     {"type": "functional"}),
]
SETUP_ONLY_FIELDS = {"approval-workflows": 409}  # one workflow per request type: a second run may already have one


def crud(key: str, title: str, body: dict, change: dict | None) -> dict:
    base = P(key)
    v = f"{key}_rid"
    create_codes = "[201, 409]" if key in SETUP_ONLY_FIELDS else "[201]"
    items = [
        req(f"Create {title.lower()}", "POST", base, body, ev=expect(create_codes, save(v))),
        req(f"List {title.lower()}s", "GET", base, ev=expect(200, "pm.test('has items', () => pm.expect(pm.response.json().total).to.be.above(0));")),
        req(f"Get one {title.lower()}", "GET", f"{base}/{{{{{v}}}}}"),
    ]
    if change:
        items += [
            req("Change from a future date (new version)", "PUT", f"{base}/{{{{{v}}}}}", {**change, "effective_from": "{{future}}",
                                                                                         "change_reason": "Postman: dated change"}),
            req("Get as of the future date", "GET", f"{base}/{{{{{v}}}}}", query={"as_of": "{{future}}"}),
        ]
    items += [
        req("History (all versions)", "GET", f"{base}/{{{{{v}}}}}/history",
            ev=expect(200, "pm.test('versions listed', () => pm.expect(pm.response.json().length).to.be.above(0));")),
        req("Delete is refused (405)", "DELETE", f"{base}/{{{{{v}}}}}", ev=expect(405)),
    ]
    if key not in ("employment-assignments", "reporting-lines", "persons"):
        items += [
            req("Deactivate today", "POST", f"{base}/{{{{{v}}}}}/deactivate", {"change_reason": "Postman: deactivate"},
                ev=expect(200, "pm.test('inactive', () => pm.expect(pm.response.json().is_active).to.eql(false));")),
            req("Reactivate today", "POST", f"{base}/{{{{{v}}}}}/reactivate", {"change_reason": "Postman: reactivate"},
                ev=expect(200, "pm.test('active', () => pm.expect(pm.response.json().is_active).to.eql(true));")),
        ]
    items.append(req("Excel template", "GET", f"{base}/template.xlsx"))
    return folder(f"{title}", items)


manager = req("Create a manager person (for the reporting line)", "POST", "/api/setup/persons",
              {"first_name": f"Manager{R}", "last_name": "Person", "date_of_birth": "1980-03-03", "gender": "male", "phone": "+91 90000 88888"},
              ev=expect(201, save("manager_rid")))
setup_items = []
for key, title, body, change in ENTITIES:
    if key == "reporting-lines":
        setup_items.append(folder("Manager (helper)", [manager]))
    setup_items.append(crud(key, title, body, change))
setup_items.append(folder("Documents", [
    req("Upload a document (base64)", "POST", "/api/setup/documents/upload-base64",
        {"owner_type": "legal-entities", "owner_rid": "{{legal-entities_rid}}", "doc_type": "Incorporation certificate", "file_name": "certificate.txt",
         "content_type": "text/plain", "content_base64": "U3ludGhldGljIHRlc3QgZG9jdW1lbnQ="}, ev=expect(201, save("documents_rid"))),
    req("List documents", "GET", "/api/setup/documents"),
    req("Download the file", "GET", "/api/setup/documents/{{documents_rid}}/file"),
    req("Deactivate the document", "POST", "/api/setup/documents/{{documents_rid}}/deactivate", {"change_reason": "Postman"}),
]))
setup_items.append(folder("Special reads", [
    req("Holidays at a location (2026)", "GET", "/api/setup/locations/{{loc_chn}}/holidays", query={"year": 2026},
        ev=expect(200, "pm.test('has holidays', () => pm.expect(pm.response.json().holidays.length).to.be.above(0));")),
    req("Next employee number (preview)", "GET", "/api/setup/number-series/{{number-series_rid}}/preview"),
    req("Policies for an entity", "GET", "/api/setup/policies/resolve", query={"legal_entity_rid": "{{le_hvr}}"}),
    req("This client (from client.yaml)", "GET", "/api/setup/client", ev=expect(200, "pm.test('HV', () => pm.expect(pm.response.json().code).to.eql('HV'));")),
    req("Entity-location link: end it", "POST", "/api/setup/entity-locations/{{entity-locations_rid}}/end", {"end_date": "{{future}}",
                                                                                                              "change_reason": "Postman: end link"}),
]))
setup = folder("02 Company Setup - CRUD for every entity", setup_items,
               "Create, list, get, change from a date, history, deactivate/reactivate, delete refused, Excel template. Records are never deleted.")

# ---------------------------------------------------------------- 03 the eleven rules, shown one by one
rules = folder("03 Design rules (acceptance)", [
    req("1 client_id in the body is ignored", "POST", "/api/setup/designations", {"code": f"PX{R}", "title": "Ignored client id", "client_id": 999},
        ev=expect(201)),
    req("2 Effective dating: as_of today shows the old name", "GET", "/api/setup/locations/{{locations_rid}}",
        ev=expect(200, "pm.test('old name today', () => pm.expect(pm.response.json().name).to.not.include('renamed'));")),
    req("3a Overlap: same entity-location link again = 409", "POST", "/api/setup/entity-locations",
        {"legal_entity_rid": "{{le_hvh}}", "location_rid": "{{loc_chn}}"}, ev=expect(409)),
    req("3b Backdated change = 202, waits for approval", "PUT", "/api/setup/designations/{{des_foe}}",
        {"job_family": "Front Office (corrected)", "effective_from": "{{yesterday}}", "change_reason": "Postman: backdated"},
        ev=expect(202, "pm.collectionVariables.set('pending_id', pm.response.json().pending_change.id);")),
    req("3c Pending changes list", "GET", "/api/setup/changes"),
    req("3d Requester cannot approve own change = 403", "POST", "/api/setup/changes/{{pending_id}}/approve", {"note": "self"}, ev=expect(403)),
    req("3e Another user (HR) approves = applied", "POST", "/api/setup/changes/{{pending_id}}/approve", {"note": "ok"}, token="token_hr",
        ev=expect(200, "pm.test('approved', () => pm.expect(pm.response.json().status).to.eql('approved'));")),
    req("4 Delete is refused = 405", "DELETE", "/api/setup/locations/{{loc_chn}}", ev=expect(405)),
    req("5 Codes are unique, not case-sensitive = 409", "POST", "/api/setup/locations", {"code": "chn", "name": "Duplicate", "state_rid": "{{state_tn}}"},
        ev=expect(409)),
    req("6 Audit log (append-only, secrets masked)", "GET", "/api/setup/audit", query={"resource": "legal-entities"},
        ev=expect(200, "pm.test('entries', () => pm.expect(pm.response.json().items.length).to.be.above(0));")),
    req("7a Data scope: Ooty HR sees only Ooty", "GET", "/api/setup/locations", token="token_ooty",
        ev=expect(200, "pm.test('only OOT', () => pm.expect(pm.response.json().items.map(x => x.code)).to.eql(['OOT']));")),
    req("7b Data scope: Ooty HR cannot open Chennai = 404", "GET", "/api/setup/locations/{{loc_chn}}", token="token_ooty", ev=expect(404)),
    req("8 Masking: head of department sees PAN masked", "GET", "/api/employee", token="token_hod",
        ev=expect(200, "pm.test('masked', () => pm.response.json().items.forEach(p => { if (p.pan) pm.expect(p.pan[0]).to.eql('X'); }));")),
    req("9 Excel import (dry run): rows imported + rejected = rows in file", "POST", "/api/setup/departments/import",
        formdata=[{"key": "file", "type": "file", "src": "samples/departments-import.xlsx"}, {"key": "dry_run", "value": "true", "type": "text"}],
        ev=expect(200, "const r = pm.response.json();", "pm.test('reconciles', () => pm.expect(r.counts_reconcile).to.eql(true));",
                  "pm.test('bad rows rejected', () => pm.expect(r.rejected).to.be.above(0));"),
        desc="In Postman desktop choose the file postman/samples/departments-import.xlsx in the Body tab if it is not found."),
    req("10 Dependency check: unknown location = 422", "POST", "/api/setup/biometric-devices",
        {"code": f"PQ{R}", "location_rid": 999999, "connection": "file"}, ev=expect(422)),
    req("10b Employee role cannot create = 403", "POST", P("grades"), {"code": f"PY{R}", "name": "No"}, token="token_employee", ev=expect(403)),
    req("11 Client isolation: the client comes from the login (see rule 1; tested with two clients in CI)", "GET", "/api/auth/me",
        ev=expect(200, "pm.test('client HV', () => pm.expect(pm.response.json().client.code).to.eql('HV'));")),
], "One request per rule of the design doc (18-Nov). Expected status codes are part of the test.")

# ---------------------------------------------------------------- 04 onboarding (Hotel Vivek API)
def job(le: str, loc: str, share: int, primary: bool) -> dict:
    return {
        "legal_entity_rid": le, "location_rid": loc, "department_rid": "{{dep_fo}}", "designation_rid": "{{des_foe}}", "grade_rid": "{{grade_g1}}",
        "employment_type_rid": "{{et_perm}}", "shift_rid": "{{shift_gen}}", "weekly_off_rid": "{{wo_sun}}", "pay_share": share, "is_primary": primary,
        "valid_from": "{{today}}"}


onboard = folder("04 Onboarding an employee (Hotel Vivek: /api/employee)", [
    req("Onboard: person + 2 jobs (60/40 split) + login", "POST", "/api/employee/add", {
        "person": {"first_name": f"Joiner{R}", "last_name": "Demo", "date_of_birth": "1996-05-05", "gender": "female", "phone": "+91 90000 12345",
                   "email": f"joiner{R}@example.com", "pan": "abcpj{{run4}}k"},
        "assignments": [job("{{le_hvh}}", "{{loc_chn}}", 60, True), job("{{le_hvr}}", "{{loc_oot}}", 40, False)],
        "login": {"email": f"joiner{R}@hotelvivek.local", "roles": ["employee"]}, "change_reason": "Postman onboarding"},
        token="token_hr", ev=expect(201, "const r = pm.response.json();", save("emp_rid", "r.person_rid"),
                                    save("job2_rid", "r.assignments[1].assignment_rid"),
                                    "pm.test('employee numbers', () => pm.expect(r.assignments[0].employee_number).to.match(/^HVH-/));",
                                    "pm.test('temporary password shown once', () => pm.expect(r.login.temporary_password).to.be.a('string'));")),
    req("List employees", "GET", "/api/employee", query={"q": f"Joiner{R}"},
        ev=expect(200, "pm.test('found', () => pm.expect(pm.response.json().total).to.eql(1));")),
    req("Employee profile", "GET", "/api/employee/{{emp_rid}}",
        ev=expect(200, "pm.test('two jobs, 100%', () => { const r = pm.response.json(); pm.expect(r.assignments.length).to.eql(2); "
                       "pm.expect(Number(r.total_pay_share)).to.eql(100); });")),
    req("Change person details (today)", "PUT", "/api/employee/{{emp_rid}}", {"phone": "+91 90000 12346", "change_reason": "New number"}),
    req("Transfer job 2 from a future date", "PUT", "/api/employee/{{emp_rid}}/assignments/{{job2_rid}}",
        {"designation_rid": "{{designations_rid}}", "effective_from": "{{future}}", "change_reason": "Promotion"}),
    req("Third job over 100% is refused = 409", "POST", "/api/employee/{{emp_rid}}/assignments", job("{{le_hvh}}", "{{loc_chn}}", 10, False), ev=expect(409)),
    req("Second login for the same person = 409", "POST", "/api/employee/{{emp_rid}}/login", {"email": f"other{R}@hotelvivek.local"}, ev=expect(409)),
    req("Pay shares over 100% at onboarding = 422", "POST", "/api/employee/add", {
        "person": {"first_name": f"Over{R}", "last_name": "Demo", "date_of_birth": "1990-01-01", "gender": "male", "phone": "+91 90000 22222"},
        "assignments": [job("{{le_hvh}}", "{{loc_chn}}", 70, True), job("{{le_hvr}}", "{{loc_oot}}", 40, False)]}, ev=expect(422)),
    req("Missing required field (client.yaml: phone) = 422", "POST", "/api/employee/add", {
        "person": {"first_name": f"NoPhone{R}", "last_name": "Demo", "date_of_birth": "1990-01-01", "gender": "male"},
        "assignments": [job("{{le_hvh}}", "{{loc_chn}}", 100, True)]}, ev=expect(422)),
    req("Deactivate while jobs are active = 409", "POST", "/api/employee/{{emp_rid}}/deactivate", {"change_reason": "Test"}, ev=expect(409)),
    req("End job 2 (end of the second job)", "POST", "/api/employee/{{emp_rid}}/assignments/{{job2_rid}}/end",
        {"end_date": "{{future}}", "change_reason": "Second job ends"}, ev=expect("[200, 422]")),
    req("Employee sees only themselves", "GET", "/api/employee", token="token_employee",
        ev=expect(200, "pm.test('self only', () => pm.expect(pm.response.json().total).to.eql(1));")),
    req("Delete is refused = 405", "DELETE", "/api/employee/{{emp_rid}}", ev=expect(405)),
], "Hotel Vivek's own APIs on top of the core. One person, one login, one employment assignment per job with its pay share.")

# ---------------------------------------------------------------- 05 users
users = folder("05 Users and roles", [
    req("List logins", "GET", "/api/users"),
    req("Create a login", "POST", "/api/users", {"email": f"pm.user{R}@hotelvivek.local", "display_name": "Postman User", "roles": ["hr"],
                                                 "scope_location_rids": ["{{loc_oot}}"]},
        ev=expect(201, save("user_id", "pm.response.json().id"))),
    req("Get the login", "GET", "/api/users/{{user_id}}"),
    req("Change roles and scope", "PUT", "/api/users/{{user_id}}", {"roles": ["hr", "payroll_preparer"], "scope_location_rids": []}),
    req("HR cannot give master_admin = 403", "PUT", "/api/users/{{user_id}}", {"roles": ["master_admin"]}, token="token_hr", ev=expect(403)),
    req("Reset password (temporary, shown once)", "POST", "/api/users/{{user_id}}/reset-password"),
    req("Deactivate", "POST", "/api/users/{{user_id}}/deactivate"),
    req("Activate", "POST", "/api/users/{{user_id}}/activate"),
    req("Delete is refused = 405", "DELETE", "/api/users/{{user_id}}", ev=expect(405)),
])

collection = {
    "info": {"name": "Peak HRMS Core + Hotel Vivek APIs", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
             "description": "Backend-first API tests (design review 18-Nov): Company Setup CRUD, the eleven rules, onboarding, users. "
                            "SYNTHETIC demo data only. Generated by scripts/make_postman.py - change the script, not this file."},
    "item": [signin, lookups, setup, rules, onboard, users],
    "variable": [{"key": k, "value": ""} for k in ("run", "run4", "today", "future", "yesterday")],
}
env = {"name": "Peak HRMS local (synthetic)", "values": [
    {"key": "baseUrl", "value": "http://localhost:8000", "enabled": True},
    {"key": "password", "value": "Peak@12345", "type": "secret", "enabled": True},
    {"key": "adminEmail", "value": "admin@hotelvivek.local", "enabled": True},
    {"key": "hrEmail", "value": "hr@hotelvivek.local", "enabled": True},
    {"key": "hrOotyEmail", "value": "hr.ooty@hotelvivek.local", "enabled": True},
    {"key": "hodEmail", "value": "hod@hotelvivek.local", "enabled": True},
    {"key": "employeeEmail", "value": "employee@hotelvivek.local", "enabled": True},
]}


def sample_import(path: Path) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(["code", "name", "parent_code", "head_person_rid", "valid_from", "valid_to"])
    ws.append(["IMP-SEC", "Security", None, None, None, None])
    ws.append(["IMP-SPA", "Spa and wellness", None, None, "2026-04-01", None])
    ws.append(["imp-sec", "Duplicate of Security (rejected: same code in file)", None, None, None, None])
    ws.append(["FO", "Front Office again (rejected: code already used)", None, None, None, None])
    ws.append(["IMP-BAD", "Bad parent (rejected)", "NOPE", None, None, None])
    ws.append([None, "No code (rejected)", None, None, None, None])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    (OUT / "Peak-HRMS-Core.postman_collection.json").write_text(json.dumps(collection, indent=2), encoding="utf-8")
    (OUT / "local.postman_environment.json").write_text(json.dumps(env, indent=2), encoding="utf-8")
    sample_import(OUT / "samples" / "departments-import.xlsx")
    n = json.dumps(collection).count('"request": {')
    print(f"Postman: {n} requests -> {OUT}")
