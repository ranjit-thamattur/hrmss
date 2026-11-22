"""Employee master import (PEAKHRMS-125, PEAKHRMS-42): people and their jobs from one Excel / CSV sheet.

One row = one job. Rows with the same `person_ref` are one person with several jobs (e.g. 60/40 across two
entities); without `person_ref` every row is a new person. Each person goes through the same onboarding as
POST /api/employee/add, so every rule applies; a person is imported whole or not at all.

Column mapping: the client's own headers can be mapped to ours, e.g. {"Emp Name": "first_name", "DOJ": "joining_date"}.
CSV is accepted, so a Google Sheet can be imported with File > Download > CSV.

The report always reconciles: rows imported + rows rejected = rows in the file.
"""
from __future__ import annotations

import io
import json
from collections import OrderedDict
from datetime import date
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from .. import models as m
from ..core import access
from ..core.context import Ctx, current
from ..core.importer import _by_code, _date
from . import onboarding

PERSON_COLS = ["first_name", "middle_name", "last_name", "preferred_name", "date_of_birth", "gender", "email", "phone", "address",
               "language", "pan", "aadhaar", "emergency_contact"]
JOB_REFS = {  # column -> (assignment field, catalogue entity looked up by code)
    "legal_entity_code": ("legal_entity_rid", "legal-entities"),
    "location_code": ("location_rid", "locations"),
    "department_code": ("department_rid", "departments"),
    "designation_code": ("designation_rid", "designations"),
    "grade_code": ("grade_rid", "grades"),
    "employment_type_code": ("employment_type_rid", "employment-types"),
    "cost_centre_code": ("cost_centre_rid", "cost-centres"),
    "shift_code": ("shift_rid", "shifts"),
    "weekly_off_code": ("weekly_off_rid", "weekly-offs"),
}
REQUIRED_JOB = ["legal_entity_code", "location_code", "department_code", "designation_code"]
OTHER_COLS = ["pay_share", "is_primary", "joining_date", "reports_to_employee_number", "login_email", "login_roles"]
COLUMNS = ["person_ref", *PERSON_COLS, *JOB_REFS, *OTHER_COLS]

HELP = {
    "person_ref": "Same value on several rows = one person with several jobs. Empty = a new person per row",
    "first_name": "Required", "date_of_birth": "YYYY-MM-DD (or DD-MM-YYYY)", "gender": "male / female / other",
    "pan": "Kept encrypted; shown masked", "aadhaar": "Kept encrypted; shown masked",
    "legal_entity_code": "Required. Code of the legal entity", "location_code": "Required. The entity must work at this location",
    "department_code": "Required. Must belong to the legal entity", "designation_code": "Required",
    "pay_share": "Percent of pay for this job (default 100). A person's jobs add up to 100 at most",
    "is_primary": "yes / no. One primary job per person (default: the first row)",
    "joining_date": "YYYY-MM-DD. Start of this job (default today)",
    "reports_to_employee_number": "Line manager's employee number (already in the system, or on an earlier row)",
    "login_email": "Gives the person a login (one per person). Not created on a dry run",
    "login_roles": "Roles separated by ; (default employee)",
}


