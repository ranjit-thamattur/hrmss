"""Excel import validation (pure). Reading the workbook is done with openpyxl in read_sheet();
everything else works on plain dicts so it can be tested without files.

Rule: imported + rejected always equals the number of data rows in the source.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
AADHAAR_RE = re.compile(r"^\d{12}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Peak field -> accepted column headers (lower-case, spaces/underscores ignored)
EMPLOYEE_COLUMNS: dict[str, list[str]] = {
    "code": ["empcode", "employeecode", "code", "empno", "employeeid"],
    "first_name": ["firstname", "name", "employeename", "fullname"],
    "last_name": ["lastname", "surname"],
    "gender": ["gender", "sex"],
    "dob": ["dob", "dateofbirth", "birthdate"],
    "doj": ["doj", "dateofjoining", "joiningdate", "joinedon"],
    "entity": ["entity", "company", "companycode", "payingentity"],
    "location": ["location", "property", "unit", "site"],
    "department": ["department", "dept"],
    "designation": ["designation", "desig", "role", "title"],
    "grade": ["grade", "band", "level"],
    "phone": ["phone", "mobile", "mobileno", "whatsapp", "phonenumber"],
    "email": ["email", "emailid", "mail"],
    "pan": ["pan", "panno", "pannumber"],
    "aadhaar": ["aadhaar", "aadhar", "aadhaarno", "uid"],
    "bank_account": ["bankaccount", "bankac", "bankacno", "accountnumber", "accountno", "bankaccountno"],
    "ifsc": ["ifsc", "ifsccode"],
    "bank_name": ["bank", "bankname"],
    "uan": ["uan", "uanno", "pfuan"],
    "esic_no": ["esic", "esicno", "esino", "ipnumber"],
    "shift": ["shift", "shiftcode", "defaultshift"],
    "language": ["language", "lang", "preferredlanguage"],
    "monthly_gross": ["gross", "monthlygross", "ctcmonthly", "salary", "grosssalary"],
}

SALARY_COLUMNS: dict[str, list[str]] = {
    "code": EMPLOYEE_COLUMNS["code"],
    "effective_from": ["effectivefrom", "from", "witheffectfrom", "wef"],
    "BASIC": ["basic", "basicpay"],
    "DA": ["da", "dearnessallowance"],
    "HRA": ["hra"],
    "CONV": ["conv", "conveyance"],
    "SPECIAL": ["special", "specialallowance", "otherallowance"],
}

DEFAULT_MANDATORY = ["code", "first_name", "doj", "entity", "location", "department", "pan", "bank_account", "ifsc"]


def norm(h: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(h or "").lower())


def map_columns(headers: Iterable[Any], spec: dict[str, list[str]]) -> tuple[dict[str, int], list[str]]:
    """Return {peak_field: column index} and the list of unmapped source headers."""
    mapping: dict[str, int] = {}
    unmapped: list[str] = []
    for i, h in enumerate(headers):
        n = norm(h)
        hit = next((f for f, aliases in spec.items() if n in aliases or n == norm(f)), None)
        if hit and hit not in mapping:
            mapping[hit] = i
        elif str(h or "").strip():
            unmapped.append(str(h))
    return mapping, unmapped


def to_date(v: Any) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y", "%d-%b-%Y", "%d %b %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"'{s}' is not a date (use DD-MM-YYYY)")


def to_decimal(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v).replace(",", "").strip())
    except InvalidOperation as e:
        raise ValueError(f"'{v}' is not a number") from e


def clean(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


@dataclass
class ImportReport:
    total: int = 0
    valid: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    unmapped_columns: list[str] = field(default_factory=list)
    missing_columns: list[str] = field(default_factory=list)

    @property
    def counts_reconcile(self) -> bool:
        return len(self.valid) + len(self.rejected) == self.total

    def as_dict(self) -> dict[str, Any]:
        return {"total": self.total, "imported": len(self.valid), "rejected": len(self.rejected),
                "rejected_rows": self.rejected, "unmapped_columns": self.unmapped_columns, "missing_columns": self.missing_columns,
                "counts_reconcile": self.counts_reconcile}


def validate_employees(headers: list[Any], rows: list[list[Any]], *, entities: set[str], locations: set[str],
                       departments: set[str], designations: set[str] | None = None, grades: set[str] | None = None,
                       existing_codes: set[str] | None = None, mandatory: list[str] | None = None) -> ImportReport:
    mandatory = mandatory or DEFAULT_MANDATORY
    mapping, unmapped = map_columns(headers, EMPLOYEE_COLUMNS)
    rep = ImportReport(unmapped_columns=unmapped, missing_columns=[m for m in mandatory if m not in mapping])
    existing = {c.upper() for c in (existing_codes or set())}
    seen: dict[str, int] = {}
    up = lambda s: {x.upper() for x in s}  # noqa: E731
    ents, locs, depts = up(entities), up(locations), up(departments)
    desigs, grds = (up(designations) if designations else None), (up(grades) if grades else None)

    for idx, raw in enumerate(rows, start=2):  # row 1 is the header
        if all(clean(c) == "" for c in raw):
            continue
        rep.total += 1
        rec = {f: (raw[i] if i < len(raw) else None) for f, i in mapping.items()}
        errors: list[str] = []
        for m in mandatory:
            if clean(rec.get(m)) == "":
                errors.append(f"Missing {m.replace('_', ' ')}")
        out: dict[str, Any] = {k: clean(v) for k, v in rec.items()}
        out["code"] = out.get("code", "").upper()
        code = out["code"]
        if code:
            if code in seen:
                errors.append(f"Duplicate employee code (also row {seen[code]})")
            elif code in existing:
                errors.append("Employee code already exists")
            seen.setdefault(code, idx)
        pan = out.get("pan", "").upper()
        if pan and not PAN_RE.match(pan):
            errors.append(f"Bad PAN format '{pan}'")
        out["pan"] = pan
        aad = re.sub(r"\s", "", out.get("aadhaar", ""))
        if aad and not AADHAAR_RE.match(aad):
            errors.append("Aadhaar must be 12 digits")
        out["aadhaar"] = aad
        ifsc = out.get("ifsc", "").upper()
        if ifsc and not IFSC_RE.match(ifsc):
            errors.append(f"Bad IFSC '{ifsc}'")
        out["ifsc"] = ifsc
        if out.get("email") and not EMAIL_RE.match(out["email"]):
            errors.append("Bad email")
        for f, known, label in (("entity", ents, "entity"), ("location", locs, "location"), ("department", depts, "department"),
                                ("designation", desigs, "designation"), ("grade", grds, "grade")):
            v = out.get(f, "")
            if v and known is not None and v.upper() not in known:
                errors.append(f"Unknown {label} '{v}'")
        for f in ("dob", "doj"):
            try:
                out[f] = to_date(rec.get(f))
            except ValueError as e:
                errors.append(f"{f.upper()}: {e}")
        try:
            out["monthly_gross"] = to_decimal(rec.get("monthly_gross"))
        except ValueError as e:
            errors.append(f"Gross: {e}")
        if errors:
            rep.rejected.append({"row": idx, "code": code, "name": out.get("first_name", ""), "errors": errors})
        else:
            out["row"] = idx
            rep.valid.append(out)
    return rep


def validate_salary(headers: list[Any], rows: list[list[Any]], *, known_codes: set[str]) -> ImportReport:
    mapping, unmapped = map_columns(headers, SALARY_COLUMNS)
    rep = ImportReport(unmapped_columns=unmapped, missing_columns=[m for m in ("code", "effective_from", "BASIC") if m not in mapping])
    known = {c.upper() for c in known_codes}
    for idx, raw in enumerate(rows, start=2):
        if all(clean(c) == "" for c in raw):
            continue
        rep.total += 1
        rec = {f: (raw[i] if i < len(raw) else None) for f, i in mapping.items()}
        errors: list[str] = []
        code = clean(rec.get("code")).upper()
        if not code:
            errors.append("Missing code")
        elif code not in known:
            errors.append(f"Unknown employee '{code}'")
        comps: dict[str, Decimal] = {}
        for c in ("BASIC", "DA", "HRA", "CONV", "SPECIAL"):
            try:
                v = to_decimal(rec.get(c))
            except ValueError as e:
                errors.append(f"{c}: {e}")
                continue
            if v is not None:
                if v < 0:
                    errors.append(f"{c} is negative")
                comps[c] = v
        if not comps.get("BASIC"):
            errors.append("BASIC is required")
        try:
            eff = to_date(rec.get("effective_from"))
            if not eff:
                errors.append("Missing effective from")
        except ValueError as e:
            errors.append(str(e))
            eff = None
        if errors:
            rep.rejected.append({"row": idx, "code": code, "errors": errors})
        else:
            rep.valid.append({"row": idx, "code": code, "effective_from": eff, "components": comps})
    return rep


# ---------------------------------------------------------------- biometric Excel fallback
PUNCH_COLUMNS = {
    "code": EMPLOYEE_COLUMNS["code"] + ["userid", "enrollno", "badge"],
    "datetime": ["datetime", "punchtime", "punchdatetime", "logtime", "timestamp"],
    "date": ["date", "punchdate", "attendancedate"],
    "time": ["time"],
    "in": ["in", "intime", "checkin", "firstin"],
    "out": ["out", "outtime", "checkout", "lastout"],
    "device": ["device", "deviceid", "terminal", "machine", "location"],
}


def _to_time(v: Any) -> time | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.time()
    if isinstance(v, time):
        return v
    if isinstance(v, (int, float)) and 0 <= v < 1:  # Excel fraction of a day
        secs = round(v * 86400)
        return time(secs // 3600, (secs % 3600) // 60)
    s = str(v).strip()
    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M:%S %p"):
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            pass
    raise ValueError(f"'{s}' is not a time")


@dataclass
class PunchParse:
    punches: list[tuple[str, datetime, str]] = field(default_factory=list)  # (code, at, device)
    errors: list[dict[str, Any]] = field(default_factory=list)
    rows: int = 0
    mode: str = ""


def parse_punches(headers: list[Any], rows: list[list[Any]]) -> PunchParse:
    """Accepts one row per punch (code + datetime, or code + date + time) or a daily sheet
    (code + date + in + out). In a daily sheet an out time earlier than the in time is the next day
    (night shift)."""
    mapping, _ = map_columns(headers, PUNCH_COLUMNS)
    res = PunchParse()
    if "code" not in mapping:
        res.errors.append({"row": 1, "errors": ["No employee code column"]})
        return res
    res.mode = "daily" if "in" in mapping else "per_punch"
    for idx, raw in enumerate(rows, start=2):
        if all(clean(c) == "" for c in raw):
            continue
        res.rows += 1
        g = lambda f: raw[mapping[f]] if f in mapping and mapping[f] < len(raw) else None  # noqa: E731
        code = clean(g("code")).upper()
        device = clean(g("device"))
        try:
            if not code:
                raise ValueError("Missing employee code")
            if res.mode == "daily":
                d = to_date(g("date"))
                if not d:
                    raise ValueError("Missing date")
                tin, tout = _to_time(g("in")), _to_time(g("out"))
                if tin:
                    res.punches.append((code, datetime.combine(d, tin), device))
                if tout:
                    out_dt = datetime.combine(d, tout)
                    if tin and tout <= tin:
                        out_dt += timedelta(days=1)
                    res.punches.append((code, out_dt, device))
                if not tin and not tout:
                    raise ValueError("No in or out time")
            else:
                dtv = g("datetime")
                if isinstance(dtv, datetime):
                    at = dtv
                elif dtv:
                    s = str(dtv).strip()
                    at = None
                    for fmt in ("%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M:%S"):
                        try:
                            at = datetime.strptime(s, fmt)
                            break
                        except ValueError:
                            pass
                    if at is None:
                        raise ValueError(f"'{s}' is not a date-time")
                else:
                    d, t = to_date(g("date")), _to_time(g("time"))
                    if not d or not t:
                        raise ValueError("Missing date or time")
                    at = datetime.combine(d, t)
                res.punches.append((code, at, device))
        except ValueError as e:
            res.errors.append({"row": idx, "code": code, "errors": [str(e)]})
    return res


def read_sheet(content: bytes, sheet: str | None = None) -> tuple[list[Any], list[list[Any]]]:
    """Read the first (or named) sheet of an .xlsx or a .csv into headers + rows."""
    if content[:2] == b"PK":
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb[sheet] if sheet else wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        headers = list(next(it, []))
        return headers, [list(r) for r in it]
    import csv

    text = content.decode("utf-8-sig")
    data = list(csv.reader(io.StringIO(text)))
    return (data[0] if data else []), data[1:]


def mask(value: str | None, keep: int = 4) -> str:
    if not value:
        return ""
    v = str(value)
    return "X" * max(0, len(v) - keep) + v[-keep:]
