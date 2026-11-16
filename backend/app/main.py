"""Peak HRMS API. OpenAPI contract at /openapi.json, interactive docs at /docs (decision 0003)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from .config import get_settings
from .db import SessionLocal
from .routers import attendance, core, employees, imports, org, payroll, people, statutory_exits, users

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auth_mode == "cognito" and settings.cognito_bootstrap:
        from .services.identity import get_identity

        with SessionLocal() as db:
            try:
                get_identity().bootstrap(db)
            except Exception as e:  # noqa: BLE001 - API still starts; /health shows the problem
                logging.getLogger("hrms").error("Cognito bootstrap failed: %s", e)
    yield


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan,
              description="HRMS for Hotel Vivek: employee master, attendance, payroll, statutory, exit, performance and self-service.")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(IntegrityError)
async def integrity_error(_: Request, exc: IntegrityError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": "This conflicts with existing data (duplicate or linked record)."})


for r in (core, org, employees, imports, users, attendance, payroll, statutory_exits, people):
    app.include_router(r.router)
