# Peak HRMS – Hotel Vivek

Standalone HR, attendance and payroll system for Hotel Vivek: 3 paying entities, 5 locations, about 256 staff.

**Stack:** React 18 (Vite) · Python 3.12 FastAPI · PostgreSQL 16 · AWS Cognito (cognito-local in Docker) · Docker Compose · AWS CDK (ECS Fargate, RDS, S3, CloudFront).

## What it does

| Area | Highlights |
|---|---|
| Employees | Manual onboarding, Excel import with a rejected-rows report (imported + rejected = rows in file), documents with expiry, change requests, dated history |
| Users & access | Employee ≠ user. Converting creates the Cognito account (with role groups) and the biometric enrolment, each with its own status and retry. Six roles, entity/location scope, masked salary/PAN/Aadhaar/bank |
| Attendance | Biometric adapter (Excel export, HTTP, mock), night shifts across midnight, missed punches, late, OT approval by HOD, regularisation, roster |
| Leave | Balances, HOD then HR approval |
| Payroll | Deterministic rules (PF, ESI, PT, LWF, TDS, OT), split salaries across entities, per-line checks, preparer → HR → Finance → lock; bank file, Tally XML, EPF ECR, ESI, payslip PDFs |
| Statutory | Due-date calendar from locked runs, challan entry |
| Exits | Clearance, F&F (gratuity, leave encashment, notice), letters, access removal |
| Performance | Review cycles, merit-matrix increments with GM approval that become dated salary versions |
| Reports, circulars, audit | 8 static reports with CSV, multilingual circulars (outbox), append-only audit trail |

## Run it (Docker – recommended)

```powershell
docker compose up --build
```

- App: http://localhost:8080
- API docs (OpenAPI): http://localhost:8000/docs
- First start seeds 256 **synthetic** employees and these users (password `Peak@12345`):
  `admin@hotelvivek.local`, `hr@…`, `payroll@…`, `finance@…`, `hod@…`, `employee@…`

Stop with `docker compose down`; wipe all data with `docker compose down -v`.

## Run it without Docker

Backend (Python 3.12):

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload --port 8000
```

Frontend (Node 20), in a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Native mode uses SQLite and app-held passwords (`AUTH_MODE=local`).

## Tests and checks

```powershell
cd backend
ruff check .
pytest -q
```

CI (`.github/workflows/ci.yml`) also checks migrations on Postgres, the audit-log lock, the front-end build, dependency scans and the Docker build.

## Deploy to AWS (CDK)

```powershell
cd frontend; npm install; npm run build; cd ..\infra
py -3.12 -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt
npm install -g aws-cdk@2.170.0
cdk bootstrap                      # once per account/region
cdk deploy -c env=dev              # or qa / prod
cdk destroy -c env=dev             # remove dev/qa (prod keeps its database and files)
```

Outputs include the app URL. For `prod` (no demo data) create the first admin inside the API container:

```powershell
aws ecs execute-command --cluster <ClusterName> --task <task-id> --container api --interactive --command "python -m app.admin setup-org"
aws ecs execute-command --cluster <ClusterName> --task <task-id> --container api --interactive --command "python -m app.admin create-admin you@company.com 'Your Name'"
```

## Branches

`main` (base, production) → `qa` (created from main) → `feature/*` (created from main). PRs go feature → qa, then qa → main. See `docs/decisions/0001-branching-main-qa-feature.md`. To apply a new codebase zip on a feature branch: `.\scripts\apply-update.ps1 -Zip <zip> -Branch feature/<name>`.

## Layout

```
backend/    FastAPI app (app/domain = pure payroll/attendance/import/F&F rules, app/routers = API), Alembic, tests
frontend/   React app (src/pages), nginx config for the container
infra/      AWS CDK app (one stack per environment)
docs/       Decision records, open decisions, payroll rules, data dictionary
data/samples/  Synthetic Excel files for import testing
scripts/    apply-update.ps1, make_samples.py
```

## Before go-live

Read `docs/open-decisions.md`. The statutory rates are **sample values** and must be confirmed by Hotel Vivek's auditor, and the missed-punch rule has no default on purpose.
