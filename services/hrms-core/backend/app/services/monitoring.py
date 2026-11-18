"""Monitoring of the 5 core services (SCRUM-130).

    web        the React app (nginx)            GET MONITOR_WEB_URL (e.g. http://web/healthz)
    api        this FastAPI service             request count, error rate and p95 time over 15 minutes
    database   PostgreSQL / SQLite              SELECT 1 time, size and connections
    signin     Cognito (or app passwords)       user-pool call time; failed sign-in provisioning tasks
    biometric  biometric feed / adapter         device reachable (http adapter); age of the newest punch

A background task in the API runs the checks every MONITOR_INTERVAL_SECONDS and stores one sample per
service. Alert rules:
    down on 2 checks in a row           -> critical alert
    degraded or down on 3 checks in a row -> warning alert (raised to critical if it goes down)
    up again                            -> open alerts for that service are resolved
New alerts are logged and queued in the outbox (email) for MONITOR_ALERT_EMAILS.

If the API itself is down, nothing inside it can raise an alert: the container health check and the
infrastructure monitoring (SCRUM-132) cover that case.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from .. import models as m
from ..config import get_settings

log = logging.getLogger("hrms.monitor")
settings = get_settings()

SERVICES = {
    "web": "Web app",
    "api": "API",
    "database": "Database",
    "signin": "Sign-in (Cognito)",
    "biometric": "Biometric feed",
}
STARTED = time.time()


# ---------------------------------------------------------------- API request metrics (filled by middleware in main.py)
class RequestStats:
    def __init__(self, window_s: int = 900) -> None:
        self.window = window_s
        self.items: deque[tuple[float, int, float]] = deque()
        self.lock = Lock()

    def add(self, status: int, ms: float) -> None:
        now = time.time()
        with self.lock:
            self.items.append((now, status, ms))
            while self.items and self.items[0][0] < now - self.window:
                self.items.popleft()

    def summary(self) -> dict[str, Any]:
        now = time.time()
        with self.lock:
            rows = [x for x in self.items if x[0] >= now - self.window]
        times = sorted(x[2] for x in rows)
        p95 = times[min(len(times) - 1, int(len(times) * 0.95))] if times else 0
        errors = sum(1 for x in rows if x[1] >= 500)
        return {"requests_15m": len(rows), "errors_15m": errors, "error_rate": round(errors / len(rows), 3) if rows else 0.0, "p95_ms": round(p95)}


REQUESTS = RequestStats()


# ---------------------------------------------------------------- checks
def _result(status: str, ms: float | None, detail: str, **metrics: Any) -> dict[str, Any]:
    return {"status": status, "latency_ms": None if ms is None else round(ms), "detail": detail[:300], "metrics": metrics}


def check_api(db: Session) -> dict[str, Any]:
    s = REQUESTS.summary()
    s.update(uptime_s=round(time.time() - STARTED), version=settings.version)
    if s["requests_15m"] >= 20 and s["error_rate"] > 0.05:
        return _result("degraded", s["p95_ms"], f"{s['errors_15m']} server errors in {s['requests_15m']} requests (15 min)", **s)
    if s["p95_ms"] > 2000:
        return _result("degraded", s["p95_ms"], f"Slow: 95% of requests under {s['p95_ms']} ms", **s)
    return _result("up", s["p95_ms"], f"{s['requests_15m']} requests in 15 min, {s['errors_15m']} errors", **s)


def check_database(db: Session) -> dict[str, Any]:
    t = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
        ms = (time.perf_counter() - t) * 1000
        metrics: dict[str, Any] = {"engine": db.get_bind().dialect.name}
        if metrics["engine"] == "postgresql":
            metrics["size_mb"] = round(db.scalar(text("SELECT pg_database_size(current_database())")) / 1048576, 1)
            metrics["connections"] = db.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"))
        metrics["employees"] = db.scalar(select(func.count(m.Employee.id)))
        return _result("degraded" if ms > 500 else "up", ms, "Slow response" if ms > 500 else "Responding", **metrics)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        return _result("down", None, f"Not reachable: {e.__class__.__name__}")


def check_signin(db: Session) -> dict[str, Any]:
    failed = db.scalar(select(func.count(m.ProvisioningTask.id)).where(m.ProvisioningTask.target == "identity", m.ProvisioningTask.status == "failed"))
    users = db.scalar(select(func.count(m.AppUser.id)).where(m.AppUser.is_active.is_(True)))
    if settings.auth_mode != "cognito":
        return _result("up", None, "App-held passwords (AUTH_MODE=local)", mode="local", active_users=users, failed_tasks=failed)
    from .identity import get_identity

    idp = get_identity()
    t = time.perf_counter()
    try:
        pool, _ = idp.ids(db)
        idp.client.describe_user_pool(UserPoolId=pool)
        ms = (time.perf_counter() - t) * 1000
    except Exception as e:  # noqa: BLE001
        return _result("down", None, f"Cognito not reachable: {getattr(e, 'detail', None) or e.__class__.__name__}", mode="cognito", failed_tasks=failed)
    if failed:
        return _result("degraded", ms, f"{failed} sign-in accounts failed to create (Users & access → Provisioning)", mode="cognito",
                       active_users=users, failed_tasks=failed)
    return _result("up", ms, "User pool responding", mode="cognito", active_users=users, failed_tasks=failed)


def check_biometric(db: Session) -> dict[str, Any]:
    from .integrations import BiometricError, get_biometric

    adapter = get_biometric()
    now = datetime.now()
    last = db.scalar(select(func.max(m.Punch.punched_at)).where(m.Punch.punched_at <= now + timedelta(hours=6)))
    pending = db.scalar(select(func.count(m.ProvisioningTask.id)).where(m.ProvisioningTask.target == "biometric",
                                                                        m.ProvisioningTask.status.in_(["failed", "manual"])))
    # punch times are the property's local time; the server may run in UTC, so never show a negative age
    age_h = max(0.0, round((now - last).total_seconds() / 3600, 1)) if last else None
    metrics = {"adapter": adapter.name, "last_punch": last.isoformat() if last else None, "hours_since_last_punch": age_h, "enrolments_open": pending}
    ms = None
    if adapter.name == "http":
        t = time.perf_counter()
        try:
            adapter.fetch_punches(datetime.now())
            ms = (time.perf_counter() - t) * 1000
        except BiometricError as e:
            return _result("down", None, f"Device API not reachable: {e}", **metrics)
    if last is None:
        return _result("degraded", ms, "No punches received yet", **metrics)
    if age_h is not None and age_h > settings.monitor_biometric_stale_hours:
        how = "device" if adapter.name == "http" else "Excel import"
        return _result("degraded", ms, f"No new punches for {age_h} hours (check the {how})", **metrics)
    return _result("up", ms, f"Last punch {age_h} hours ago · adapter {adapter.name}", **metrics)


def check_web(db: Session) -> dict[str, Any]:
    if not settings.monitor_web_url:
        return _result("unknown", None, "MONITOR_WEB_URL is not set")
    import httpx

    t = time.perf_counter()
    try:
        r = httpx.get(settings.monitor_web_url, timeout=5)
        ms = (time.perf_counter() - t) * 1000
    except httpx.HTTPError as e:
        return _result("down", None, f"Not reachable: {e.__class__.__name__}")
    if r.status_code != 200:
        return _result("down", ms, f"HTTP {r.status_code}")
    return _result("degraded" if ms > 1500 else "up", ms, "Serving" if ms <= 1500 else "Slow response")


CHECKS = {"web": check_web, "api": check_api, "database": check_database, "signin": check_signin, "biometric": check_biometric}


# ---------------------------------------------------------------- alerts
def _recent(db: Session, service: str, n: int) -> list[str]:
    return list(db.scalars(select(m.MonitorSample.status).where(m.MonitorSample.service == service).order_by(m.MonitorSample.id.desc()).limit(n)))


def evaluate_alerts(db: Session, service: str) -> m.MonitorAlert | None:
    statuses = _recent(db, service, 3)
    open_alert = db.scalar(select(m.MonitorAlert).where(m.MonitorAlert.service == service, m.MonitorAlert.resolved_at.is_(None)))
    current = statuses[0] if statuses else "unknown"
    if current == "up":
        if open_alert:
            open_alert.resolved_at = datetime.now(timezone.utc)
            log.info("Alert resolved: %s", open_alert.message)
        return None
    down2 = len(statuses) >= 2 and all(s == "down" for s in statuses[:2])
    bad3 = len(statuses) >= 3 and all(s in ("down", "degraded") for s in statuses[:3])
    severity = "critical" if down2 else "warning" if bad3 else None
    if not severity:
        return None
    sample = db.scalar(select(m.MonitorSample).where(m.MonitorSample.service == service).order_by(m.MonitorSample.id.desc()))
    message = f"{SERVICES[service]}: {sample.detail if sample else current}"[:300]
    if open_alert:
        if severity == "critical" and open_alert.severity != "critical":
            open_alert.severity, open_alert.message = "critical", message
            _notify(db, open_alert)
        return None
    alert = m.MonitorAlert(service=service, severity=severity, message=message)
    db.add(alert)
    db.flush()
    _notify(db, alert)
    return alert


def _notify(db: Session, alert: m.MonitorAlert) -> None:
    log.warning("ALERT %s %s", alert.severity.upper(), alert.message)
    from .integrations import queue_message

    for email in [x.strip() for x in settings.monitor_alert_emails.split(",") if x.strip()]:
        queue_message(db, to=email, template="monitor_alert", channel="email",
                      payload={"severity": alert.severity, "service": alert.service, "message": alert.message})


# ---------------------------------------------------------------- run
def run_checks(db: Session) -> list[dict[str, Any]]:
    out = []
    for service, fn in CHECKS.items():
        try:
            r = fn(db)
        except Exception as e:  # noqa: BLE001 - a broken check must not stop the others
            db.rollback()
            r = _result("unknown", None, f"Check failed: {e.__class__.__name__}: {e}")
        db.add(m.MonitorSample(service=service, status=r["status"], latency_ms=r["latency_ms"], detail=r["detail"], metrics=r["metrics"]))
        db.flush()
        evaluate_alerts(db, service)
        out.append({"service": service, **r})
    db.commit()
    return out


def prune(db: Session) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.monitor_keep_days)
    n = db.execute(delete(m.MonitorSample).where(m.MonitorSample.at < cutoff)).rowcount or 0
    db.commit()
    return n
