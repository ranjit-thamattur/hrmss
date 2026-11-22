# 06 Onboarding an employee (Hotel Vivek APIs)

These live in `services/hotel_vivek_backend/hotel_vivek/api/employees.py` and use the core's building blocks.

| Call | What it does |
|---|---|
| `POST /api/employee/add` | person + one or more jobs + optional login, all or nothing -> 201 with employee numbers and the temporary password |
| `GET /api/employee?q=&legal_entity_rid=&location_rid=&department_rid=&designation_rid=` | people in your scope with their current jobs |
| `GET /api/employee/{person_rid}?as_of=` | profile: person, jobs (current and past), reporting lines, total pay share, login |
| `PUT /api/employee/{person_rid}` | change person details from a date |
| `POST /api/employee/{person_rid}/assignments` | add another job |
| `PUT /api/employee/{person_rid}/assignments/{rid}` | transfer / promotion / pay share from a date |
| `POST /api/employee/{person_rid}/assignments/{rid}/end` | end a job |
| `POST /api/employee/{person_rid}/login` | give the person a login (one per person) |
| `POST /api/employee/{person_rid}/deactivate` | only when no job is active; the login is disabled |

Checks: required person fields come from `client.yaml` (`onboarding.required_person_fields`; Hotel Vivek: first and last name,
date of birth, gender, phone); duplicate PAN or same name + date of birth -> 409; the legal entity must work at the location and the
department must belong to the entity on the joining date; pay shares of overlapping jobs <= 100%; one primary job; the employee number
comes from the entity's number series.

Example body:
```json
{
  "person": {"first_name": "Asha", "last_name": "Demo", "date_of_birth": "1996-05-05", "gender": "female", "phone": "+91 90000 12345"},
  "assignments": [
    {"legal_entity_rid": 1, "location_rid": 1, "department_rid": 1, "designation_rid": 3, "pay_share": 60, "is_primary": true, "reports_to_person_rid": 4},
    {"legal_entity_rid": 2, "location_rid": 2, "department_rid": 1, "designation_rid": 3, "pay_share": 40}
  ],
  "login": {"email": "asha@hotelvivek.local", "roles": ["employee"]}
}
```

## Employee master import (PEAKHRMS-125, PEAKHRMS-42)

| Call | What it does |
|---|---|
| `GET /api/employee/import/template.xlsx` | template: one row per job, "How to" sheet; this client's required columns highlighted |
| `POST /api/employee/import` (multipart: `file`, `dry_run`, `mapping`) | imports people + jobs from Excel or CSV |

- One row = one job. Rows with the same `person_ref` are one person with several jobs (e.g. 60/40 across two entities).
- References by code: `legal_entity_code`, `location_code`, `department_code`, `designation_code` (required), `grade_code`,
  `employment_type_code`, `cost_centre_code`, `shift_code`, `weekly_off_code`; manager by `reports_to_employee_number`
  (already in the system or on an earlier row); optional `login_email` + `login_roles` (not created on a dry run).
- Each person goes through the same onboarding as `/api/employee/add`, so every rule applies; a person is imported whole or not at all.
- **Column mapping:** use the client's own headers by sending `mapping` as JSON, e.g. `{"Emp Name": "first_name", "DOJ": "joining_date"}`.
- **CSV** works too, so a Google Sheet can be imported with File > Download > Comma-separated values.
- The report lists every person imported (employee numbers, temporary passwords for new logins - shown once) and every rejected
  person with its rows and reasons. `imported + rejected = total` rows (`counts_reconcile: true`). `dry_run=true` saves nothing.

Sample (synthetic): `postman/samples/employee-master-import.xlsx` - 9 rows: 4 rows (3 people, one with two jobs) import,
5 rows are rejected (entity not at that site, unknown location, missing phone, pay shares over 100%).
