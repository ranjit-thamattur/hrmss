# Peak HRMS

HRMS core + client backends. First client: **Hotel Vivek (client code HV)**.
Current stage (design review 18-Nov, decision 0007): **Company Setup, then onboarding - backend first.** All CRUD is REST, tested
with Postman and pytest. No screens yet (built on these APIs next). Monitoring has been removed from the application.

**Stack:** Python 3.12 · FastAPI · SQLAlchemy 2 · PostgreSQL 16 (one database per client) · Cognito (cognito-local on laptops) · Docker Compose.
AWS (API Gateway, Postgres, pipeline) is owned by the infrastructure owner (PEAKHRMS-132); each client runs in its own AWS account.

## Folders
```
services/hrms-core/backend/     the core: Company Setup, entities, basic operations, rules module (no client name in it)
services/hotel_vivek_backend/   Hotel Vivek: client.yaml + hotel_vivek package (/api/employee/... APIs, synthetic demo data)
postman/                        Postman collection + environment + sample Excel
docs/                           architecture, features, decisions, data dictionary (generated)
scripts/                        apply-update.sh/.ps1, make_postman.py, make_docs.py
```

## Run on a laptop (Docker)
```bash
docker compose up --build -d
curl http://localhost:8000/api/health        # {"status":"ok", "client":"HV", ...}
```
- API docs (try every call): http://localhost:8000/docs
- First start loads **synthetic** data: 3 legal entities, 5 locations, 27 people (one with two jobs, 60/40), and these logins,
  password `Peak@12345`: `admin@hotelvivek.local`, `hr@`, `hr.ooty@` (Ooty only), `payroll@`, `finance@`, `hod@`, `employee@`.
- `docker compose logs -f api` to watch it, `docker compose down` to stop, `docker compose down -v` to wipe the laptop database.

## Test
```bash
# Postman: import postman/*.json, pick "Peak HRMS local (synthetic)", Run collection (see docs/features/07-postman-testing.md)
cd services/hrms-core/backend && pip install -r requirements-dev.txt && ruff check . && pytest -q   # eleven rules + catalogue + rules
cd ../../hotel_vivek_backend && pytest -q                                                       # onboarding + employee APIs
```

## Changing the catalogue
Add or change an entity in `services/hrms-core/backend/app/core/specs.py`, then:
```bash
cd services/hrms-core/backend && python scripts/gen_models.py      # regenerates app/models.py (CI checks it)
cd ../../.. && python scripts/make_docs.py && python scripts/make_postman.py
```

## Branches
`main` -> `qa` -> `feature/*`. PRs go feature -> qa, then qa -> main (decision 0001). Apply a codebase zip on a new branch (Git Bash):
```bash
./scripts/apply-update.sh ~/Downloads/hrmss.zip feature/PEAKHRMS-xxx-short-name "PEAKHRMS-xxx: what changed" qa
```
The earlier prototype (screens, attendance, payroll, exits) is in git tag `prototype-v1`.

## Rules for data
Synthetic data only on laptops; real client data only in QA/production (in the client's own AWS account). Never commit real data.
Read `docs/open-decisions.md` before go-live.
