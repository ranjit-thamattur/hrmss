# Increments (merit matrix)

**Jira:** SCRUM-87  
**Status:** built (synthetic data on laptops). Items marked "not built" below are open.

## What it does

Suggested increment % from final rating × position in the grade's pay band. HR approves the list; the GM (master admin) approves each, which creates a new dated salary structure that payroll uses from the effective date.

## Who uses it

| Role | Uses it to |
|---|---|
| HR | Proposes |
| Master admin (GM) | Approves |

## Screens

- Performance → Increments
- Approvals

## Use cases

```mermaid
flowchart LR
  AHR(("HR"))
  subgraph SYS["Peak HRMS: Increments (merit matrix)"]
    U1(["Adjust and approve list"])
    U2(["Approve increment"])
  end
  AGM(("GM"))
  AHR --- U1
  U2 --- AGM
```

## Data flow (screen → API → tables)

| Screen action | API | Reads | Writes |
|---|---|---|---|
| See proposals | `GET /api/performance/cycles/{id}/increments` | reviews, salary_structures, grades | — |
| HR approve | `POST /api/performance/cycles/{id}/increments` | — | increments, audit_log |
| GM approve / send back | `POST /api/performance/increments/{id}/gm` | increments | increments, salary_structures, audit_log |

Diagram of the writes (every change also adds a row to `audit_log`, left out of the diagram for clarity):

```mermaid
flowchart LR
  S["Screen: Performance → Increments"]
  P1["See proposals<br/><small>GET /api/performance/cycles/{id}/increments</small>"]
  S --> P1
  P2["HR approve<br/><small>POST /api/performance/cycles/{id}/increments</small>"]
  S --> P2
  P2 --> Tincrements[("increments")]
  P3["GM approve / send back<br/><small>POST /api/performance/increments/{id}/gm</small>"]
  S --> P3
  P3 --> Tincrements[("increments")]
  P3 --> Tsalary_structures[("salary_structures")]
```

## Rules and limits

- Merit matrix is a sample (people.py MERIT).

## Code and tests

- `services/hrms-core/backend/app/routers/people.py`
- Test: none yet
