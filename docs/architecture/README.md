# Architecture (application, not AWS)

| Doc | What it shows |
|---|---|
| [01 Application layers](01-application-layers.md) | The five layers of the API and what each may do |
| [02 Folders and clients](02-folder-structure-and-clients.md) | Core vs client package, the client YAML, one database and one AWS account per client |
| [03 Request and sign-in flow](03-request-and-sign-in-flow.md) | From a Postman call to the database: token, client, role, scope, masking |
| [04 Company Setup and onboarding flow](04-company-setup-and-onboarding-flow.md) | The order to set up a client, versioned records, backdated approvals, onboarding |

AWS (API Gateway, Postgres, pipeline, monitoring) is owned by the infrastructure owner (PEAKHRMS-132).
