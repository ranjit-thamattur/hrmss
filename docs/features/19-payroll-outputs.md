# Payroll outputs and payslips

**Jira:** SCRUM-64, SCRUM-72 (part), SCRUM-74 (part)  
**Status:** built (synthetic data on laptops). Items marked "not built" below are open.

## What it does

From a locked run only: payroll register, bank file (held lines left out), Tally journal XML, EPF ECR, ESI file and payslip PDFs (English, Tamil or Hindi labels). Publishing queues payslip messages in the outbox.

## Who uses it

| Role | Uses it to |
|---|---|
| Payroll preparer, Finance | Download files |
| Employee | Downloads own payslip |

## Screens

- Payroll run → Files
- My HR → Payslips

## Use cases

```mermaid
flowchart LR
  AFinance(("Finance"))
  APayrollpreparer(("Payroll preparer"))
  subgraph SYS["Peak HRMS: Payroll outputs and payslips"]
    U1(["Download bank file"])
    U2(["Download Tally journal"])
    U3(["Download EPF / ESI files"])
    U4(["Publish payslips"])
    U5(["Download own payslip"])
  end
  AEmployee(("Employee"))
  AFinance --- U1
  AFinance --- U2
  APayrollpreparer --- U3
  APayrollpreparer --- U4
  U5 --- AEmployee
```

## Data flow (screen → API → tables)

| Screen action | API | Reads | Writes |
|---|---|---|---|
| Download file | `GET /api/payroll/runs/{id}/register.csv \| bank.csv \| tally.xml \| epf-ecr.txt \| esi.csv` | payroll_runs, payroll_lines, employees | — |
| Payslip PDF | `GET /api/payroll/runs/{id}/payslips/{employee_id}.pdf` | payroll_lines, employees | — |
| Publish payslips | `POST /api/payroll/runs/{id}/publish` | payroll_lines | outbox, payroll_runs, audit_log |

Diagram of the writes (every change also adds a row to `audit_log`, left out of the diagram for clarity):

```mermaid
flowchart LR
  S["Screen: Payroll run → Files"]
  P1["Download file<br/><small>GET /api/payroll/runs/{id}/register.csv | bank.csv | tally.xml | epf-ecr.txt | esi.csv</small>"]
  S --> P1
  P2["Payslip PDF<br/><small>GET /api/payroll/runs/{id}/payslips/{employee_id}.pdf</small>"]
  S --> P2
  P3["Publish payslips<br/><small>POST /api/payroll/runs/{id}/publish</small>"]
  S --> P3
  P3 --> Toutbox[("outbox")]
  P3 --> Tpayroll_runs[("payroll_runs")]
```

## Rules and limits

- TDS return file is not built (SCRUM-72).
- WhatsApp sending is not live; messages stay in the outbox (SCRUM-73/74).

## Code and tests

- `services/hrms-core/backend/app/domain/outputs.py`
- `services/hrms-core/backend/app/routers/payroll.py`
- Test: `test_api_hv.py::test_attendance_and_payroll_flow`
