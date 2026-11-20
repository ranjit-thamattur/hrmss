# 0003 – OpenAPI is the contract; biometric through an adapter

Status: accepted · 2026-11-13

## API
The backend is FastAPI. Its OpenAPI document (`/openapi.json`, browsable at `/docs`) is the contract between the React app and the API. Breaking changes need a new path or a version bump and a note in the PR.

## Biometric device
The vendor and API of the device are not yet confirmed. The app talks to it only through `services/integrations.py`:

| `BIOMETRIC_ADAPTER` | Behaviour |
|---|---|
| `excel` (default) | Punches arrive as the device's Excel export (Import → Biometric punches). Enrolment of a new employee becomes a *manual* task HR confirms. |
| `http` | Generic REST adapter: `GET {BIOMETRIC_API_URL}/punches?since=` and `POST /users`. Replace the field mapping once the vendor documents the API. |
| `mock` | For demos and tests. |

Night shifts that end after midnight count on the shift's start date. Missed punches are never filled in silently: see decision on the missed-punch rule in `open-decisions.md`.
