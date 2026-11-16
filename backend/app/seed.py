"""Demo data: synthetic only (no real Hotel Vivek data). Safe to run more than once: it does nothing
if entities already exist.

    python -m app.seed            # seed if empty
    python -m app.seed --punches  # also (re)generate punches for last month and this month
"""
from __future__ import annotations

import random
import sys
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select

from . import models as m
from .config import get_settings
from .db import SessionLocal
from .domain.payroll_engine import DEFAULT_RULES
from .services.employees import create_employee
from .services.identity import get_identity
from .services.provisioning import queue

settings = get_settings()
rnd = random.Random(20261120)

ENTITIES = [("VHPL", "Vivek Hotels Pvt Ltd (Demo)"), ("VRL", "Vivek Resorts LLP (Demo)"), ("VFS", "Vivek Foods & Services Pvt Ltd (Demo)")]
LOCATIONS = [("OOT", "Ooty", "VHPL", 70), ("CNR", "Coonoor", "VHPL", 50), ("KTG", "Kotagiri", "VRL", 50), ("MTP", "Mettupalayam", "VRL", 40),
             ("CBE", "Coimbatore", "VFS", 46)]
DEPTS = ["Front Office", "Housekeeping", "F&B Service", "Kitchen", "Engineering", "Security", "Accounts", "HR & Admin", "Laundry"]
DESIGS = {"Front Office": ["Front Office Associate", "Front Office Supervisor"], "Housekeeping": ["Room Attendant", "Floor Supervisor"],
          "F&B Service": ["Steward", "Captain"], "Kitchen": ["Commis", "Chef de Partie"], "Engineering": ["Technician", "Shift Engineer"],
          "Security": ["Security Guard", "Security Supervisor"], "Accounts": ["Accounts Associate", "Accountant"], "HR & Admin": ["HR Associate", "HR Executive"],
          "Laundry": ["Laundry Attendant", "Laundry Supervisor"]}
GRADES = [("G1", "Trainee / Attendant", 13000, 15500, 30), ("G2", "Associate", 15000, 19500, 30), ("G3", "Senior Associate", 18500, 24500, 30),
          ("G4", "Supervisor", 23000, 32000, 30), ("G5", "Executive", 32000, 45000, 60), ("M1", "Manager / HOD", 45000, 75000, 90)]
SHIFTS = [("A", "Morning", "07:00", "15:00", 30, False, False), ("B", "Evening", "15:00", "23:00", 30, False, False),
          ("N", "Night", "23:00", "07:00", 30, False, True), ("G", "General", "09:00", "18:00", 60, False, False), ("OFF", "Weekly off", "00:00", "00:00", 0, True, False)]
HOLIDAYS = [("2026-01-01", "New Year's Day"), ("2026-01-15", "Pongal"), ("2026-01-26", "Republic Day"), ("2026-04-14", "Tamil New Year"),
            ("2026-05-01", "May Day"), ("2026-08-15", "Independence Day"), ("2026-10-02", "Gandhi Jayanti"), ("2026-11-08", "Deepavali"),
            ("2026-12-25", "Christmas"), ("2027-01-01", "New Year's Day"), ("2027-01-15", "Pongal"), ("2027-01-26", "Republic Day")]
LEAVE_TYPES = [("CL", "Casual leave", 12, True), ("SL", "Sick leave", 12, True), ("EL", "Earned leave", 15, True), ("LWP", "Leave without pay", 0, False)]
FIRST = ["Selvi", "Senthil", "Meena", "Arun", "Ravi", "Lakshmi", "Muthu", "Imran", "Kavitha", "Karthik", "Priya", "Vignesh", "Divya", "Suresh", "Anitha",
         "Prakash", "Revathi", "Dinesh", "Sangeetha", "Manoj", "Deepa", "Bala", "Janani", "Ganesh", "Saranya", "Rajesh", "Pooja", "Saravanan", "Mary", "Joseph"]
INITIAL = list("KMSRPLDAVNTGJB")
DEMO_USERS = [("admin@hotelvivek.local", "Master Admin", ["master_admin"], None), ("hr@hotelvivek.local", "HR Manager", ["hr"], None),
              ("payroll@hotelvivek.local", "Payroll Preparer", ["payroll_preparer"], None), ("finance@hotelvivek.local", "Finance Approver", ["finance_approver"], None),
              ("hod@hotelvivek.local", "Housekeeping HOD", ["hod"], "HOD"), ("employee@hotelvivek.local", "Employee", ["employee"], "EMP")]


