# 05 Audit log

- Every create, change, deactivate, end, approval, rejection, login change and client-YAML change writes one row:
  when, who, action, entity, record, before, after, reason, approved by.
- Append-only: on Postgres a trigger refuses UPDATE and DELETE on `audit_log` (checked in CI).
- Sensitive values (PAN, Aadhaar, account numbers, identity documents) are masked in the log.
- `GET /api/setup/audit?resource=&rid=&actor=&page=&size=` (master admin, HR).
