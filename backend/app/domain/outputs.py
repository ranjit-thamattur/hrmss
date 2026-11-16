"""Output files from a locked payroll: bank transfer file, Tally journal, EPF ECR, ESI file, payslip PDF.

Formats are the common ones; the bank's exact bulk-upload layout and Tally ledger names are set in
configuration once Hotel Vivek confirms them (open decision list).
"""
from __future__ import annotations

import csv
import io
from decimal import Decimal
from typing import Any
from xml.sax.saxutils import escape

D = Decimal


def bank_csv(lines: list[dict[str, Any]], *, narration: str) -> str:
    """lines: {code, name, account, ifsc, net}. Lines with no account or net <= 0 are left out."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Beneficiary Name", "Employee Code", "Account Number", "IFSC", "Amount", "Narration"])
    for ln in lines:
        if not ln.get("account") or D(str(ln["net"])) <= 0:
            continue
        w.writerow([ln["name"], ln["code"], ln["account"], ln.get("ifsc", ""), f"{D(str(ln['net'])):.2f}", narration])
    return buf.getvalue()


def tally_journal_xml(*, company: str, date_yyyymmdd: str, narration: str, debits: dict[str, Decimal], credits: dict[str, Decimal]) -> str:
    """Tally import XML with one journal voucher. Debits and credits must balance."""
    td, tc = sum(debits.values(), D(0)), sum(credits.values(), D(0))
    if td != tc:
        raise ValueError(f"Journal does not balance: debits {td} vs credits {tc}")
    entries = []
    for ledger, amt in debits.items():
        if amt:
            entries.append(f"<ALLLEDGERENTRIES.LIST><LEDGERNAME>{escape(ledger)}</LEDGERNAME><ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE><AMOUNT>-{amt:.2f}</AMOUNT></ALLLEDGERENTRIES.LIST>")
    for ledger, amt in credits.items():
        if amt:
            entries.append(f"<ALLLEDGERENTRIES.LIST><LEDGERNAME>{escape(ledger)}</LEDGERNAME><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><AMOUNT>{amt:.2f}</AMOUNT></ALLLEDGERENTRIES.LIST>")
    return (
        "<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA>"
        f"<REQUESTDESC><REPORTNAME>Vouchers</REPORTNAME><STATICVARIABLES><SVCURRENTCOMPANY>{escape(company)}</SVCURRENTCOMPANY></STATICVARIABLES></REQUESTDESC>"
        f"<REQUESTDATA><TALLYMESSAGE xmlns:UDF=\"TallyUDF\"><VOUCHER VCHTYPE=\"Journal\" ACTION=\"Create\"><DATE>{date_yyyymmdd}</DATE>"
        f"<VOUCHERTYPENAME>Journal</VOUCHERTYPENAME><NARRATION>{escape(narration)}</NARRATION>{''.join(entries)}</VOUCHER></TALLYMESSAGE></REQUESTDATA>"
        "</IMPORTDATA></BODY></ENVELOPE>"
    )


def payroll_journal(totals: dict[str, Decimal]) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    """Standard salary journal from run totals (gross, deductions by code, employer by code, net)."""
    g = lambda k: D(str(totals.get(k, 0)))  # noqa: E731
    employer = g("EPF_ER") + g("EPS") + g("EDLI") + g("PF_ADMIN") + g("ESI_ER") + g("LWF_ER")
    debits = {"Salaries & Wages": g("gross"), "Employer PF Contribution": g("EPF_ER") + g("EPS") + g("EDLI") + g("PF_ADMIN"),
              "Employer ESI Contribution": g("ESI_ER"), "Employer LWF Contribution": g("LWF_ER")}
    credits = {"PF Payable": g("PF") + g("EPF_ER") + g("EPS") + g("EDLI") + g("PF_ADMIN"), "ESI Payable": g("ESI") + g("ESI_ER"),
               "Professional Tax Payable": g("PT"), "LWF Payable": g("LWF") + g("LWF_ER"), "TDS Payable (Salary)": g("TDS"),
               "Staff Advances": g("ADVANCE"), "Staff Loans": g("LOAN_EMI"), "Other Deductions": g("OTHER_DEDUCTION"),
               "Salary Payable": g("net")}
    # rounding guard: any difference goes to Salary Payable so the voucher balances
    diff = sum(debits.values(), D(0)) - sum(credits.values(), D(0))
    credits["Salary Payable"] += diff
    _ = employer
    return {k: v for k, v in debits.items() if v}, {k: v for k, v in credits.items() if v}


def epf_ecr(lines: list[dict[str, Any]]) -> str:
    """EPF ECR text: UAN#~#Name#~#Gross#~#EPF wages#~#EPS wages#~#EDLI wages#~#EE share#~#EPS#~#ER diff#~#NCP days#~#Refund"""
    out = []
    for ln in lines:
        if not ln.get("uan") or not D(str(ln.get("PF", 0))):
            continue
        pf_wage = D(str(ln["pf_wage"]))
        capped = min(pf_wage, D(15000))
        out.append("#~#".join(str(x) for x in [ln["uan"], ln["name"].upper(), int(D(str(ln["gross"]))), int(pf_wage), int(capped), int(capped),
                                                int(D(str(ln["PF"]))), int(D(str(ln.get("EPS", 0)))), int(D(str(ln.get("EPF_ER", 0)))),
                                                int(D(str(ln.get("lop_days", 0)))), 0]))
    return "\n".join(out) + ("\n" if out else "")


