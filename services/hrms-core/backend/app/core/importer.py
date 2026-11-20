"""Excel import for any catalogue entity (rule 9): template download, then row-by-row import with an error
report and a duplicate check. Every row goes through the same create() as the API, so the same rules apply.
Imported + rejected = rows in the file.
"""
from __future__ import annotations

import io
import json
from datetime import date, datetime
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

from . import access, engine
from .context import Ctx, current
from .records import model
from .schemas import create_schema
from .specs import SPECS, F, Spec


def columns(spec: Spec) -> list[tuple[str, F | None]]:
    """(header, field). References by code where the target has codes, else by rid."""
    out: list[tuple[str, F | None]] = []
    for f in spec.input_fields:
        target = SPECS[f.ref] if f.ref else None
        if f.kind == "ref" and target and target.code_field:
            out.append((f"{f.name.removesuffix('_rid')}_code", f))
        elif f.kind == "refs" and target and target.code_field:
            out.append((f"{f.name.removesuffix('_rids')}_codes", f))
        else:
            out.append((f.name, f))
    out.append(("valid_from", None))
    out.append(("valid_to", None))
    return out


def _describe(f: F | None, header: str) -> str:
    if f is None:
        return "Date YYYY-MM-DD" + (" (default: today)" if header == "valid_from" else " (empty = open)")
    if f.kind == "enum":
        return "One of: " + ", ".join(f.choices)
    if header.endswith("_codes"):
        return f"Codes of {SPECS[f.ref].title.lower()}s, separated by ;"
    if header.endswith("_code"):
        return f"Code of the {SPECS[f.ref].title.lower()}"
    if f.kind in ("ref", "refs"):
        return f"Record id (rid) of the {SPECS[f.ref].title.lower()}" + ("s, separated by ;" if f.kind == "refs" else "")
    if f.kind in ("json", "secret_json"):
        return "JSON text"
    return {"date": "Date YYYY-MM-DD", "bool": "yes / no", "int": "Whole number", "year": "Year", "decimal": "Number",
            "time": "HH:MM (24 h)", "period": "YYYY-MM", "secret": "Kept encrypted; shown masked"}.get(f.kind, "Text")


def template(spec: Spec) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    cols = columns(spec)
    ws.append([h for h, _ in cols])
    for i, c in enumerate(ws[1], start=1):
        c.font = Font(bold=True, color="FFFFFF", name="Arial")
        c.fill = PatternFill("solid", start_color="0F766E")
        ws.column_dimensions[c.column_letter].width = max(14, len(cols[i - 1][0]) + 4)
    how = wb.create_sheet("How to")
    how.append(["Column", "Required", "What to enter"])
    for c in how[1]:
        c.font = Font(bold=True, name="Arial")
    for h, f in cols:
        how.append([h, "yes" if f is not None and f.required and f.default is None else "", _describe(f, h)])
    how.append([])
    how.append([f"{spec.title}: one row per record. Rows with errors are rejected with the reason; the others are imported."])
    how.column_dimensions["A"].width = 28
    how.column_dimensions["C"].width = 70
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _date(v: Any) -> date | None:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"'{s}' is not a date (use YYYY-MM-DD)")


def _by_code(ctx: Ctx, key: str, code: str, on: date) -> int | None:
    t = SPECS[key]
    md = model(t)
    return ctx.db.scalar(select(md.rid).where(md.client_id == ctx.client_id, current(md, on), md.is_active.is_(True),
                                              func.lower(getattr(md, t.code_field)) == str(code).strip().lower()).limit(1))


