"""Excel / CSV imports. Every import is logged (who, when, file, counts) and gives a rejected-row report.
dry_run=true checks the file without saving anything."""
from __future__ import annotations

import csv
import io
from decimal import Decimal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from sqlalchemy import select

from .. import models as m
from ..deps import DB, User
from ..domain.imports import parse_punches, read_sheet, to_decimal, validate_employees, validate_salary
from ..serial import row
from ..services.access import require
from ..services.audit import record
from ..services.employees import close_dated, create_employee

router = APIRouter(prefix="/api/imports", tags=["imports"])

INPUT_CODES = ["SERVICE_CHARGE", "INCENTIVE", "ARREAR", "BONUS", "OTHER_EARNING", "ADVANCE", "LOAN_EMI", "OTHER_DEDUCTION", "TDS_OVERRIDE"]


async def _read(file: UploadFile) -> tuple[list, list]:
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(413, "File larger than 20 MB")
    try:
        return read_sheet(content)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Could not read the file: {e}") from e


def _log(db: DB, user: User, kind: str, filename: str, report: dict, dry_run: bool) -> m.ImportBatch:
    b = m.ImportBatch(kind=kind, filename=filename, uploaded_by=user.email, total=report.get("total", 0), imported=report.get("imported", 0),
                      rejected=report.get("rejected", 0), dry_run=dry_run, report=report)
    db.add(b)
    db.flush()
    record(db, user.email, f"import_{kind}" + ("_check" if dry_run else ""), "import", b.id,
           after={"file": filename, "total": b.total, "imported": b.imported, "rejected": b.rejected})
    return b


@router.post("/employees")
async def import_employees(user: User, db: DB, file: UploadFile = File(...), dry_run: bool = Form(False)) -> dict:
    require(user, "employees.import")
    headers, rows = await _read(file)
    known = lambda model, f: {getattr(x, f) for x in db.scalars(select(model))}  # noqa: E731
    rep = validate_employees(headers, rows, entities=known(m.Entity, "code"), locations=known(m.Location, "code") | known(m.Location, "name"),
                             departments=known(m.Department, "name"), designations=known(m.Designation, "name") or None,
                             grades=known(m.Grade, "code") or None, existing_codes=known(m.Employee, "code"))
    report = rep.as_dict()
    if not dry_run and rep.missing_columns:
        raise HTTPException(400, f"Missing columns: {', '.join(rep.missing_columns)}")
    if not dry_run:
        loc_by_name = {x.name.upper(): x.code for x in db.scalars(select(m.Location))}
        for r in rep.valid:
            r["location"] = loc_by_name.get(str(r.get("location", "")).upper(), r.get("location"))
            r["source"] = "import"
            create_employee(db, r, user.email)
    b = _log(db, user, "employees", file.filename or "file", report, dry_run)
    db.commit()
    return {"batch_id": b.id, **report, "dry_run": dry_run}


@router.post("/salary")
async def import_salary(user: User, db: DB, file: UploadFile = File(...), dry_run: bool = Form(False)) -> dict:
    require(user, "employees.import")
    headers, rows = await _read(file)
    ids = {e.code: e.id for e in db.scalars(select(m.Employee))}
    rep = validate_salary(headers, rows, known_codes=set(ids))
    if not dry_run:
        for r in rep.valid:
            eid = ids[r["code"]]
            close_dated(db, m.SalaryStructure, eid, r["effective_from"])
            comps = {k: str(v) for k, v in r["components"].items()}
            db.add(m.SalaryStructure(employee_id=eid, effective_from=r["effective_from"], components=comps,
                                     monthly_gross=sum(r["components"].values(), Decimal(0)), source="import"))
            record(db, user.email, "salary_structure_import", "employee", eid, after={"effective_from": r["effective_from"], **comps}, employee_id=eid)
    report = rep.as_dict()
    b = _log(db, user, "salary", file.filename or "file", report, dry_run)
    db.commit()
    return {"batch_id": b.id, **report, "dry_run": dry_run}


@router.post("/punches")
async def import_punches(user: User, db: DB, file: UploadFile = File(...), dry_run: bool = Form(False)) -> dict:
    """Biometric Excel fallback: punches from the device export. Unknown employees are reported, not dropped silently."""
    require(user, "attendance.manage")
    headers, rows = await _read(file)
    res = parse_punches(headers, rows)
    ids = {e.code: e.id for e in db.scalars(select(m.Employee))}
    errors = list(res.errors)
    good = []
    for code, at, device in res.punches:
        if code not in ids:
            errors.append({"row": None, "code": code, "errors": [f"Unknown employee '{code}'"]})
        else:
            good.append((ids[code], at, device))
    added = dup = 0
    b = _log(db, user, "punches", file.filename or "file", {}, dry_run)
    if not dry_run:
        for eid, at, device in good:
            exists = db.scalar(select(m.Punch.id).where(m.Punch.employee_id == eid, m.Punch.punched_at == at))
            if exists:
                dup += 1
                continue
            db.add(m.Punch(employee_id=eid, punched_at=at, device_id=device or None, source="excel", batch_id=b.id))
            added += 1
    report = {"total": res.rows, "mode": res.mode, "punches_read": len(res.punches), "imported": added, "duplicates": dup,
              "rejected": len(errors), "rejected_rows": errors}
    b.total, b.imported, b.rejected, b.report = res.rows, added, len(errors), report
    db.commit()
    return {"batch_id": b.id, **report, "dry_run": dry_run}


