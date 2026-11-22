# 0005 – Three paying entities, split salaries, dated records

Status: accepted · 2026-11-13

- Hotel Vivek pays staff from three entities (demo codes VHPL, VRL, VFS). Each location belongs to one entity.
- An employee's pay can be split across entities by percent or fixed amount (`entity_allocations`), each with effective-from/to dates. Each entity runs its own payroll and its own statutory files.
- Statutory basis is configurable per rule set: `combined` (compute on full pay, share proportionally) or `per_entity`. The sample rules use `combined`; the auditor must confirm.
- Salary structures, assignments, allocations, policies and statutory rules are all **dated versions**: a change never rewrites history, and a payroll for an old month uses the values in force then. A locked payroll keeps a snapshot of the rules it used.
- Payroll is deterministic code, never AI. Negative pay is blocked. HR then Finance approve, then the run locks and becomes read-only; attendance for that month locks with it.
