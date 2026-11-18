# Onboarding an employee (manual)

**Jira:** SCRUM-79 (part), SCRUM-121  
**Status:** built (synthetic data on laptops). Items marked "not built" below are open.

## What it does

HR adds a new joiner by hand: person, job, statutory and bank details and monthly gross. The system creates the first assignment, 100% allocation to the location's entity, a salary structure (Basic 50%, HRA 20%, Conveyance 1,600, rest Special), leave balances and a biometric enrolment task. No agent, no offer-letter automation (removed with Peak Brain). Software access is a separate step.

## Who uses it

| Role | Uses it to |
|---|---|
| HR, Master admin | Onboard |

## Screens

- Onboard employee (`/employees/new`)

## Use cases

```mermaid
flowchart LR
  AHR(("HR"))
  subgraph SYS["Peak HRMS: Onboarding an employee (manual)"]
    U1(["Add new joiner"])
    U2(["Then give software access (optional)"])
    U3(["Enrol (task)"])
  end
  ABiometricdevice(("Biometric device"))
  AHR --- U1
  AHR --- U2
  U3 --- ABiometricdevice
```

## Data flow (screen → API → tables)

| Screen action | API | Reads | Writes |
|---|---|---|---|
| Save new employee | `POST /api/employees` | entities, locations, grades, leave_types | employees, assignments, entity_allocations, salary_structures, leave_balances, provisioning_tasks, audit_log |

Diagram of the writes (every change also adds a row to `audit_log`, left out of the diagram for clarity):

```mermaid
flowchart LR
  S["Screen: Onboard employee"]
  P1["Save new employee<br/><small>POST /api/employees</small>"]
  S --> P1
  P1 --> Temployees[("employees")]
  P1 --> Tassignments[("assignments")]
  P1 --> Tentity_allocations[("entity_allocations")]
  P1 --> Tsalary_structures[("salary_structures")]
  P1 --> Tleave_balances[("leave_balances")]
  P1 --> Tprovisioning_tasks[("provisioning_tasks")]
```

## Rules and limits

- Mandatory: code, name, joining date, location, department, PAN, bank account, IFSC (same as import).
- Day-1 checklist (SCRUM-79) is not built.

## Code and tests

- `services/hrms-core/backend/app/services/employees.py`
- `services/hrms-core/frontend/src/pages/Employees.jsx (EmployeeNew)`
- Test: `test_api_hv.py::test_onboard_and_convert_to_user`