def seed_org(db) -> None:
    ents = {}
    for code, name in ENTITIES:
        e = m.Entity(code=code, name=name, state="Tamil Nadu", pf_code=f"TN/CBE/DEMO/{code}", esi_code=f"56DEMO{code}", tally_company=name,
                     statutory={"PF": True, "ESI": True, "PT": True, "LWF": True, "TDS": True})
        db.add(e)
        db.flush()
        ents[code] = e.id
    for code, name, ent, _ in LOCATIONS:
        db.add(m.Location(code=code, name=name, entity_id=ents[ent], weekly_off=rnd.choice([6, 6, 0])))
    for d in DEPTS:
        db.add(m.Department(name=d))
    for ds in sorted({x for v in DESIGS.values() for x in v} | {"Executive Housekeeper"}):
        db.add(m.Designation(name=ds))
    for code, name, lo, hi, notice in GRADES:
        db.add(m.Grade(code=code, name=name, min_gross=lo, max_gross=hi, notice_days=notice))
    for code, name, s, e, br, off, night in SHIFTS:
        db.add(m.Shift(code=code, name=name, start_time=s, end_time=e, break_minutes=br, is_off=off, is_night=night))
    for d, n in HOLIDAYS:
        db.add(m.Holiday(day=date.fromisoformat(d), name=n))
    for code, name, q, paid in LEAVE_TYPES:
        db.add(m.LeaveType(code=code, name=name, annual_quota=q, paid=paid))
    db.add(m.StatutoryRuleVersion(rules=DEFAULT_RULES, effective_from=date(2026, 4, 1), note="Sample rules — confirm with consultant (SCRUM-119)", created_by="seed"))
    for key, value in (("payroll_day", 26), ("attendance_cutoff_day", 25)):
        db.add(m.PolicyVersion(key=key, value=value, effective_from=date(2026, 4, 1), note="Sample — confirm with Gerald", created_by="seed"))
    db.flush()


def seed_employees(db, count: int) -> dict[str, int]:
    locs = {x.code: x for x in db.scalars(select(m.Location))}
    ents = {x.code: x.id for x in db.scalars(select(m.Entity))}
    grades = {g.code: g for g in db.scalars(select(m.Grade))}
    scale = count / sum(x[3] for x in LOCATIONS)
    n, special = 0, {}
    hods: dict[tuple[str, str], int] = {}
    for code, _, ent, headcount in LOCATIONS:
        for i in range(max(1, round(headcount * scale))):
            n += 1
            dept = rnd.choice(DEPTS[:6] if code != "CBE" else ["Kitchen", "Laundry", "Engineering", "Security", "Accounts", "HR & Admin"])
            hod_key = (code, dept)
            is_hod = hod_key not in hods
            grade = "M1" if is_hod else rnd.choice(["G1", "G1", "G2", "G2", "G2", "G3", "G3", "G4", "G5"])
            g = grades[grade]
            gross = Decimal(rnd.randrange(int(g.min_gross), int(g.max_gross), 100))
            first = rnd.choice(FIRST)
            emp_code = f"HV{n:04d}"
            if n == 1:  # Selvi: the demo employee user
                first, dept, grade, gross, is_hod = "Selvi", "Housekeeping", "G2", Decimal(16800), False
            data = {
                "code": emp_code, "first_name": first, "last_name": rnd.choice(INITIAL), "gender": rnd.choice(["F", "M"]),
                "dob": date(rnd.randint(1972, 2004), rnd.randint(1, 12), rnd.randint(1, 28)),
                "doj": date(rnd.randint(2015, 2026), rnd.randint(1, 9), rnd.randint(1, 28)), "location_id": locs[code].id,
                "department": dept, "designation": "Executive Housekeeper" if (is_hod and dept == "Housekeeping") else DESIGS[dept][1 if is_hod or grade in ("G4", "G5") else 0],
                "grade": grade, "phone": f"+9190000{n:05d}", "language": rnd.choice(["ta"] * 8 + ["en", "hi"]),
                "pan": f"ABCDE{1000 + n:04d}F", "aadhaar": f"{rnd.randint(10**11, 10**12 - 1)}",
                "bank_account": None if n in (7, 112) else str(rnd.randint(10**9, 10**10 - 1)), "ifsc": "SBIN0001234", "bank_name": "State Bank of India",
                "uan": f"1009{n:08d}", "esic_no": f"560{n:07d}" if gross <= 21000 else None, "monthly_gross": gross,
                "shift": "G" if dept in ("Accounts", "HR & Admin") else rnd.choice(["A", "A", "B", "B", "N", "G"]),
            }
            e = create_employee(db, data, "seed")
            if is_hod:
                hods[hod_key] = e.id
            else:
                e.manager_id = hods.get(hod_key)
            if n == 1:
                special["EMP"] = e.id
            if dept == "Housekeeping" and code == "OOT" and is_hod:
                special["HOD"] = e.id
            if n in (5, 9, 60) and ent != "VFS":  # split salaries across entities
                for a in db.scalars(select(m.EntityAllocation).where(m.EntityAllocation.employee_id == e.id)):
                    a.value = Decimal(60 if n != 60 else 70)
                db.add(m.EntityAllocation(employee_id=e.id, entity_id=ents["VFS"], effective_from=e.doj, method="percent",
                                          value=Decimal(40 if n != 60 else 30), is_primary=False))
            if rnd.random() < 0.25:
                db.add(m.EmployeeDocument(employee_id=e.id, doc_type=rnd.choice(["Food handler medical certificate", "Police verification", "Fixed-term contract"]),
                                          expiry_date=date.today() + timedelta(days=rnd.randint(-10, 200))))
    db.flush()
    selvi = db.get(m.Employee, special.get("EMP"))
    if selvi and special.get("HOD"):
        selvi.manager_id = special["HOD"]
    return special


