# 01 Application layers

```
 Postman / later the screens
        |  HTTPS + Bearer token
 1 Routers        app/routers/*.py, <client>/api/*.py   HTTP only: parse, call, commit, status codes (201, 202, 405)
        |
 2 Services       app/services/*.py                     business operations made of several records (onboarding, users)
        |
 3 Engine         app/core/engine.py + hooks.py         one record: create, change from a date, deactivate, end, approve
        |                                                (validation, the eleven rules, audit)
 4 Catalogue      app/core/specs.py                     the 26 entities as data: fields, codes, scope, overlaps
        |          -> models.py (generated), schemas.py (request bodies), routes, Excel templates, data dictionary
 5 Database       Postgres (one database per client)    versioned rows, append-only audit log
```

Rules of thumb
- A router never writes SQL; it calls a service or the engine and commits once.
- Every write goes through `engine.create / change / set_active / end`, so the rules apply the same way to the API, the Excel import
  and the demo data.
- A new entity = a new `Spec` in `specs.py`, then `python scripts/gen_models.py`. Its REST endpoints, schema and template appear automatically.
- Client-specific behaviour is in the client package and its YAML, never in the core.
- `app/rules/` holds the calculation rules carried over from the prototype (payroll, attendance, F&F); they are pure functions.
