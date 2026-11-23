# Handover: backend APIs for the screens (Neeraj)

Status 24-Nov-2026. Backend first (decision 0007): Company Setup (28 entities, Stages 1-3) and onboarding are REST APIs.
The screens are built on exactly these APIs; nothing in the backend needs to change for a screen to work.

## 1. Branch to pull
```bash
git clone https://github.com/ranjit-thamattur/hrmss.git      # or: git fetch origin
cd hrmss
git checkout qa && git pull          # after the PR is merged; until then:
# git checkout feature/PEAKHRMS-135-company-setup-onboarding
```
Start your own branch from `qa`: `git checkout -b feature/PEAKHRMS-171-legal-entity-screen`.

## 2. Set-up from a clean checkout (Windows, Git Bash) - full guide: [RUN-LOCALLY.md](../RUN-LOCALLY.md)
Needs Docker Desktop (running) and Git. Nothing else.
```bash
docker compose up --build -d          # first time ~2 min: Postgres + local Cognito + API, synthetic demo data
./scripts/smoke-test.sh               # waits for the API, signs in as every role; ends with SMOKE TEST PASSED
```
- API docs (every endpoint, try it out): http://localhost:8000/docs  ·  contract for code generation: http://localhost:8000/openapi.json
- Stop: `docker compose down` (data kept) · Start again from zero: `docker compose down -v` then `up --build -d`
- Logs: `docker compose logs -f api`
- If sign-in fails on your laptop (local Cognito): `AUTH_MODE=local docker compose up --build -d`

## 3. Test logins (synthetic, laptop only) - password `Peak@12345`
| Login | Role | What they see |
|---|---|---|
| admin@hotelvivek.local | master_admin | everything, can change everything |
| hr@hotelvivek.local | hr | all setup and people; can onboard and create logins (not master_admin) |
| hr.ooty@hotelvivek.local | hr, scoped to Ooty | only Ooty and the people working there |
| payroll@hotelvivek.local | payroll_preparer | view everything; can change payroll calendars |
| finance@hotelvivek.local | finance_approver | view everything; approves payroll calendars |
| hod@hotelvivek.local | hod | their team only; PAN / Aadhaar masked |
| employee@hotelvivek.local | employee | only themselves |

The screen should read `GET /api/auth/me` after sign-in: it returns the roles, scope and `permissions` (per resource: actions),
so buttons can be shown or hidden without hard-coding roles.

## 4. Postman
Import `postman/Peak-HRMS-Core.postman_collection.json` + `postman/local.postman_environment.json`, pick "Peak HRMS local (synthetic)",
Run collection. Folder 02 has a working request body for every entity - copy them for the forms.

## 5. What a screen needs to know
- Sign-in: `POST /api/auth/login` -> `{token}`; first sign-in with a temporary password returns `NEW_PASSWORD_REQUIRED` ->
  `POST /api/auth/new-password`. Send `Authorization: Bearer <token>` on every call.
- Every entity has the same endpoints (docs/features/02-company-setup.md): list with `as_of`, `include_inactive`, `q`, `page`, `size`
  and field filters; create; get; history; change with `effective_from`; deactivate / reactivate; end; Excel template and import.
- A list response is `{total, page, size, as_of, items}`. Each item has `rid` (use it in URLs), `status`
  (active / inactive / scheduled / ended), and for each link `x_rid` also `x` with the linked record's code and name
  (e.g. `state_rid` + `state`). `GET .../{rid}` adds `version`; `/history` lists all versions.
- `PUT` returns **200** (applied) or **202** (backdated: waiting for approval; show "sent for approval"). `DELETE` is always 405.
- Errors: `{"detail": "..."}` in plain language - show it as is. 401 sign in again, 403 no permission, 404 not found or outside the
  user's scope, 409 duplicate / conflict, 422 invalid input (pydantic list or a message).
- Field list and formats for every form: docs/data-dictionary.md (generated from the catalogue).
- Onboarding form: `POST /api/employee/add`; bulk upload: `POST /api/employee/import` with `dry_run` first (docs/features/06-onboarding.md).
- First screen: Legal entity (PEAKHRMS-171) - `/api/setup/legal-entities`.

## 6. Who to ask
Backend / APIs: Aryu. AWS, API Gateway, QA environment: Renjith (PEAKHRMS-132, 143-145). Design: Priyanka.
