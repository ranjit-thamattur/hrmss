# Employee master (list and record)

**Jira:** SCRUM-44  
**Status:** built (synthetic data on laptops). Items marked "not built" below are open.

## What it does

Searchable, filterable list of all staff (entity, location, department, status, documents expiring) and a record with tabs: profile, pay, documents, change requests and timeline. Sensitive fields follow the masking rules.

## Who uses it

| Role | Uses it to |
|---|---|
| HR, Master admin | Maintain records |
| Payroll, Finance, HOD | Read (HOD: own team only) |

## Screens

- Employees (`/employees`)
- Employee record (`/employees/:id`)

## Use cases

```mermaid
flowchart LR
  AHR(("HR"))
  subgraph SYS["Peak HRMS: Employee master (list and record)"]
    U1(["Find employee"])
    U2(["Edit details"])
    U3(["Filter documents expiring"])
    U4(["See own team"])
  end
  AHOD(("HOD"))
  AHR --- U1
  AHR --- U2
  AHR --- U3
  U4 --- AHOD
```

## Data flow (screen → API → tables)

| Screen action | API | Reads | Writes |
|---|---|---|---|
| List and filter | `GET /api/employees` | employees, employee_documents, change_requests, app_users | — |
| Open record | `GET /api/employees/{id}` | employees, assignments, salary_structures, entity_allocations, employee_documents, change_requests, app_users | — |
| Edit contact / shift | `PATCH /api/employees/{id}` | employees | employees, audit_log |

Diagram of the writes (every change also adds a row to `audit_log`, left out of the diagram for clarity):

```mermaid
flowchart LR
  S["Screen: Employees"]
  P1["List and filter<br/><small>GET /api/employees</small>"]
  S --> P1
  P2["Open record<br/><small>GET /api/employees/{id}</small>"]
  S --> P2
  P3["Edit contact / shift<br/><small>PATCH /api/employees/{id}</small>"]
  S --> P3
  P3 --> Temployees[("employees")]
```

## Rules and limits

- Location, department, designation and grade changes are dated (assignments).
- Bank and PAN changes from staff go through change requests.

## Code and tests

- `services/hrms-core/backend/app/routers/employees.py`
- `services/hrms-core/frontend/src/pages/Employees.jsx`
- Test: `test_api_hv.py::test_scope_and_masking`
