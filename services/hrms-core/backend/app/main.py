"""Peak HRMS API. OpenAPI contract at /openapi.json, interactive docs at /docs (decision 0003)."""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from .config import get_settings
from .db import SessionLocal
from .routers import attendance, core, employees, imports, monitoring, org, payroll, people, statutory_exits, users
from .services.monitoring import REQUESTS, prune, run_checks

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
    task = asyncio.create_task(_monitor_loop()) if settings.monitor_interval_seconds > 0 else None
    yield
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def _monitor_once(prune_too: bool) -> None:
    with SessionLocal() as db:
        run_checks(db)
        if prune_too:
            prune(db)


async def _monitor_loop() -> None:
    """Health checks of the 5 core services every MONITOR_INTERVAL_SECONDS (SCRUM-130)."""
    n = 0
    await asyncio.sleep(5)
    while True:
        try:
            await asyncio.to_thread(_monitor_once, n % 60 == 0)
        except Exception as e:  # noqa: BLE001 - monitoring must never stop the API
            logging.getLogger("hrms.monitor").error("Monitor run failed: %s", e)
        n += 1
        await asyncio.sleep(settings.monitor_interval_seconds)


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan,
              description="Peak HRMS core API: employee master, attendance, payroll, statutory, exit, performance, self-service and monitoring.")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def request_stats(request: Request, call_next):
    t = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        if request.url.path.startswith("/api/") and not request.url.path.startswith("/api/health"):
            REQUESTS.add(status, (time.perf_counter() - t) * 1000)


@app.exception_handler(IntegrityError)
async def integrity_error(_: Request, exc: IntegrityError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": "This conflicts with existing data (duplicate or linked record)."})


for r in (core, org, employees, imports, users, attendance, payroll, statutory_exits, people, monitoring):
    app.include_router(r.router)
