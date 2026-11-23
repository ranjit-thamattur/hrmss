# hrms-core

The HRMS core, common to every client: Company Setup (entity catalogue), the basic operations on every record (create, change from a date,
deactivate, end, import, approve), users and roles, audit, and the rules module. Nothing client-specific belongs here
(CI fails on a client name). A client is configured by its YAML file and adds its own APIs in its own package (decision 0007).

- `backend/` - the API. See `../../docs/architecture/01-application-layers.md`.
- `frontend/` - placeholder: the common screens are built after the APIs (backend first).