@router.post("/inputs")
async def import_inputs(user: User, db: DB, period: str = Form(...), file: UploadFile = File(...), dry_run: bool = Form(False)) -> dict:
    """Monthly inputs sheet: Emp Code + one column per input code (SERVICE_CHARGE, INCENTIVE, …)."""
    require(user, "payroll.prepare")
    headers, rows = await _read(file)
    norm = [str(h or "").strip().upper().replace(" ", "_") for h in headers]
    if not norm or norm[0] not in ("EMP_CODE", "EMPLOYEE_CODE", "CODE"):
        raise HTTPException(400, "First column must be Emp Code")
    cols = {i: c for i, c in enumerate(norm) if c in INPUT_CODES}
    ids = {e.code: e.id for e in db.scalars(select(m.Employee))}
    errors, saved, total = [], 0, 0
    for idx, r in enumerate(rows, start=2):
        if not r or not str(r[0] or "").strip():
            continue
        total += 1
        code = str(r[0]).strip().upper()
        if code not in ids:
            errors.append({"row": idx, "code": code, "errors": ["Unknown employee"]})
            continue
        try:
            vals = {c: to_decimal(r[i]) for i, c in cols.items() if i < len(r)}
        except ValueError as e:
            errors.append({"row": idx, "code": code, "errors": [str(e)]})
            continue
        if not dry_run:
            for c, v in vals.items():
                existing = db.scalar(select(m.MonthlyInput).where(m.MonthlyInput.period == period, m.MonthlyInput.employee_id == ids[code], m.MonthlyInput.code == c))
                if v is None or v == 0:
                    if existing:
                        db.delete(existing)
                    continue
                if existing:
                    existing.amount = v
                else:
                    db.add(m.MonthlyInput(period=period, employee_id=ids[code], code=c, amount=v))
        saved += 1
    report = {"total": total, "imported": saved, "rejected": len(errors), "rejected_rows": errors, "columns": list(cols.values())}
    b = _log(db, user, "inputs", file.filename or "file", report, dry_run)
    db.commit()
    return {"batch_id": b.id, **report, "dry_run": dry_run}


@router.get("")
def import_log(user: User, db: DB, kind: str | None = None) -> list[dict]:
    require(user, "employees.import")
    stmt = select(m.ImportBatch).order_by(m.ImportBatch.created_at.desc()).limit(100)
    if kind:
        stmt = stmt.where(m.ImportBatch.kind == kind)
    return [row(b, ["id", "kind", "filename", "uploaded_by", "total", "imported", "rejected", "dry_run", "created_at"]) for b in db.scalars(stmt)]


@router.get("/{batch_id}/rejected.csv")
def rejected_csv(batch_id: int, user: User, db: DB) -> Response:
    require(user, "employees.import")
    b = db.get(m.ImportBatch, batch_id)
    if not b:
        raise HTTPException(404, "No such import")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Row", "Code", "Problems"])
    for r in (b.report or {}).get("rejected_rows", []):
        w.writerow([r.get("row"), r.get("code"), "; ".join(r.get("errors", []))])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="rejected-{batch_id}.csv"'})


TEMPLATES = {
    "employees": (["Emp Code", "First Name", "Last Name", "Gender", "DOB", "DOJ", "Entity", "Location", "Department", "Designation", "Grade",
                   "Mobile", "Email", "PAN", "Aadhaar", "Bank A/c", "IFSC", "Bank Name", "UAN", "ESIC No", "Shift", "Language", "Gross"],
                  ["HV0001", "Selvi", "K", "F", "14-03-1990", "01-08-2022", "VHPL", "OOT", "Housekeeping", "Room Attendant", "G2", "9XXXXXXXXX",
                   "", "ABCDE1234F", "123412341234", "1234567890", "IDIB000O001", "Indian Bank", "100000000001", "5600000001", "A", "ta", "16800"]),
    "salary": (["Emp Code", "Effective From", "Basic", "DA", "HRA", "Conveyance", "Special"], ["HV0001", "01-11-2026", "8400", "0", "3360", "1600", "3440"]),
    "punches": (["Emp Code", "Date", "In Time", "Out Time", "Device"], ["HV0001", "16-11-2026", "06:58", "15:04", "OOT-1"]),
    "inputs": (["Emp Code"] + INPUT_CODES, ["HV0001", "1800", "500", "0", "0", "0", "0", "2500", "0", ""]),
}

HOW_TO = {
    "employees": ["One row per employee. Dates as DD-MM-YYYY.", "Entity = entity code (VHPL, VRL, VFS). Location = location code or name.",
                  "Mandatory: Emp Code, First Name, DOJ, Entity, Location, Department, PAN, Bank A/c, IFSC.",
                  "Gross is split Basic 50%, HRA 20%, Conveyance 1,600, rest Special, unless a salary sheet is imported."],
    "salary": ["One row per employee per effective date. Amounts are monthly rupees.", "A new effective date closes the previous structure the day before."],
    "punches": ["Either one row per day (Date, In Time, Out Time) or one row per punch (Punch Time).",
                "Night shift: an Out Time earlier than the In Time is read as the next day."],
    "inputs": ["One row per employee for the month. Leave a cell empty or 0 to clear it.", "TDS_OVERRIDE replaces the calculated TDS for that month."],
}


@router.get("/templates/{kind}.xlsx")
def template(kind: str, user: User) -> Response:
    if kind not in TEMPLATES:
        raise HTTPException(404, "Unknown template")
    head, example = TEMPLATES[kind]
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(head)
    ws.append(example)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", start_color="0F766E")
    for i in range(1, len(head) + 1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = max(12, len(head[i - 1]) + 4)
    if kind == "employees":
        dv = DataValidation(type="list", formula1='"ta,en,hi"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add("V2:V2000")
    h = wb.create_sheet("How to fill")
    for line in HOW_TO[kind]:
        h.append([line])
    h.column_dimensions["A"].width = 110
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{kind}-template.xlsx"'})

