# Architecture (application)

How the application is built and how data moves through it. AWS hosting, the pipeline and backups are owned by the infrastructure owner (SCRUM-132) and are not described here.

| Document | What it covers |
|---|---|
| [01-application-layers.md](01-application-layers.md) | Screens → API → services → rules → database, and what each layer may do |
| [02-folder-structure-and-clients.md](02-folder-structure-and-clients.md) | `services/hrms-core` vs client folders, tenant code, one database per client, where data may live |
| [03-request-and-sign-in-flow.md](03-request-and-sign-in-flow.md) | Sign-in, tokens, roles and scope on every request |
| [04-employee-lifecycle-flow.md](04-employee-lifecycle-flow.md) | Onboarding → user access → attendance → payroll → exit |
| [05-attendance-to-payroll-flow.md](05-attendance-to-payroll-flow.md) | Punches → days → paid days → payroll run → approvals → files |
| [06-monitoring-flow.md](06-monitoring-flow.md) | Health checks of the 5 core services and alert rules |

Related: decision records in [../decisions](../decisions), one document per feature in [../features](../features).
