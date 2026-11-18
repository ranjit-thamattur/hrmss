#!/bin/sh
# Wait for the database, apply migrations and seed demo data (if SEED_DEMO=true), then start the API.
set -e
python -m app.startup
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*' ${UVICORN_EXTRA:-}