def template(client: m.Client | None) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    required = set(onboarding.required_person_fields(client)) | set(REQUIRED_JOB)
    wb = Workbook()
    ws = wb.active
    ws.title = "Employees"
    ws.append(COLUMNS)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF", name="Arial")
        c.fill = PatternFill("solid", start_color="0F766E" if c.value in required else "64748B")
        ws.column_dimensions[c.column_letter].width = max(14, len(str(c.value)) + 4)
    how = wb.create_sheet("How to")
    how.append(["Column", "Required", "What to enter"])
    for c in how[1]:
        c.font = Font(bold=True, name="Arial")
    for col in COLUMNS:
        how.append([col, "yes" if col in required else "", HELP.get(col, "Text")])
    how.append([])
    how.append(["One row per job. Dark green headers are required for this client. Codes must exist in Company Setup."])
    how.append(["Your own column names can be used: send a mapping, e.g. {\"Emp Name\": \"first_name\"}."])
    how.column_dimensions["A"].width = 28
    how.column_dimensions["C"].width = 80
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _mapping(raw: str | dict | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        mp = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError as e:
        raise HTTPException(422, f"mapping is not valid JSON: {e}") from e
    if not isinstance(mp, dict):
        raise HTTPException(422, "mapping must be a JSON object: {\"their column\": \"our column\"}.")
    bad = sorted(v for v in mp.values() if v not in COLUMNS)
    if bad:
        raise HTTPException(422, f"mapping points to unknown columns: {', '.join(bad)}. Known: {', '.join(COLUMNS)}.")
    return {str(k).strip().lower(): str(v) for k, v in mp.items()}


def _text(v: Any) -> str | None:
    if v is None or str(v).strip() == "":
        return None
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _manager(ctx: Ctx, number: str, on: date) -> int | None:
    ea = m.EmploymentAssignment
    return ctx.db.scalar(select(ea.person_rid).where(ea.client_id == ctx.client_id, ea.employee_number == number, current(ea, on),
                                                     ea.is_active.is_(True)).limit(1))


def _job(ctx: Ctx, raw: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    start = None
    try:
        start = _date(raw.get("joining_date"))
    except ValueError as e:
        errors.append(f"joining_date: {e}")
    on = start or ctx.today
    job: dict[str, Any] = {"valid_from": start}
    for col, (field, key) in JOB_REFS.items():
        code = _text(raw.get(col))
        if code is None:
            if col in REQUIRED_JOB:
                errors.append(f"{col} is required")
            continue
        rid = _by_code(ctx, key, code, on)
        if rid is None:
            errors.append(f"{col}: '{code}' not found or not active on {on}")
        job[field] = rid
    if _text(raw.get("pay_share")) is not None:
        job["pay_share"] = _text(raw.get("pay_share"))
    if _text(raw.get("is_primary")) is not None:
        job["is_primary"] = str(raw["is_primary"]).strip().lower() in ("yes", "y", "true", "1")
    mgr = _text(raw.get("reports_to_employee_number"))
    if mgr:
        rid = _manager(ctx, mgr, on)
        if rid is None:
            errors.append(f"reports_to_employee_number: '{mgr}' not found (must be in the system or on an earlier row)")
        job["reports_to_person_rid"] = rid
    return job


def _person(raw: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    p: dict[str, Any] = {}
    for col in PERSON_COLS:
        v = raw.get(col)
        if col == "date_of_birth" and v not in (None, ""):
            try:
                v = _date(v).isoformat()
            except ValueError as e:
                errors.append(f"date_of_birth: {e}")
                continue
        t = _text(v) if col != "date_of_birth" else v
        if t not in (None, ""):
            p[col] = t
    return p


def import_file(ctx: Ctx, content: bytes, dry_run: bool, mapping: str | dict | None = None) -> dict[str, Any]:
    """Import people + jobs. The caller commits, or rolls back on a dry run."""
    from ..rules.imports import read_sheet

    access.require(ctx, "persons", "import")
    access.require(ctx, "employment-assignments", "import")
    mp = _mapping(mapping)
    try:
        headers, rows = read_sheet(content)
    except Exception as e:  # noqa: BLE001 - any unreadable file
        raise HTTPException(422, f"Could not read the file: {e}") from e
    norm = []
    for h in headers:
        k = str(h).strip().lower() if h is not None else ""
        norm.append(mp.get(k, k))
    required = ["first_name", *REQUIRED_JOB]
    report: dict[str, Any] = {"dry_run": dry_run, "total": 0, "imported": 0, "rejected": 0, "people_imported": 0, "people": [],
                              "rejected_rows": [], "missing_columns": [c for c in required if c not in norm],
                              "unknown_columns": [h for h in norm if h and h not in COLUMNS]}
    if report["missing_columns"]:
        raise HTTPException(422, {"message": f"Missing required columns: {', '.join(report['missing_columns'])}", **report})

    groups: OrderedDict[str, list[tuple[int, dict[str, Any]]]] = OrderedDict()
    for n, r in enumerate(rows, start=2):
        if all(v in (None, "") for v in r):
            continue
        raw = {norm[i]: r[i] for i in range(min(len(norm), len(r))) if norm[i]}
        report["total"] += 1
        ref = _text(raw.get("person_ref"))
        groups.setdefault(f"ref:{ref.lower()}" if ref else f"row:{n}", []).append((n, raw))

    for _, items in groups.items():
        row_nos = [n for n, _ in items]
        errors: list[str] = []
        first = items[0][1]
        person = _person(first, errors)
        jobs = [_job(ctx, raw, errors) for _, raw in items]
        login_email = next((_text(raw.get("login_email")) for _, raw in items if _text(raw.get("login_email"))), None)
        roles = next((_text(raw.get("login_roles")) for _, raw in items if _text(raw.get("login_roles"))), None)
        body = None
        if not errors:
            try:
                login = None
                if login_email and not dry_run:  # never create real sign-ins on a dry run
                    login = {"email": login_email, "roles": [x.strip() for x in (roles or "employee").split(";") if x.strip()]}
                body = onboarding.OnboardIn(person=person, assignments=[{k: v for k, v in j.items() if v is not None} for j in jobs],
                                            login=login, change_reason="Employee master import")
            except ValidationError as e:
                errors += [f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()]
        out = None
        if not errors and body is not None:
            sp = ctx.db.begin_nested()
            try:
                out = onboarding.onboard(ctx, body)
                sp.commit()
            except HTTPException as e:
                sp.rollback()
                errors.append(e.detail if isinstance(e.detail, str) else json.dumps(e.detail))
            except ValidationError as e:
                sp.rollback()
                errors += [f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()]
        name = " ".join(x for x in (person.get("first_name"), person.get("last_name")) if x)
        if errors or out is None:
            report["rejected"] += len(items)
            report["rejected_rows"].append({"rows": row_nos, "person": name, "errors": errors})
        else:
            report["imported"] += len(items)
            report["people_imported"] += 1
            entry = {"rows": row_nos, "person": name, "person_rid": out["person_rid"],
                     "employee_numbers": [a["employee_number"] for a in out["assignments"]]}
            if out.get("login"):
                entry["login"] = {"email": out["login"]["email"], "temporary_password": out["login"]["temporary_password"]}
            elif login_email and dry_run:
                entry["login"] = {"email": login_email, "note": "would be created (not on a dry run)"}
            report["people"].append(entry)
    report["counts_reconcile"] = report["imported"] + report["rejected"] == report["total"]
    return report
