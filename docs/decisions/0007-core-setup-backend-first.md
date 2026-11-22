# 0007 - HRMS core: Company Setup first, backend first, one YAML per client

Status: accepted · 2026-11-18 (design review "HRMS Core: Company Setup") · Jira: PEAKHRMS-135, 136-141, 147-170 (built); PEAKHRMS-132, 131 (others)

## Decision
1. **Company Setup comes first, then onboarding.** Stage 1 entities: 1 Client, 2 Legal entity, 5 State, 6 Location, 7 Entity at location, 8 Department.
   Stage 2: 9, 10, 11, 12, 3, 14, 28, 30. Stage 3: 18, 13, 19, 20, 21, 4, 15, 16, 17, 22, 31, 26, 27, 29. Later: 23, 24, 25.
2. **What lives where.** `hrms-core` holds Company Setup, the entities, the basic operations (create / change from a date / deactivate /
   end / import / approve), the rules module and (later) the common screens. Each client backend (`hotel_vivek_backend`) holds that client's
   APIs and business operations, e.g. `POST /api/employee/add`.
3. **Backend first.** REST APIs are shown in Postman (`postman/`) and `/docs`. No frontend yet; screens are built on these APIs afterwards.
4. **A new client goes live with a YAML file** (`client.yaml`: code, name, country, currency, database, domain, AWS account, package,
   onboarding rules) plus its own database. No change to the core. The core contains no client name (checked in CI).
5. **Each client's HRMS runs in that client's own AWS account**; Peak Brain stays in Peak's account (Ask Brain after the demo, PEAKHRMS-131).
6. **People model:** one Person per human, one login per person, one Employment assignment per job with its pay share; the reporting line
   sits on the employment assignment.
7. **Eleven rules** with acceptance tests (`services/hrms-core/backend/tests/test_setup_api.py`, Postman folder 03): client from the login;
   effective dating; no overlaps / controlled backdating; deactivate, never delete; unique codes (not case-sensitive); append-only audit log;
   data scope; masking; Excel import; dependency checks; client isolation.
8. **Monitoring is removed** from the application (it was PEAKHRMS-130). Health of the running service is the infrastructure owner's
   CloudWatch set-up; the API keeps `/api/health`.
9. The earlier prototype (attendance, payroll, exits and the React screens on the old employee model) is kept in git tag `prototype-v1`.
   Its calculation rules are carried over as `app/rules/` and will be wired to the new entities in later stages. Payroll stays on hold
   until the salary sheets arrive.

## Why
The prototype mixed a client's data model into the core. The design review asked for a clean core that any client can use through
configuration, proven with plain API calls before any screen is built.

## Consequences
- Tables are generated from the catalogue (`scripts/gen_models.py`); CI fails if `app/models.py` is out of date.
- Postgres, the API Gateway and the pipeline are set up by Renjith (PEAKHRMS-132) in each client's AWS account.
- Test clients A, B and C (`tests/clients/*.yaml`) cover one entity, a hotel group with split pay, and an entity with no PF/ESI.
