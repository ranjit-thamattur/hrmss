# 0002 – Merge checks

Status: accepted · 2026-11-13

Every pull request into `qa` or `main` must pass `.github/workflows/ci.yml`:

| Check | Tool |
|---|---|
| Lint | ruff |
| Unit tests incl. payroll, attendance, import and F&F rules | pytest (`tests/test_payroll_engine.py`, `tests/test_attendance_imports_fnf.py`) |
| API flow tests (roles, masking, approvals order, lock immutability) | pytest (`tests/test_api.py`) |
| Migrations apply, match the models, and roll back | alembic upgrade / check / downgrade on Postgres 16 |
| Audit log cannot be edited | UPDATE on `audit_log` must fail |
| Front-end builds | vite build |
| Dependency scan | pip-audit, npm audit (high and above) |
| Images build | docker compose build |

Set these as required status checks in GitHub → Settings → Branches for `main` and `qa`.
