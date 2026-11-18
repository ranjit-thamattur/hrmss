# Audit trail and employee timeline

**Jira:** SCRUM-47, SCRUM-92  
**Status:** built (synthetic data on laptops). Items marked "not built" below are open.

## What it does

Every change is written to an append-only audit log (who, when, what, before and after, sensitive values masked). A database trigger rejects UPDATE and DELETE on Postgres. The employee timeline shows dated assignments and that person's audit events.

## Who uses it

| Role | Uses it to |
|---|---|
| Master admin, HR | Read |

## Screens

- Audit trail (`/audit`)
- Employee record → Timeline

## Use cases

```mermaid
flowchart LR
  AHR(("HR"))
  subgraph SYS["Peak HRMS: Audit trail and employee timeline"]
    U1(["Search changes"])
    U2(["See employee history"])
    U3(["Review exported trail"])
  end
  AAuditoroutsidetheapp(("Auditor (outside the app)"))
  AHR --- U1
  AHR --- U2
  U3 --- AAuditoroutsidetheapp
```

## Data flow (screen → API → tables)

| Screen action | API | Reads | Writes |
|---|---|---|---|
| Search audit | `GET /api/audit` | audit_log | — |
| Employee timeline | `GET /api/employees/{id}/timeline` | assignments, audit_log | — |
| Any change anywhere | `—` | — | audit_log (insert only) |

Diagram of the writes (every change also adds a row to `audit_log`, left out of the diagram for clarity):

```mermaid
flowchart LR
  S["Screen: Audit trail"]
  P1["Search audit<br/><small>GET /api/audit</small>"]
  S --> P1
  P2["Employee timeline<br/><small>GET /api/employees/{id}/timeline</small>"]
  S --> P2
  P3["Any change anywhere<br/><small>—</small>"]
  S --> P3
```

## Rules and limits

- CI proves the trigger blocks UPDATE (decision 0002).

## Code and tests

- `services/hrms-core/backend/app/services/audit.py`
- `services/hrms-core/backend/alembic/versions/0001_baseline.py`
- Test: `test_api_hv.py::test_audit_and_timeline`
