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
