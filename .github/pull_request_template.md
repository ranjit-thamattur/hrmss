## What changed

<!-- One or two lines. Link the Jira ticket, e.g. SCRUM-116 -->

## Branch flow

- [ ] This is a feature branch into `qa`, **or** a release `qa` → `main`
- [ ] Branch was created from `main` (feature) and is up to date

## Checks

- [ ] CI is green (lint, tests incl. payroll tests, migration check, frontend build, dependency scan)
- [ ] Payroll rules changed? Payroll tests updated and the rule change recorded in `docs/payroll-rules.md`
- [ ] Database change? New Alembic migration added (no edits to old ones)
- [ ] No real employee data, passwords or keys in the change
- [ ] A decision record was added in `docs/decisions/` if this changes how we build
