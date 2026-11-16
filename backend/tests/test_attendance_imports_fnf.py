from datetime import date, datetime, time
from decimal import Decimal as D

import pytest

from app.domain.attendance_engine import Shift, assign_punches, build_day, summarise_month
from app.domain.fnf import FnfInput, add_working_days, calculate_fnf, service_years
from app.domain.imports import parse_punches, validate_employees, validate_salary
from app.domain.outputs import bank_csv, epf_ecr, esi_csv, payroll_journal, payslip_pdf, tally_journal_xml

A = Shift("A", time(7), time(15), 30)
N = Shift("N", time(23), time(7), 30)
OFF = Shift("OFF", time(0), time(0), 0, is_off=True)


# ---------------- attendance
def test_day_shift_present_late_and_ot():
    d = date(2026, 11, 16)
    r = build_day(d, A, [datetime(2026, 11, 16, 7, 25), datetime(2026, 11, 16, 16, 30)])
    assert r.status == "present"
    assert r.late_minutes == 15  # 25 min after start, minus 10 min grace
    assert r.worked_minutes == 545
    assert r.ot_minutes == 90  # 545 - 450 scheduled = 95 -> 90 in 30-min blocks


def test_night_shift_counts_on_start_date():
    shifts = {date(2026, 11, 16): N, date(2026, 11, 17): N}
    punches = [datetime(2026, 11, 16, 22, 55), datetime(2026, 11, 17, 7, 5), datetime(2026, 11, 17, 22, 58), datetime(2026, 11, 18, 7, 2)]
    by, orphans = assign_punches(punches, shifts)
    assert orphans == []
    assert by[date(2026, 11, 16)] == punches[:2]
    assert by[date(2026, 11, 17)] == punches[2:]
    r = build_day(date(2026, 11, 16), N, by[date(2026, 11, 16)])
    assert r.status == "present" and r.worked_minutes == 490


def test_missed_punch_and_double_tap():
    d = date(2026, 11, 16)
    r = build_day(d, A, [datetime(2026, 11, 16, 7, 0), datetime(2026, 11, 16, 7, 1)])  # double tap = 1 punch
    assert r.status == "missed_punch"


def test_absent_leave_weekly_off():
    d = date(2026, 11, 16)
    assert build_day(d, A, []).status == "absent"
    assert build_day(d, A, [], on_leave=True).status == "leave"
    assert build_day(d, OFF, []).status == "weekly_off"


def test_month_summary_requires_rule_when_punches_open():
    d1, d2 = date(2026, 11, 1), date(2026, 11, 2)
    days = [build_day(d1, A, [datetime(2026, 11, 1, 7)]), build_day(d2, A, [])]
    with pytest.raises(ValueError, match="rule is not set"):
        summarise_month(days, 30, missed_punch_rule=None)
    assert summarise_month(days, 30, missed_punch_rule="present").lop_days == D(1)
    assert summarise_month(days, 30, missed_punch_rule="lop").lop_days == D(2)
    s = summarise_month(days, 30, missed_punch_rule="hold")
    assert s.lop_days == D(2) and s.held_days == 1


# ---------------- employee import with planted errors (SCRUM-125)
HEAD = ["Emp Code", "Name", "DOJ", "Company", "Location", "Department", "PAN", "Bank A/c", "IFSC", "Gross", "Remarks"]
ROWS = [
    ["HV0001", "Selvi K", "01-08-2022", "VHPL", "OOT", "Housekeeping", "ABCDE1234F", "1234567890", "IDIB000O001", "16800", ""],
    ["HV0002", "Ravi S", "01-02-2024", "VHPL", "OOT", "F&B Service", "ABCDE1234G", "", "SBIN0001234", "15800", ""],  # missing bank
    ["HV0001", "Dup", "01-02-2024", "VHPL", "OOT", "Kitchen", "ABCDE1234H", "111", "SBIN0001234", "15000", ""],  # duplicate code
    ["HV0004", "Bad Pan", "01-02-2024", "VHPL", "OOT", "Kitchen", "ABCD1234", "222", "SBIN0001234", "15000", ""],  # bad PAN
    ["HV0005", "Who", "01-02-2024", "XYZ", "OOT", "Kitchen", "ABCDE1234J", "333", "SBIN0001234", "15000", ""],  # unknown entity
    ["HV0006", "", "01-02-2024", "VHPL", "OOT", "Kitchen", "ABCDE1234K", "444", "SBIN0001234", "15000", ""],  # blank mandatory
    ["", "", "", "", "", "", "", "", "", "", ""],  # blank line ignored
]


def test_import_rejects_every_planted_error_and_reconciles():
    rep = validate_employees(HEAD, ROWS, entities={"VHPL", "VRL", "VFS"}, locations={"OOT"}, departments={"Housekeeping", "F&B Service", "Kitchen"})
    assert rep.total == 6 and len(rep.valid) == 1 and len(rep.rejected) == 5
    assert rep.counts_reconcile
    errs = {r["row"]: " ".join(r["errors"]) for r in rep.rejected}
    assert "Missing bank account" in errs[3]
    assert "Duplicate employee code" in errs[4]
    assert "Bad PAN" in errs[5]
    assert "Unknown entity" in errs[6]
    assert "Missing first name" in errs[7]
    assert rep.unmapped_columns == ["Remarks"]


