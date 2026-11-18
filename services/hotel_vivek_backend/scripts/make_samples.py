"""Builds the synthetic Hotel Vivek sample Excel files in services/hotel_vivek_backend/samples (no real people).
Run from services/hotel_vivek_backend:  python scripts/make_samples.py"""
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

OUT = Path(__file__).resolve().parents[1] / "samples"
OUT.mkdir(parents=True, exist_ok=True)


def save(name, head, rows, notes):
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(head)
    for r in rows:
        ws.append(r)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF", name="Arial")
        c.fill = PatternFill("solid", start_color="0F766E")
    for i, h in enumerate(head, start=1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = max(12, len(str(h)) + 4)
    n = wb.create_sheet("Notes")
    for line in notes:
        n.append([line])
    n.column_dimensions["A"].width = 110
    wb.save(OUT / name)


EMP_HEAD = ["Emp Code", "First Name", "Last Name", "Gender", "DOB", "DOJ", "Entity", "Location", "Department", "Designation", "Grade", "Mobile", "Email",
            "PAN", "Aadhaar", "Bank A/c", "IFSC", "Bank Name", "UAN", "ESIC No", "Shift", "Language", "Gross"]
emps = [
    ["HV0901", "Nila", "R", "F", "02-02-1996", "01-11-2026", "VHPL", "OOT", "Housekeeping", "Room Attendant", "G1", "9000000901", "", "AAAPN0901A", "111122220901", "50100000901", "SBIN0000901", "State Bank of India", "", "", "A", "ta", "14500"],
    ["HV0902", "Kumar", "S", "M", "11-07-1992", "01-11-2026", "VHPL", "CNR", "Kitchen", "Commis", "G2", "9000000902", "", "AAAPK0902B", "111122220902", "50100000902", "SBIN0000902", "State Bank of India", "", "", "B", "ta", "16500"],
    ["HV0903", "Asha", "M", "F", "23-09-1994", "03-11-2026", "VRL", "KTG", "Front Office", "Front Office Associate", "G2", "9000000903", "", "AAAPA0903C", "111122220903", "50100000903", "IDIB000K903", "Indian Bank", "", "", "G", "en", "17500"],
    ["HV0904", "Farid", "A", "M", "05-05-1990", "05-11-2026", "VRL", "MTP", "Security", "Security Guard", "G1", "9000000904", "", "AAAPF0904D", "111122220904", "50100000904", "IDIB000M904", "Indian Bank", "", "", "N", "hi", "14000"],
    ["HV0905", "Geetha", "P", "F", "17-12-1998", "05-11-2026", "VFS", "CBE", "Accounts", "Accounts Associate", "G3", "9000000905", "", "AAAPG0905E", "111122220905", "50100000905", "HDFC0000905", "HDFC Bank", "", "", "G", "ta", "21000"],
    # planted errors: bad PAN, unknown location, missing bank, duplicate code
    ["HV0906", "Error", "BadPan", "M", "01-01-1990", "05-11-2026", "VHPL", "OOT", "Kitchen", "Commis", "G1", "9000000906", "", "BADPAN", "", "50100000906", "SBIN0000906", "SBI", "", "", "A", "ta", "14000"],
    ["HV0907", "Error", "NoLocation", "F", "01-01-1990", "05-11-2026", "VHPL", "XYZ", "Kitchen", "Commis", "G1", "9000000907", "", "AAAPE0907F", "", "50100000907", "SBIN0000907", "SBI", "", "", "A", "ta", "14000"],
    ["HV0908", "Error", "NoBank", "M", "01-01-1990", "05-11-2026", "VHPL", "OOT", "Laundry", "Laundry Attendant", "G1", "9000000908", "", "AAAPE0908G", "", "", "", "", "", "", "A", "ta", "14000"],
    ["HV0901", "Error", "Duplicate", "F", "01-01-1990", "05-11-2026", "VHPL", "OOT", "Housekeeping", "Room Attendant", "G1", "9000000909", "", "AAAPE0909H", "", "50100000909", "SBIN0000909", "SBI", "", "", "A", "ta", "14000"],
]
save("employees_sample.xlsx", EMP_HEAD, emps, ["Synthetic people only. 9 rows: 5 valid, 4 with planted errors (bad PAN, unknown location, no bank, duplicate code).",
                                              "Expected import result: 5 imported + 4 rejected = 9 rows."])

save("salary_sample.xlsx", ["Emp Code", "Effective From", "Basic", "DA", "HRA", "Conveyance", "Special"],
     [["HV0001", "01-12-2026", "8800", "0", "3520", "1600", "3680"], ["HV0002", "01-12-2026", "9500", "0", "3800", "1600", "4100"],
      ["HV9999", "01-12-2026", "9000", "0", "3600", "1600", "3800"]],
     ["Row 3 has an unknown employee code and is rejected.", "A new effective date closes the old structure the day before."])

save("punches_sample.xlsx", ["Emp Code", "Date", "In Time", "Out Time", "Device"],
     [["HV0001", "16-11-2026", "06:58", "15:04", "OOT-1"], ["HV0002", "16-11-2026", "06:52", "", "OOT-1"],
      ["HV0003", "16-11-2026", "22:55", "07:05", "OOT-1"], ["HV0004", "16-11-2026", "09:20", "18:10", "CNR-1"],
      ["HV0005", "16-11-2026", "06:59", "16:45", "CNR-1"]],
     ["Daily format. Row 2 is a missed punch (no out time).", "Row 3 is a night shift: out time 07:05 is the next morning.",
      "Row 4 is late for a 09:00 shift; row 5 has 1h45 extra (OT needs HOD approval)."])

save("monthly_inputs_sample.xlsx", ["Emp Code", "SERVICE_CHARGE", "INCENTIVE", "ARREAR", "BONUS", "OTHER_EARNING", "ADVANCE", "LOAN_EMI", "OTHER_DEDUCTION", "TDS_OVERRIDE"],
     [["HV0001", 1800, 500, 0, 0, 0, 0, 0, 0, None], ["HV0002", 1800, 0, 0, 0, 0, 2000, 0, 0, None], ["HV0003", 1800, 0, 1200, 0, 0, 0, 1500, 0, None]],
     ["Amounts in rupees for one pay period (choose the period when importing).", "Empty or 0 removes an existing input."])
print("Samples written to", OUT)
