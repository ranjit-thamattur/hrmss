# Application layers

```mermaid
flowchart TB
  subgraph WEB["Web app: React (services/hrms-core/frontend)"]
    P["Pages: src/pages/*.jsx"] --> L["lib.jsx: API calls, routing, session"]
    T["Client folder via @tenant alias:<br/>services/hotel_vivek_frontend/tenant.js, theme.css"] -.-> P
  end
  subgraph API["API: FastAPI (services/hrms-core/backend/app)"]
    R["routers/*: HTTP endpoints, OpenAPI contract"] --> D["deps.py: who is signing in"]
    R --> SV["services/*: access, audit, identity, payroll, attendance, monitoring, integrations"]
    SV --> DM["domain/*: pure rules (payroll engine, attendance engine, imports, F&F, outputs)"]
    SV --> MD["models.py: SQLAlchemy tables"]
    TN["tenant.py: loads the client package<br/>(services/hotel_vivek_backend/hotel_vivek)"] -.-> R
  end
  L -- "HTTPS /api/* (JSON, Bearer token)" --> R
  MD --> DB[("PostgreSQL: one database per client, e.g. hrms_hv")]
  SV --> COG["Cognito user pool (cognito-local on laptops)"]
  SV --> BIO["Biometric adapter: Excel export, HTTP device API, or mock"]
  SV --> FS["File storage: local folder or S3"]
  SV --> OB["Outbox table: WhatsApp / email messages to send"]
```

| Layer | Folder | May do | Must not do |
|---|---|---|---|
| Pages | `frontend/src/pages` | Show data, call the API, hide menu items the role lacks | Decide access (the API does), hold business rules |
| Client folder (web) | `services/<client>_frontend` | Names, texts, languages, theme | Change screens or behaviour |
| Routers | `backend/app/routers` | Validate input, check permission, call services, return JSON | Calculate pay or attendance directly |
| Services | `backend/app/services` | Database work, access rules, audit, external systems | Hard-code a client's data |
| Domain | `backend/app/domain` | Pure calculations with no database (fully unit-tested) | Read the database or the clock directly |
| Models + migrations | `backend/app/models.py`, `alembic/versions` | Define tables; every change gets a migration | Edit an old migration |
| Client package (API) | `services/<client>_backend/<package>` | Client code and name, demo data for laptops, KRA templates, import examples | Contain real client data |

Every change written by a service also writes a row to `audit_log` (append-only, enforced by a database trigger).
