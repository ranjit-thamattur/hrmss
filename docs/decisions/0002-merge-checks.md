# 0002 – Merge checks

Status: accepted · 2026-11-13

Every pull request into `qa` or `main` must pass `.github/workflows/ci.yml`:

| Check | Tool |
|---|---|
| Lint | ruff |
| Unit tests incl. payroll, attendance, import, F&F and monitoring | pytest in `services/hrms-core/backend/tests` |
| Hotel Vivek API flow tests (roles, masking, approvals order, lock immutability, client stamp) | pytest in `services/hotel_vivek_backend/tests` |
| No Peak Brain / chatbot code in HRMS | grep in CI |
| Migrations apply, match the models, and roll back | alembic upgrade / check / downgrade on Postgres 16 |
| Audit log cannot be edited | UPDATE on `audit_log` must fail |
| Front-end builds (core and Hotel Vivek) | vite build |
| Dependency scan | pip-audit, npm audit (high and above) |
| Images build | docker compose build |

Set these as required status checks in GitHub → Settings → Branches for `main` and `qa`.
