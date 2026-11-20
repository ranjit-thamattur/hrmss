# 01 Sign-in, users and roles

| Call | What it does |
|---|---|
| `POST /api/auth/login` | email + password -> `{token}` or `{challenge: NEW_PASSWORD_REQUIRED, session}` |
| `POST /api/auth/new-password` | email, new_password, session -> `{token}` |
| `GET /api/auth/me` | the login, roles, scope, client and the permissions summary |
| `GET/POST /api/users`, `GET/PUT /api/users/{id}` | list, create (temporary password shown once), change roles / scope |
| `POST /api/users/{id}/deactivate`, `/activate`, `/reset-password` | `DELETE` is 405 |

- One login per person (`person_rid`), whatever the number of jobs.
- Roles are rows in **role permissions (27)**: role, resource, actions (view, create, change, deactivate, approve, import, export),
  scope (all, scoped, team, self), masked fields. Default roles: master_admin, hr, payroll_preparer, finance_approver, hod, employee.
- Only a master admin can give the master_admin role. Nobody can deactivate their own login.
- Demo logins (laptops only, password `Peak@12345`): admin@, hr@, hr.ooty@ (Ooty only), payroll@, finance@, hod@, employee@hotelvivek.local.