def test_salary_import():
    rep = validate_salary(["Emp Code", "WEF", "Basic", "HRA", "Special"], [["HV0001", "01-11-2026", 8400, 3360, 5040], ["HV9", "01-11-2026", "", 1, 1]],
                          known_codes={"HV0001"})
    assert len(rep.valid) == 1 and rep.valid[0]["components"]["BASIC"] == D(8400)
    assert "Unknown employee" in " ".join(rep.rejected[0]["errors"])


# ---------------- biometric Excel fallback (SCRUM-127)
def test_punch_file_daily_format_night_shift_and_bad_rows():
    res = parse_punches(["Emp Code", "Date", "In Time", "Out Time", "Device"],
                        [["HV0001", "16-11-2026", "22:58", "07:04", "OOT-1"], ["HV0002", "16-11-2026", "07:02", "", "OOT-1"],
                         ["HV0003", "31-13-2026", "07:00", "15:00", "OOT-1"]])
    assert res.mode == "daily" and res.rows == 3
    assert (res.punches[1][1] - res.punches[0][1]).total_seconds() == 8 * 3600 + 6 * 60  # out is next day
    assert len(res.punches) == 3  # missed out-punch kept as a single punch
    assert len(res.errors) == 1 and res.errors[0]["row"] == 4


def test_punch_file_per_punch_format():
    res = parse_punches(["UserID", "Punch Time", "Terminal"], [["HV0001", datetime(2026, 11, 16, 7, 1), "T1"], ["HV0001", "16-11-2026 15:02", "T1"]])
    assert res.mode == "per_punch" and len(res.punches) == 2 and not res.errors


# ---------------- full and final
def test_fnf_due_in_two_working_days_and_gratuity_rule():
    assert add_working_days(date(2026, 11, 24), 2) == date(2026, 11, 26)
    assert add_working_days(date(2026, 11, 27), 2) == date(2026, 11, 30)  # Fri -> Sat, (Sun off), Mon
    assert service_years(date(2023, 6, 12), date(2026, 11, 24)) == (3, 5)
    r = calculate_fnf(FnfInput(D(21400), D(10700), date(2023, 6, 12), date(2026, 10, 26), date(2026, 11, 24), 30, 30, 24, D(11), D(7500)))
    assert not r.gratuity_eligible and "GRATUITY" not in r.earnings
    assert r.earnings["SALARY_TO_LWD"] == D(17120)
    assert r.deductions["LOAN_BALANCE"] == D(7500)
    assert "NOTICE_SHORTFALL" not in r.deductions
    g = calculate_fnf(FnfInput(D(30000), D(15000), date(2018, 1, 1), date(2026, 11, 1), date(2026, 11, 30), 30, 30, 30))
    assert g.gratuity_eligible and g.earnings["GRATUITY"] == D(77885)  # 15000*15/26*9 (8y 10m -> 9)


def test_fnf_notice_shortfall():
    r = calculate_fnf(FnfInput(D(30000), D(15000), date(2024, 1, 1), date(2026, 11, 1), date(2026, 11, 10), 30, 30, 10))
    assert r.deductions["NOTICE_SHORTFALL"] == D(20000)


# ---------------- output files
LINES = [{"code": "HV0001", "name": "Selvi K", "account": "1234567890", "ifsc": "IDIB000O001", "net": "16665", "uan": "100000000001",
          "gross": "18000", "pf_wage": "10000", "PF": "1200", "EPS": "833", "EPF_ER": "367", "lop_days": "0", "ESI": "135", "esic_no": "5600001",
          "paid_days": "30"},
         {"code": "HV0002", "name": "No Bank", "account": "", "ifsc": "", "net": "100", "uan": "", "gross": "100", "pf_wage": "0", "PF": "0",
          "paid_days": "1"}]


def test_bank_file_skips_missing_accounts():
    out = bank_csv(LINES, narration="SALARY NOV 2026")
    assert "HV0001" in out and "HV0002" not in out and "16665.00" in out


def test_tally_journal_balances():
    debits, credits = payroll_journal({"gross": D(18000), "PF": D(1200), "ESI": D(135), "EPF_ER": D(367), "EPS": D(833), "EDLI": D(50),
                                       "PF_ADMIN": D(50), "ESI_ER": D(585), "net": D(16665)})
    assert sum(debits.values()) == sum(credits.values())
    xml = tally_journal_xml(company="Vivek Hotels", date_yyyymmdd="20261126", narration="Salary Nov 2026", debits=debits, credits=credits)
    assert xml.startswith("<ENVELOPE>") and "Salary Payable" in xml
    with pytest.raises(ValueError):
        tally_journal_xml(company="x", date_yyyymmdd="20261126", narration="x", debits={"a": D(1)}, credits={"b": D(2)})


def test_ecr_and_esi_files():
    ecr = epf_ecr(LINES)
    assert ecr.count("\n") == 1 and ecr.startswith("100000000001#~#SELVI K#~#18000#~#10000#~#10000")
    assert "5600001" in esi_csv(LINES)


def test_payslip_pdf():
    pdf = payslip_pdf({"company": "Vivek Hotels Pvt Ltd", "period": "November 2026", "code": "HV0001", "name": "Selvi K", "designation": "Room Attendant",
                       "location": "Ooty", "paid_days": "30", "earnings": {"BASIC": "10000", "HRA": "4000"}, "deductions": {"PF": "1200"},
                       "employer": {"EPS": "833"}, "gross": "14000", "total_deductions": "1200", "net": "12800", "language": "ta"})
    assert pdf[:4] == b"%PDF" and len(pdf) > 1500
