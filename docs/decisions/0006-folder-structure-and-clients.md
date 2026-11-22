# 0006 - Folder structure, clients and scope

Status: accepted · 2026-11-18 · amended by 0007 (client YAML, monitoring removed) · Jira: PEAKHRMS-128, PEAKHRMS-131, PEAKHRMS-132

## Decision
1. **Folder structure**
   - `services/hrms-core/` - backend (and later frontend) common to every client.
   - `services/hotel_vivek_backend/` - Hotel Vivek only: `client.yaml` + the `hotel_vivek` package (its APIs, synthetic demo data).
   - `services/hotel_vivek_frontend/` - placeholder until the screens are built.
   - `docs/architecture/` - application layers and flows (not AWS). `docs/features/` - one document per feature.
2. **Client code** for Hotel Vivek is `HV`, set in `client.yaml`. The API loads the package named there and refuses to start if its code differs.
3. **One database per client** (`hrms_hv`). The database is stamped with the client code on first start; the API refuses another client's database.
4. **Synthetic data only on laptops; real client data only in QA/production.** Demo data loads only with `ENVIRONMENT=local|dev|test`.
5. **Scope of this repository:** the application only. AWS, the pipeline, backups and service monitoring belong to the infrastructure owner (PEAKHRMS-132).
6. **No chatbot inside HRMS.** After the demo an "Ask Brain" button will open the Brain (PEAKHRMS-131).
7. **Payroll is on hold** until the client's salary sheets arrive.
