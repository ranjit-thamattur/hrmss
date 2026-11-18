# Employee lifecycle flow

```mermaid
flowchart LR
  A["Onboard employee<br/>(manual or Excel import)"] --> B["Employee record<br/>assignment, salary, entity split, leave balances"]
  B --> C["Biometric enrolment task"]
  B --> D{"Needs software?"}
  D -- yes --> E["Give software access<br/>Cognito account + role groups"]
  D -- no --> F["Employee only<br/>(punches on device)"]
  C --> G["Attendance from punches"]
  E --> H["Self-service: payslips, leave, fixes, resign"]
  G --> I["Payroll each month"]
  B --> J["Changes: change requests, new salary, increments (dated)"]
  J --> I
  H --> K["Resignation"]
  B --> K
  K --> L["Clearance → F&F → letters"]
  L --> M["Close: disable sign-in and biometric"]
```

| Stage | Tables | Feature doc |
|---|---|---|
| Onboard | employees, assignments, entity_allocations, salary_structures, leave_balances, provisioning_tasks | [08](../features/08-onboarding.md), [11](../features/11-excel-imports.md) |
| Access | app_users, provisioning_tasks | [03](../features/03-users-and-provisioning.md) |
| Changes | change_requests, salary_structures, entity_allocations, increments | [10](../features/10-change-requests.md), [12](../features/12-salary-and-split.md), [24](../features/24-increments.md) |
| Exit | exit_cases, clearance_tasks | [21](../features/21-exits-and-fnf.md) |
