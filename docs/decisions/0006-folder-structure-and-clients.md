# 0006 – Folder structure, clients (tenants) and scope

Status: accepted · 2026-11-18 · Jira: SCRUM-128, SCRUM-130, SCRUM-131, SCRUM-132

## Decision

1. **Folder structure**
   - `services/hrms-core/` – backend and frontend common to every client.
   - `services/hotel_vivek_backend/`, `services/hotel_vivek_frontend/` – Hotel Vivek only.
   - `docs/architecture/` – application layers and flows (not AWS). `docs/features/` – one document per feature.
2. **Tenant code** for Hotel Vivek is `HV`. The API loads the client package named in `TENANT_PACKAGE` and refuses to start if its code differs from `TENANT`.
3. **One database per client** (`hrms_hv`). The database is stamped with the client code on first start; the API refuses another client's database.
4. **Synthetic data only on laptops; real client data only in QA/production.** Demo data loads only with `ENVIRONMENT=local|dev|test`.
5. **Scope of this repository:** the application and its monitoring dashboard and alerts for the 5 core services (SCRUM-130). No CDK, deployment or AWS set-up here: AWS, the pipeline and backups belong to the infrastructure owner (SCRUM-132). The earlier `infra/` CDK folder was removed.
6. **No chatbot inside HRMS** (decided 17-Nov). Peak Brain is removed from screens and code. After the demo, an "Ask Brain" button will open the Brain, with HRMS data pushed to it; how data is pushed and how sign-in works are still to be designed (SCRUM-131).
7. **Payroll is on hold** until the client's salary sheets arrive (SCRUM-126); payroll code is not changed meanwhile.

## Why
A second client must be added without copying or changing the core. Separate databases keep each client's data apart by construction.

## Consequences
- Native runs set `TENANT`, `TENANT_PACKAGE` and `TENANT_PATH` (see `services/hrms-core/backend/.env.example`).
- Docker images are built from the `services/` folder with the client's Dockerfile.
- Adding a client = two new folders + a new database + a new user pool.
