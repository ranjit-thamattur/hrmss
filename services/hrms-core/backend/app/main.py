"""Peak HRMS core API: Company Setup, HR records, users, approvals and audit; plus the client package's own
APIs (e.g. /api/employee/add). OpenAPI contract at /openapi.json, interactive docs at /docs.
Backend first: the screens come later and use exactly these APIs (decision 0007).
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from .client_package import get_client_package
from .config import get_settings
from .routers import auth, setup, users

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version=settings.version,
                  description="HRMS core: Company Setup (entities 1-31, stage 1-2), employee onboarding, users and roles, "
                              "backdated-change approvals and the audit log. Records are versioned (valid_from/valid_to) and never deleted.")
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(IntegrityError)
    async def integrity_error(_: Request, exc: IntegrityError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": "This conflicts with existing data (duplicate or linked record)."})

    app.include_router(auth.router)
    app.include_router(setup.extra)
    for r in setup.routers:
        app.include_router(r)
    app.include_router(users.router)
    pkg = get_client_package()
    for r in getattr(pkg, "ROUTERS", []) if pkg else []:
        app.include_router(r)
    return app


app = create_app()