def _cell(ctx: Ctx, header: str, f: F, v: Any, on: date) -> Any:
    if f.kind == "ref" and header.endswith("_code"):
        rid = _by_code(ctx, f.ref, v, on)
        if rid is None:
            raise ValueError(f"{header}: '{v}' not found")
        return rid
    if f.kind == "refs":
        parts = [p.strip() for p in str(v).replace(",", ";").split(";") if p.strip()]
        if header.endswith("_codes"):
            out = []
            for p in parts:
                rid = _by_code(ctx, f.ref, p, on)
                if rid is None:
                    raise ValueError(f"{header}: '{p}' not found")
                out.append(rid)
            return out
        return [int(p) for p in parts]
    if f.kind in ("json", "secret_json"):
        return json.loads(v) if isinstance(v, str) else v
    if f.kind == "date":
        return _date(v)
    if f.kind == "bool":
        return str(v).strip().lower() in ("yes", "y", "true", "1")
    if f.kind in ("int", "year", "ref") and isinstance(v, float) and v.is_integer():
        return int(v)
    if f.kind in ("str", "secret", "time", "period", "email", "text") and isinstance(v, float) and v.is_integer():
        return str(int(v))
    return v


def import_file(ctx: Ctx, spec: Spec, content: bytes, dry_run: bool) -> dict[str, Any]:
    from ..rules.imports import read_sheet

    access.require(ctx, spec.key, "import")
    if not spec.creatable:
        raise HTTPException(405, f"{spec.title} records cannot be imported.")
    try:
        headers, rows = read_sheet(content)
    except Exception as e:  # noqa: BLE001 - any unreadable file
        raise HTTPException(422, f"Could not read the file: {e}") from e
    cols = columns(spec)
    known = {h for h, _ in cols}
    norm = [str(h).strip().lower() if h is not None else "" for h in headers]
    missing = [h for h, f in cols if f is not None and f.required and f.default is None and h not in norm]
    unknown = [h for h in norm if h and h not in known]
    report: dict[str, Any] = {"resource": spec.key, "dry_run": dry_run, "total": 0, "imported": 0, "rejected": 0, "rejected_rows": [],
                              "imported_rids": [], "missing_columns": missing, "unknown_columns": unknown}
    if missing:
        raise HTTPException(422, {"message": f"Missing required columns: {', '.join(missing)}", **report})
    seen_codes: dict[str, int] = {}
    schema = create_schema(spec.key)
    for n, raw_row in enumerate(rows, start=2):
        if all(v in (None, "") for v in raw_row):
            continue
        report["total"] += 1
        raw = {norm[i]: raw_row[i] for i in range(min(len(norm), len(raw_row))) if norm[i]}
        errors: list[str] = []
        data: dict[str, Any] = {}
        try:
            start = _date(raw.get("valid_from")) or ctx.today
            data["valid_from"] = start
            data["valid_to"] = _date(raw.get("valid_to"))
        except ValueError as e:
            errors.append(str(e))
            start = ctx.today
        for h, f in cols:
            if f is None or raw.get(h) in (None, ""):
                continue
            try:
                data[f.name] = _cell(ctx, h, f, raw[h], start)
            except (ValueError, json.JSONDecodeError) as e:
                errors.append(f"{h}: {e}" if not str(e).startswith(h) else str(e))
        code = str(data.get(spec.code_field) or "").strip().lower() if spec.code_field else ""
        if code:
            if code in seen_codes:
                errors.append(f"Duplicate code in this file (also on row {seen_codes[code]})")
            else:
                seen_codes[code] = n
        if not errors:
            try:
                body = schema.model_validate(data).model_dump()
            except ValidationError as e:
                errors += [f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()]
        if not errors:
            sp = ctx.db.begin_nested()
            try:
                vals = {k: v for k, v in body.items() if k not in ("valid_from", "valid_to", "change_reason")}
                row = engine.create(ctx, spec, vals, body["valid_from"], body["valid_to"], body.get("change_reason") or "Excel import")
                sp.commit()
                report["imported_rids"].append(row.rid)
            except HTTPException as e:
                sp.rollback()
                errors.append(e.detail if isinstance(e.detail, str) else json.dumps(e.detail))
        if errors:
            report["rejected"] += 1
            report["rejected_rows"].append({"row": n, "code": data.get(spec.code_field) if spec.code_field else None, "errors": errors})
        else:
            report["imported"] += 1
    report["counts_reconcile"] = report["imported"] + report["rejected"] == report["total"]
    return report
