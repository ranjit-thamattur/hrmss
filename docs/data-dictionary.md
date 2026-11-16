# Data dictionary (main tables)

| Table | What it holds |
|---|---|
| entities | Paying companies (PAN, TAN, EPF/ESI codes, which laws apply) |
| locations | Hotels / units, each under one entity, with weekly off day |
| departments, designations, grades, shifts, holidays, leave_types | Masters |
| employees | Employee master. PAN and bank encrypted; Aadhaar last 4 only |
| assignments | Dated location / department / designation / grade history |
| salary_structures | Dated salary components per employee |
| entity_allocations | Dated split of pay across entities (percent or fixed) |
| employee_documents | Documents with expiry dates; files in S3 (AWS) or local storage |
| change_requests | Employee-requested changes, approved by HR |
| app_users | People who can sign in: roles, entity/location scope, link to employee |
| provisioning_tasks | Cognito and biometric actions with status, attempts and last error |
| punches, roster, attendance_days, regularisations | Raw punches → daily attendance |
| leave_balances, leave_requests | Leave |
| monthly_inputs | One-off pay items per period |
| payroll_runs, payroll_lines | Runs with status, approvals, rule snapshot; one line per employee per entity |
| statutory_challans | Payment references for EPF, ESI, PT, LWF, TDS |
| exit_cases, clearance_tasks | Resignation to closure, with F&F |
| review_cycles, reviews, increments | Performance and increments |
| circulars, circular_reads, outbox | Communications |
| policy_versions, statutory_rule_versions, app_settings | Dated settings |
| audit_log | Append-only record of every change (database trigger blocks UPDATE/DELETE) |
| import_batches | Every import with totals and rejected rows |
