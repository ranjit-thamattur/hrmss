# hrms-core

Backend (`backend/`) and frontend (`frontend/`) common to every client. Nothing client-specific belongs here:
client names, demo data, KRA templates and texts live in `services/<client>_backend` and `services/<client>_frontend` (decision 0006).
Without a client package the API runs as the neutral `CORE` tenant (no demo data) and the web app uses `frontend/src/tenant-default`.