def esi_csv(lines: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["IP Number", "IP Name", "No of Days", "Total Monthly Wages", "Reason Code", "Last Working Day"])
    for ln in lines:
        if not D(str(ln.get("ESI", 0))):
            continue
        w.writerow([ln.get("esic_no", ""), ln["name"], int(D(str(ln["paid_days"]))), f"{D(str(ln['gross'])):.0f}", "", ""])
    return buf.getvalue()


LABELS = {
    "en": {"title": "Payslip", "earnings": "Earnings", "deductions": "Deductions", "net": "Net pay", "paid_days": "Paid days",
           "employer": "Employer contributions (not deducted)"},
    "ta": {"title": "Sambala seettu (Payslip)", "earnings": "Varumaanam (Earnings)", "deductions": "Piditham (Deductions)",
           "net": "Nigara sambalam (Net pay)", "paid_days": "Sambala naatkal (Paid days)", "employer": "Employer contributions"},
    "hi": {"title": "Vetan parchi (Payslip)", "earnings": "Aay (Earnings)", "deductions": "Katauti (Deductions)", "net": "Shuddh vetan (Net pay)",
           "paid_days": "Vetan divas (Paid days)", "employer": "Employer contributions"},
}


def payslip_pdf(slip: dict[str, Any]) -> bytes:
    """slip: company, period, code, name, designation, location, paid_days, earnings{}, deductions{}, employer{}, gross, total_deductions, net, language.
    PDF labels are transliterated for Tamil/Hindi because base PDF fonts have no Indic glyphs; the WhatsApp
    message carries the native-script text."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    L = LABELS.get(slip.get("language", "en"), LABELS["en"])
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"Payslip {slip['code']} {slip['period']}")
    ss = getSampleStyleSheet()
    teal = colors.HexColor("#0F766E")
    story = [Paragraph(f"<b>{escape(slip['company'])}</b>", ss["Title"]),
             Paragraph(f"{L['title']} · {escape(slip['period'])}", ss["Heading3"]), Spacer(1, 4 * mm)]
    info = [["Employee", f"{slip['name']} ({slip['code']})", L["paid_days"], str(slip["paid_days"])],
            ["Designation", slip.get("designation", ""), "Location", slip.get("location", "")]]
    t = Table(info, colWidths=[28 * mm, 62 * mm, 32 * mm, 52 * mm])
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9), ("TEXTCOLOR", (0, 0), (0, -1), colors.grey), ("TEXTCOLOR", (2, 0), (2, -1), colors.grey)]))
    story += [t, Spacer(1, 5 * mm)]
    e, d = list(slip["earnings"].items()), list(slip["deductions"].items())
    rows = [[L["earnings"], "Rs", L["deductions"], "Rs"]]
    for i in range(max(len(e), len(d))):
        a = e[i] if i < len(e) else ("", "")
        b = d[i] if i < len(d) else ("", "")
        rows.append([a[0].replace("_", " ").title(), f"{D(str(a[1])):,.0f}" if a[1] != "" else "", b[0].replace("_", " ").title(),
                     f"{D(str(b[1])):,.0f}" if b[1] != "" else ""])
    rows.append(["Gross", f"{D(str(slip['gross'])):,.0f}", "Total", f"{D(str(slip['total_deductions'])):,.0f}"])
    t = Table(rows, colWidths=[55 * mm, 32 * mm, 55 * mm, 32 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), teal), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, -1), 9),
                           ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("ALIGN", (3, 0), (3, -1), "RIGHT"), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D5DADF")),
                           ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")]))
    story += [t, Spacer(1, 5 * mm),
              Paragraph(f"<b>{L['net']}: Rs {D(str(slip['net'])):,.0f}</b>", ss["Heading2"])]
    if slip.get("employer"):
        story.append(Paragraph(f"{L['employer']}: " + ", ".join(f"{k.replace('_', ' ')} Rs {D(str(v)):,.0f}" for k, v in slip["employer"].items()), ss["Normal"]))
    story += [Spacer(1, 8 * mm), Paragraph("This is a system-generated payslip and does not need a signature.", ss["Italic"])]
    doc.build(story)
    return buf.getvalue()
