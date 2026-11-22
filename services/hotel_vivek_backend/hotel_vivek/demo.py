"""SYNTHETIC demo data for laptops (ENVIRONMENT local/dev/test). Invented names, numbers and IDs only;
no real Hotel Vivek data is ever written here. QA and production get real data through the APIs / Excel imports.

Shaped like the design doc's test clients: three legal entities across Tamil Nadu and Karnataka, one person with
two jobs (60/40 pay split) and one entity with no PF/ESI registration.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

from sqlalchemy import select

from app import models as m
from app.config import get_settings
from app.core import engine
from app.core.context import system_ctx
from app.core.identity import get_identity
from app.core.schemas import create_schema, split_create
from app.core.specs import SPECS
from app.services import onboarding, users

D0 = date(2024, 4, 1)  # setup data applies from the start of FY 2024-25


def _mk(ctx, key: str, data: dict, start: date = D0) -> int:  # noqa: ANN001
    """Same path as the API: validate with the request schema, then create."""
    vals = split_create(create_schema(key).model_validate(data).model_dump())[0]
    return engine.create(ctx, SPECS[key], vals, start, None, "Demo data").rid


def load(db, client: m.Client) -> None:  # noqa: ANN001
    if db.scalar(select(m.LegalEntity.rid).where(m.LegalEntity.client_id == client.id).limit(1)):
        return  # already loaded
    ctx = system_ctx(db, client.id, "demo-data")
    st = {s.code: s.rid for s in db.scalars(select(m.State).where(m.State.client_id == client.id))}

    # ---- legal entities (3), locations (5) and where each entity operates
    ents = {
        "HVH": _mk(ctx, "legal-entities", {"code": "HVH", "registered_name": "Demo Vivek Hotels Private Limited", "short_name": "Vivek Hotels",
                                           "pan": "AAACV1234A", "tan": "CHEV12345A", "gstin": "33AAACV1234A1Z5", "cin": "U55101TN2010PTC012345",
                                           "state_rid": st["TN"], "registered_address": "1 Demo Road, Chennai 600001"}),
        "HVR": _mk(ctx, "legal-entities", {"code": "HVR", "registered_name": "Demo Vivek Resorts LLP", "short_name": "Vivek Resorts",
                                           "pan": "AAFFV5678B", "gstin": "33AAFFV5678B1Z2", "state_rid": st["TN"]}),
        "HVF": _mk(ctx, "legal-entities", {"code": "HVF", "registered_name": "Demo Vivek Foods Private Limited", "short_name": "Vivek Foods",
                                           "pan": "AAACV9012C", "gstin": "29AAACV9012C1Z8", "state_rid": st["KA"]}),
    }
    locs = {
        "CHN": _mk(ctx, "locations", {"code": "CHN", "name": "Chennai City Hotel", "state_rid": st["TN"], "city": "Chennai", "pincode": "600001"}),
        "OOT": _mk(ctx, "locations", {"code": "OOT", "name": "Ooty Hill Resort", "state_rid": st["TN"], "city": "Ooty", "pincode": "643001"}),
        "MDU": _mk(ctx, "locations", {"code": "MDU", "name": "Madurai Temple View", "state_rid": st["TN"], "city": "Madurai", "pincode": "625001"}),
        "KOD": _mk(ctx, "locations", {"code": "KOD", "name": "Kodaikanal Lake Resort", "state_rid": st["TN"], "city": "Kodaikanal", "pincode": "624101"}),
        "BLR": _mk(ctx, "locations", {"code": "BLR", "name": "Bengaluru Central Kitchen", "state_rid": st["KA"], "city": "Bengaluru", "pincode": "560001"}),
    }
    for e, ls in {"HVH": ["CHN", "MDU", "OOT"], "HVR": ["OOT", "KOD"], "HVF": ["BLR", "CHN"]}.items():
        for lc in ls:
            _mk(ctx, "entity-locations", {"legal_entity_rid": ents[e], "location_rid": locs[lc]})

    # ---- departments, linked to the entities that use them
    deps = {c: _mk(ctx, "departments", {"code": c, "name": n}) for c, n in
            [("FO", "Front Office"), ("HK", "Housekeeping"), ("FB", "Food and Beverage"), ("KIT", "Kitchen"), ("ENG", "Engineering"),
             ("HR", "Human Resources"), ("FIN", "Finance")]}
    for e, ds in {"HVH": list(deps), "HVR": ["FO", "HK", "FB", "KIT", "ENG"], "HVF": ["KIT", "FIN", "HR"]}.items():
        for d in ds:
            _mk(ctx, "department-entities", {"department_rid": deps[d], "legal_entity_rid": ents[e]})
    desg = {c: _mk(ctx, "designations", {"code": c, "title": t, "job_family": f}) for c, t, f in
            [("GM", "General Manager", "Management"), ("FOM", "Front Office Manager", "Front Office"), ("FOE", "Front Office Executive", "Front Office"),
             ("HKS", "Housekeeping Supervisor", "Housekeeping"), ("RA", "Room Attendant", "Housekeeping"), ("STW", "Steward", "F&B"),
             ("CDP", "Chef de Partie", "Kitchen"), ("CMS", "Commis", "Kitchen"), ("TEC", "Technician", "Engineering"),
             ("HRE", "HR Executive", "HR"), ("ACC", "Accountant", "Finance")]}
    for e in ents:
        _mk(ctx, "cost-centres", {"code": f"{e}-OPS", "name": f"{e} operations", "legal_entity_rid": ents[e]})

    # ---- HR lookups
    grades = {c: _mk(ctx, "grades", {"code": c, "name": n, "level": lv, "pay_min": lo, "pay_max": hi}) for c, n, lv, lo, hi in
              [("G1", "Staff", 1, 12000, 22000), ("G2", "Senior staff", 2, 20000, 35000), ("G3", "Supervisor", 3, 30000, 55000),
               ("G4", "Manager", 4, 50000, 120000)]}
    lts = [_mk(ctx, "leave-types", {"code": c, "name": n, "paid": p, "accrual_days_per_year": d, "accrual_frequency": f}) for c, n, p, d, f in
           [("CL", "Casual leave", True, 12, "monthly"), ("SL", "Sick leave", True, 12, "monthly"), ("EL", "Earned leave", True, 15, "monthly"),
            ("LOP", "Loss of pay", False, 0, "none")]]
    etypes = {
        "PERM": _mk(ctx, "employment-types", {"code": "PERM", "name": "Permanent", "statutory_types": ["PF", "ESI", "PT"], "leave_type_rids": lts}),
        "TRN": _mk(ctx, "employment-types", {"code": "TRN", "name": "Trainee", "statutory_types": ["PT"], "leave_type_rids": lts[:2] + lts[3:]}),
        "CON": _mk(ctx, "employment-types", {"code": "CON", "name": "Contract", "statutory_types": [], "leave_type_rids": [lts[3]]}),
    }
    shifts = {c: _mk(ctx, "shifts", {"code": c, "name": n, "start_time": s, "end_time": e, "break_minutes": 30, "grace_minutes": 10,
                                     "half_day_minutes": 240}) for c, n, s, e in
              [("GEN", "General", "09:00", "18:00"), ("MOR", "Morning", "06:00", "14:00"), ("EVE", "Evening", "14:00", "22:00"),
               ("NGT", "Night", "22:00", "06:00")]}
    woffs = {"SUN": _mk(ctx, "weekly-offs", {"code": "SUN", "name": "Sunday off", "days_off": ["sunday"]}),
             "ROT": _mk(ctx, "weekly-offs", {"code": "ROT", "name": "Rotating (roster)", "days_off": ["tuesday"], "rotation": {"cycle_weeks": 4}})}

    # ---- statutory: HVF is deliberately NOT registered for PF/ESI (design test client C)
    for e in ("HVH", "HVR"):
        _mk(ctx, "statutory-registrations", {"legal_entity_rid": ents[e], "type": "PF", "number": f"TN/MAS/00{random.Random(e).randint(10000, 99999)}"})
        _mk(ctx, "statutory-registrations", {"legal_entity_rid": ents[e], "type": "ESI", "number": f"5100{random.Random(e + 'esi').randint(10**11, 10**12 - 1)}"})
        _mk(ctx, "statutory-registrations", {"legal_entity_rid": ents[e], "type": "PT", "state_rid": st["TN"], "number": f"PT-TN-{e}-001"})
    _mk(ctx, "statutory-registrations", {"legal_entity_rid": ents["HVF"], "type": "PT", "state_rid": st["KA"], "number": "PT-KA-HVF-001"})

    # ---- holiday calendars per state, per year
    for yr in (2026, 2027):
        common = [(f"{yr}-01-26", "Republic Day"), (f"{yr}-05-01", "May Day"), (f"{yr}-08-15", "Independence Day"), (f"{yr}-10-02", "Gandhi Jayanti")]
        tn = common + [(f"{yr}-01-15", "Pongal"), (f"{yr}-04-14", "Tamil New Year")]
        ka = common + [(f"{yr}-11-01", "Kannada Rajyotsava")]
        _mk(ctx, "holiday-calendars", {"code": f"TN-{yr}", "name": f"Tamil Nadu {yr}", "year": yr, "location_rids": [locs[x] for x in ("CHN", "OOT", "MDU", "KOD")],
                                       "holidays": [{"date": d, "name": n, "kind": "fixed"} for d, n in sorted(tn)]}, date(yr, 1, 1))
        _mk(ctx, "holiday-calendars", {"code": f"KA-{yr}", "name": f"Karnataka {yr}", "year": yr, "location_rids": [locs["BLR"]],
                                       "holidays": [{"date": d, "name": n, "kind": "fixed"} for d, n in sorted(ka)]}, date(yr, 1, 1))
    for lc in locs:
        _mk(ctx, "biometric-devices", {"code": f"BIO-{lc}", "make": "DemoMake", "model": "X100", "location_rid": locs[lc], "connection": "file"})
    for e in ents:
        for per, cut, pay in (("2026-11", date(2026, 11, 25), date(2026, 11, 30)), ("2026-12", date(2026, 12, 26), date(2026, 12, 31))):
            _mk(ctx, "payroll-calendars", {"legal_entity_rid": ents[e], "period": per, "attendance_cutoff": cut, "pay_date": pay})
        _mk(ctx, "bank-accounts", {"legal_entity_rid": ents[e], "bank_name": "Demo Bank", "branch": "Main", "ifsc": "DEMO0001234",
                                   "account_number": f"9000{random.Random(e + 'acc').randint(10**7, 10**8 - 1)}", "purpose": "salary"})
        _mk(ctx, "number-series", {"code": f"EMP-{e}", "object": "employee", "legal_entity_rid": ents[e], "prefix": f"{e}-", "padding": 4, "start_number": 1})
    _mk(ctx, "number-series", {"code": "DOC", "object": "document", "prefix": "DOC-", "padding": 6, "start_number": 1})
    _mk(ctx, "policies", {"code": "ATT-STD", "name": "Standard attendance policy", "applies_to": {},
                          "settings": {"late_marks_per_half_day": 3, "overtime_after_minutes": 60}})
    _mk(ctx, "policies", {"code": "ATT-RES", "name": "Resort attendance policy", "applies_to": {"legal_entity_rids": [ents["HVR"]]},
                          "settings": {"late_marks_per_half_day": 4, "overtime_after_minutes": 30}})
    db.flush()

    # ---- people, through the same onboarding the API uses
    rnd = random.Random(2026)
    first = ["Arun", "Divya", "Karthik", "Meena", "Suresh", "Priya", "Vignesh", "Lakshmi", "Ravi", "Anitha", "Ganesh", "Kavya", "Manoj", "Revathi",
             "Senthil", "Deepa", "Prakash", "Nandhini", "Hari", "Swathi", "Ramesh", "Bhavana", "Ashok", "Pooja"]
    last = ["Kumar", "Raman", "Subramani", "Natarajan", "Iyer", "Pillai", "Gowda", "Shetty", "Murugan", "Selvam"]
    plan = [  # (entity, location, department, designation, grade)
        ("HVH", "CHN", "HR", "GM", "G4"), ("HVH", "CHN", "HR", "HRE", "G2"), ("HVH", "CHN", "FIN", "ACC", "G2"),
        ("HVH", "CHN", "FO", "FOM", "G4"), ("HVR", "OOT", "FO", "FOM", "G4"), ("HVF", "BLR", "KIT", "CDP", "G3"),
    ] + [(e, lc, d, ds, g) for e, lc, d, ds, g in
         [("HVH", "CHN", "FO", "FOE", "G1"), ("HVH", "CHN", "HK", "RA", "G1"), ("HVH", "MDU", "HK", "HKS", "G3"), ("HVH", "MDU", "FB", "STW", "G1"),
          ("HVR", "OOT", "HK", "RA", "G1"), ("HVR", "OOT", "KIT", "CMS", "G1"), ("HVR", "KOD", "FO", "FOE", "G1"), ("HVR", "KOD", "ENG", "TEC", "G2"),
          ("HVF", "BLR", "KIT", "CMS", "G1"), ("HVF", "CHN", "KIT", "CMS", "G1")] for _ in range(2)]
    persons: list[int] = []
    managers = {"HVH": None, "HVR": None, "HVF": None}
    for i, (e, lc, d, ds, g) in enumerate(plan):
        fn, ln = first[i % len(first)], last[(i * 3) % len(last)]
        joined = D0 if i < 6 else D0 + timedelta(days=23 * i)
        mgr = managers[e] if i >= 6 else (persons[0] if i else None)
        body = onboarding.OnboardIn(
            person={"first_name": fn, "last_name": ln, "date_of_birth": date(1980 + i % 20, 1 + i % 12, 1 + (i * 7) % 28).isoformat(),
                    "gender": "female" if i % 2 else "male", "phone": f"+91 90000 {10000 + i:05d}", "email": f"{fn.lower()}.{ln.lower()}{i}@example.com",
                    "pan": f"ABCP{chr(65 + i % 26)}{1000 + i:04d}{chr(70 + i % 20)}"},
            assignments=[onboarding.AssignmentIn(legal_entity_rid=ents[e], location_rid=locs[lc], department_rid=deps[d], designation_rid=desg[ds],
                                                 grade_rid=grades[g], employment_type_rid=etypes["PERM" if i % 7 else "TRN"],
                                                 shift_rid=shifts[rnd.choice(["GEN", "MOR", "EVE"]) if d not in ("HR", "FIN") else "GEN"],
                                                 weekly_off_rid=woffs["SUN" if d in ("HR", "FIN") else "ROT"], valid_from=joined, reports_to_person_rid=mgr)],
            change_reason="Demo data")
        out = onboarding.onboard(ctx, body)
        persons.append(out["person_rid"])
        if i in (3, 4, 5):
            managers[{3: "HVH", 4: "HVR", 5: "HVF"}[i]] = out["person_rid"]

    # one person, two jobs: 60% at the Chennai hotel (HVH), 40% at the Ooty resort (HVR) - split pay
    split = onboarding.OnboardIn(
        person={"first_name": "Selvi", "last_name": "Arumugam", "date_of_birth": "1990-06-12", "gender": "female", "phone": "+91 90000 29999"},
        assignments=[
            onboarding.AssignmentIn(legal_entity_rid=ents["HVH"], location_rid=locs["CHN"], department_rid=deps["FB"], designation_rid=desg["STW"],
                                    grade_rid=grades["G2"], employment_type_rid=etypes["PERM"], pay_share=60, is_primary=True, valid_from=date(2025, 4, 1),
                                    reports_to_person_rid=managers["HVH"]),
            onboarding.AssignmentIn(legal_entity_rid=ents["HVR"], location_rid=locs["OOT"], department_rid=deps["FB"], designation_rid=desg["STW"],
                                    grade_rid=grades["G2"], employment_type_rid=etypes["PERM"], pay_share=40, valid_from=date(2025, 4, 1),
                                    reports_to_person_rid=managers["HVR"])],
        change_reason="Demo data: split pay")
    persons.append(onboarding.onboard(ctx, split)["person_rid"])
    db.flush()

    # ---- demo logins (laptops only; password from DEMO_PASSWORD, no change at first sign-in)
    pw = get_settings().demo_password
    idp = get_identity()
    logins = [("admin@hotelvivek.local", "Demo Admin", ["master_admin"], persons[0], {}),
              ("hr@hotelvivek.local", "Demo HR", ["hr"], persons[1], {}),
              ("hr.ooty@hotelvivek.local", "Demo HR Ooty", ["hr"], None, {"scope_location_rids": [locs["OOT"]]}),
              ("payroll@hotelvivek.local", "Demo Payroll", ["payroll_preparer"], persons[2], {}),
              ("finance@hotelvivek.local", "Demo Finance", ["finance_approver"], None, {}),
              ("hod@hotelvivek.local", "Demo Head of Front Office", ["hod"], persons[3], {}),
              ("employee@hotelvivek.local", "Demo Employee", ["employee"], persons[6], {})]
    for email, name, roles, prid, scope in logins:
        if db.scalar(select(m.AppUser.id).where(m.AppUser.email == email)):
            continue
        u, _ = users.create_user(ctx, email, name, roles, prid, scope)
        idp.set_permanent_password(db, u, pw)
    print(f"Demo data: 3 entities, 5 locations, {len(persons)} people, {len(logins)} logins (password: DEMO_PASSWORD).", flush=True)
