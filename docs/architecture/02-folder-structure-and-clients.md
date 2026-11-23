# 02 Folders and clients

```
hrmss/
  docker-compose.yml               laptop stack: db + cognito-local + api (synthetic data)
  postman/                         collection, environment, sample Excel  (generated: scripts/make_postman.py)
  docs/                            architecture, features, decisions, data dictionary (generated: scripts/make_docs.py)
  scripts/                         apply-update, make_postman, make_docs
  services/
    hrms-core/backend/             THE CORE (no client name in it)
      app/core/                    catalogue, engine, rules of dating, access, audit, import, numbering, storage, identity
      app/routers/                 /api/auth, /api/setup/*, /api/hr/*, /api/users
      app/services/                onboarding, users
      app/rules/                   payroll / attendance / F&F rules (from the prototype)
      alembic/                     migrations
      tests/                       eleven rules, catalogue, dating, schemas, rules; test clients A/B/C
    hotel_vivek_backend/           HOTEL VIVEK ONLY
      client.yaml                  code HV, database hrms_hv, domain, AWS account, onboarding rules
      hotel_vivek/client.py        CODE, ROUTERS, load_demo
      hotel_vivek/api/employees.py /api/employee/add and the employee APIs
      hotel_vivek/demo.py          synthetic demo data (laptops only)
      tests/                       onboarding tests
    hrms-core/frontend/            placeholder (screens come after the APIs)
    hotel_vivek_frontend/          placeholder
```

## Adding a client
1. Copy `hotel_vivek_backend/` to `<client>_backend/`, rename the package, set `CODE`.
2. Write its `client.yaml` (code, name, database name, domain, AWS account, onboarding rules).
3. Infrastructure creates its database and runs the image in the client's own AWS account with `CLIENT_CONFIG` pointing at the YAML.
4. First start: the client is created from the YAML with India's states, default roles and permissions, and the backdated-change workflow.
5. `python -m app.admin create-admin EMAIL "Name"`, then set up the company through the APIs or Excel imports.
