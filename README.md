# Peak HRMS

Standalone HR, attendance and payroll application. First client: **Hotel Vivek (tenant code HV)** – 3 paying entities, 5 locations, about 256 staff.

**Stack:** React 18 (Vite) · Python 3.12 FastAPI · PostgreSQL 16 · Cognito (cognito-local in Docker) · Docker Compose.
AWS hosting, the deployment pipeline and backups are owned by the infrastructure owner (SCRUM-132) and are not in this repository.

## Folder structure (SCRUM-128, decision 0006)

```
services/
  hrms-core/backend/        API common to every client (FastAPI, migrations, core tests)
  hrms-core/frontend/       Web app common to every client (React, nginx)
  hotel_vivek_backend/      Hotel Vivek only: client package, demo data, tests, sample Excel files
  hotel_vivek_frontend/     Hotel Vivek only: names, texts, languages, theme
docs/
  architecture/             application layers and flows
  features/                 one document per feature (SCRUM-129)
  decisions/                decision records
scripts/                    apply-update.sh (Git Bash), apply-update.ps1 (PowerShell)
```

Rules: one database per client (`hrms_hv`); synthetic data only on laptops, real client data only in QA/production; no chatbot inside HRMS (an "Ask Brain" link comes after the demo, SCRUM-131).

## Run on a laptop (Docker – recommended)

```bash
docker compose up --build
```

- App: http://localhost:8080 · API docs: http://localhost:8000/docs · Monitoring: http://localhost:8080/monitor (master admin)
- First start loads 256 **synthetic** employees and these users (password `Peak@12345`):
  `admin@hotelvivek.local`, `hr@…`, `payroll@…`, `finance@…`, `hod@…`, `employee@…`

`docker compose down` stops it; `docker compose down -v` wipes the laptop database and the local Cognito users.

## Run without Docker

API (Python 3.12), from `services/hrms-core/backend`:

```bash
py -3.12 -m venv .venv
source .venv/Scripts/activate          # PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
cp .env.example .env                   # TENANT=HV, TENANT_PACKAGE=hotel_vivek, SQLite hrms_hv.db
alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload --port 8000
```

Web (Node 20), second terminal:

```bash
cd services/hrms-core/frontend && npm install     # once
cd ../../hotel_vivek_frontend && npm run dev      # http://localhost:5173 with Hotel Vivek texts
```

## Tests

```bash
cd services/hrms-core/backend && ruff check . && pytest              # core: payroll, attendance, imports, F&F, monitoring
cd ../../hotel_vivek_backend && pytest                                 # Hotel Vivek end-to-end API tests
```

CI (`.github/workflows/ci.yml`) also checks migrations on Postgres, the audit-log lock, both front-end builds, dependency scans, the Docker build, and that no Peak Brain/chatbot code is present.

## Branches

`main` (base) → `qa` (created from main) → `feature/*`. PRs go feature → qa, then qa → main (decision 0001).
To apply a new codebase zip on a new branch (Git Bash):

```bash
./scripts/apply-update.sh ~/Downloads/peak-hrms-full.zip feature/SCRUM-xxx-short-name "SCRUM-xxx: what changed"
```

## Before go-live

Read `docs/open-decisions.md`. Statutory rates are **sample values** to be confirmed by the client's auditor, the missed-punch rule has no default on purpose, and payroll work is on hold until the client's salary sheets arrive.
