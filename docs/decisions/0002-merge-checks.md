# 0002 – Merge checks

Status: accepted · 2026-11-13

Every pull request into `qa` or `main` must pass `.github/workflows/ci.yml`:

| Check | Tool |
|---|---|
| Lint | ruff |
| Tests: eleven rules, catalogue, dating, rules module; Hotel Vivek onboarding | pytest in `services/hrms-core/backend/tests` and `services/hotel_vivek_backend/tests` |
| Models match the entity catalogue | `scripts/gen_models.py --check` |
| No client name in the core; no Peak Brain / chatbot code | grep in CI |
| Migrations apply and roll back | alembic upgrade / downgrade on Postgres 16 |
| Audit log cannot be edited | UPDATE on `audit_log` must fail |
| Every API call in the Postman collection | newman |
| Dependency scan | pip-audit |
| Images build | docker compose build |

Set these as required status checks in GitHub → Settings → Branches for `main` and `qa`.
