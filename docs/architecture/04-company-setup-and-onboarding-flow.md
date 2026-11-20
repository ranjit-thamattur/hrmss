# 04 Company Setup and onboarding flow

## Order of set-up (one client)
```
client.yaml -> Client (1), States (5), roles + permissions (27), backdated workflow (26)     automatic on first start
1 Legal entities (2) -> Locations (6) -> Entity at location (7) -> Departments (8) -> Department in entity (9)
2 Designations (10), Cost centres (11), Statutory registrations (3), Holiday calendars (14), Biometric devices (28), Payroll calendars (30)
3 Grades (19), Employment types (31), Shifts (20), Weekly offs (21), Leave types (22), Bank accounts (4), Policies (15), Number series (17)
4 Onboarding: Person (12) + Employment assignment(s) (18) + Reporting line(s) (13) + Login (16)
```

## Versioned records
- Create: version 1 from `valid_from` (a past start date is allowed for initial set-up).
- Change from a date: same day as the version -> corrected in place; later -> the version is closed the day before and a new one starts.
- Change from an earlier date than today (backdated) -> **202**, saved as a pending change. Another user with a role in the
  `backdated_change` workflow approves it (`/api/setup/changes/{id}/approve`); nobody approves their own request.
- Deactivate / reactivate from a date; `DELETE` is always 405. End a record (link, job) on a date.
- `GET ...?as_of=YYYY-MM-DD` shows the version in force on that day; `/history` lists all versions.

## Onboarding (`POST /api/employee/add`, Hotel Vivek package)
One transaction: person (required fields from `client.yaml`) -> each job checked (entity works at the location, department belongs to
the entity, pay shares <= 100%, one primary job) -> employee number from the entity's number series -> reporting lines -> optional login
(temporary password shown once). Any error = nothing saved.
