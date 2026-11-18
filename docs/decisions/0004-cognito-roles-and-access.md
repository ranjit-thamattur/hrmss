# 0004 – Sign-in with Cognito; roles and scope enforced in the API

Status: accepted · 2026-11-13

- An **employee** is a record on the employee master. A **user** is someone who can sign in. Converting an employee into a user creates the account in Cognito (with groups) and is a separate step with its own status and retry. Every employee also gets a biometric enrolment task. On exit both are disabled.
- Local development uses `cognito-local` in Docker; QA and production use the client's own user pool, set up by the infrastructure owner (SCRUM-132). `AUTH_MODE=local` (passwords kept by the app) exists only for quick native runs and tests.
- Roles (SCRUM-116): master admin, HR, payroll preparer, finance approver, HOD, employee. Permissions are in `services/hrms-core/backend/app/services/access.py`; the menu hides what a role cannot do, but **the API enforces every rule**.
- Scope: a user can be limited to entities and/or locations. HODs see themselves and their team; employees see only themselves.
- Salary, PAN, Aadhaar and bank are masked for HOD and employee roles (except their own record). PAN and bank are encrypted at rest; only the last 4 Aadhaar digits are stored.
- Separation of duties: the person who prepares a payroll cannot HR-approve or finance-approve it; finance approval must be a third person.