def seed_punches(db, months: tuple[tuple[int, int], ...]) -> int:
    """Synthetic punches incl. night shifts across midnight, late arrivals, some missed punches and OT."""
    shifts = {s.code: s for s in db.scalars(select(m.Shift))}
    locs = {x.id: x for x in db.scalars(select(m.Location))}
    n = 0
    for e in db.scalars(select(m.Employee).where(m.Employee.status != "exited")):
        sh = shifts.get(e.shift_code) or shifts["G"]
        for y, mo in months:
            d = date(y, mo, 1)
            while d.month == mo and d <= date.today():
                if d < e.doj or d.weekday() == locs[e.location_id].weekly_off or rnd.random() < 0.04:
                    d += timedelta(days=1)
                    continue
                start = datetime.combine(d, time.fromisoformat(sh.start_time)) + timedelta(minutes=rnd.choice([-12, -8, -5, -3, 0, 2, 6, 25]))
                end_t = datetime.combine(d, time.fromisoformat(sh.end_time))
                if end_t <= datetime.combine(d, time.fromisoformat(sh.start_time)):
                    end_t += timedelta(days=1)
                end = end_t + timedelta(minutes=rnd.choice([0, 3, 7, 12, 40, 95]))
                pts = [start] if rnd.random() < 0.02 else [start, end]  # ~2% missed punches
                for p in pts:
                    if not db.scalar(select(m.Punch.id).where(m.Punch.employee_id == e.id, m.Punch.punched_at == p)):
                        db.add(m.Punch(employee_id=e.id, punched_at=p, device_id=f"{locs[e.location_id].code}-1", source="excel"))
                        n += 1
                d += timedelta(days=1)
    db.flush()
    return n


def seed_users(db, special: dict[str, int]) -> list[tuple[str, str]]:
    idp = get_identity()
    idp.bootstrap(db)
    out = []
    for email, name, roles, link in DEMO_USERS:
        if db.scalar(select(m.AppUser.id).where(m.AppUser.email == email)):
            continue
        u = m.AppUser(email=email, display_name=name, roles=roles, employee_id=special.get(link) if link else None)
        db.add(u)
        db.flush()
        task = queue(db, target="identity", action="create", user_id=u.id, temp_password=settings.demo_password, actor="seed")
        # demo users: accept the demo password as permanent so the walkthrough needs no password change
        u.must_change_password = False
        if task.status == "done" and settings.auth_mode == "cognito":
            from .services.identity import CognitoIdentity

            if isinstance(idp, CognitoIdentity):
                pool, _ = idp.ids(db)
                try:
                    idp.client.admin_set_user_password(UserPoolId=pool, Username=email, Password=settings.demo_password, Permanent=True)
                except Exception:  # noqa: BLE001 - cognito-local may not support it; then first sign-in asks for a new password
                    u.must_change_password = True
        out.append((email, task.status))
    return out


def run(with_punches: bool = False) -> None:
    with SessionLocal() as db:
        if db.scalar(select(m.Entity.id)):
            print("Seed: data already present.")
            if with_punches:
                today = date.today()
                prev = (today.replace(day=1) - timedelta(days=1))
                print("Punches added:", seed_punches(db, ((prev.year, prev.month), (today.year, today.month))))
                db.commit()
            return
        seed_org(db)
        special = seed_employees(db, settings.demo_employee_count)
        today = date.today()
        prev = today.replace(day=1) - timedelta(days=1)
        punches = seed_punches(db, ((prev.year, prev.month), (today.year, today.month)))
        users = seed_users(db, special)
        db.commit()
        print(f"Seed: {settings.demo_employee_count} employees, {punches} punches, users: {users}")
        print(f"Demo sign-in: admin@hotelvivek.local / {settings.demo_password} (also hr@, payroll@, finance@, hod@, employee@)")


if __name__ == "__main__":
    run(with_punches="--punches" in sys.argv)
