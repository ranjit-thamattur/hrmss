# Payroll run, checks and approvals

**Jira:** SCRUM-60, SCRUM-61, SCRUM-62, SCRUM-63, SCRUM-71, SCRUM-75  
**Status:** built (synthetic data on laptops). Items marked "not built" below are open.

## What it does

Deterministic calculation (not AI) per paying entity and month: locks attendance, applies inputs, calculates earnings, PF, ESI, PT, LWF, TDS and OT, then runs checks. Flagged lines need a decision (accept with note, or hold). Negative pay is blocked. Flow: calculated → reviewed → HR approved → Finance approved → locked; a locked run cannot change.

## Who uses it

| Role | Uses it to |
|---|---|
| Payroll preparer | Calculates, decides lines, submits |
| HR | Approves |
| Finance approver | Approves and locks |

## Screens

- Payroll (`/payroll`) → Runs
- Payroll run (`/payroll/runs/:id`)

## Use cases

```mermaid
flowchart LR
  APayrollpreparer(("Payroll preparer"))
  AHR(("HR"))
  subgraph SYS["Peak HRMS: Payroll run, checks and approvals"]
    U1(["Calculate run"])
    U2(["Accept or hold flagged lines"])
    U3(["Submit"])
    U4(["HR approve"])
    U5(["Send back"])
    U6(["Finance approve"])
    U7(["Lock"])
  end
  AFinanceapprover(("Finance approver"))
  APayrollpreparer --- U1
  APayrollpreparer --- U2
  APayrollpreparer --- U3
  AHR --- U4
  AHR --- U5
  U6 --- AFinanceapprover
  U7 --- AFinanceapprover
```

## Data flow (screen → API → tables)

| Screen action | API | Reads | Writes |
|---|---|---|---|
| New run | `POST /api/payroll/runs` | employees, entity_allocations, salary_structures, attendance_days, monthly_inputs, statutory_rule_versions, policy_versions | payroll_runs, payroll_lines, attendance_days (locked), audit_log |
| Decide a line | `POST /api/payroll/lines/{id}/decide` | payroll_lines | payroll_lines, payroll_runs.totals, audit_log |
| Recalculate | `POST /api/payroll/runs/{id}/recalculate` | same as new run | payroll_lines, payroll_runs |
| Submit / HR approve / Finance approve / Lock | `POST /api/payroll/runs/{id}/submit \| approve-hr \| approve-finance \| lock` | payroll_runs | payroll_runs, audit_log |
| Send back | `POST /api/payroll/runs/{id}/send-back` | payroll_runs | payroll_runs, audit_log |

Diagram of the writes (every change also adds a row to `audit_log`, left out of the diagram for clarity):

```mermaid
flowchart LR
  S["Screen: Payroll"]
  P1["New run<br/><small>POST /api/payroll/runs</small>"]
  S --> P1
  P1 --> Tpayroll_runs[("payroll_runs")]
  P1 --> Tpayroll_lines[("payroll_lines")]
  P1 --> Tattendance_days[("attendance_days")]
  P2["Decide a line<br/><small>POST /api/payroll/lines/{id}/decide</small>"]
  S --> P2
  P2 --> Tpayroll_lines[("payroll_lines")]
  P2 --> Tpayroll_runs[("payroll_runs")]
  P3["Recalculate<br/><small>POST /api/payroll/runs/{id}/recalculate</small>"]
  S --> P3
  P3 --> Tpayroll_lines[("payroll_lines")]
  P3 --> Tpayroll_runs[("payroll_runs")]
  P4["Submit / HR approve / Finance approve / Lock<br/><small>POST /api/payroll/runs/{id}/submit | approve-hr | approve-finance | lock</small>"]
  S --> P4
  P4 --> Tpayroll_runs[("payroll_runs")]
  P5["Send back<br/><small>POST /api/payroll/runs/{id}/send-back</small>"]
  S --> P5
  P5 --> Tpayroll_runs[("payroll_runs")]
```

## Rules and limits

- ON HOLD: no payroll changes until the client's salary sheets arrive.
- Blocked while missed punches are open and the missed-punch rule is unset.
- Same person cannot prepare and approve.

## Code and tests

- `services/hrms-core/backend/app/domain/payroll_engine.py`
- `services/hrms-core/backend/app/services/payroll.py`
- `services/hrms-core/backend/app/routers/payroll.py`
- Test: `test_payroll_engine.py`
- Test: `test_api_hv.py::test_attendance_and_payroll_flow`
- Test: `test_api_hv.py::test_preparer_cannot_approve`
