"""Monitoring dashboard API (SCRUM-130). Master admin only."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from .. import models as m
from ..config import get_settings
from ..deps import DB, User
from ..serial import row
from ..services.access import require
from ..services.audit import record
from ..services.monitoring import SERVICES, run_checks

router = APIRouter(prefix="/api/monitor", tags=["monitoring"])
settings = get_settings()


def _since(hours: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours)


@router.get("/status")
def status(db: DB, user: User, refresh: bool = False) -> dict:
    require(user, "monitor.read")
    if refresh or not db.scalar(select(m.MonitorSample.id)):
        run_checks(db)
    services = []
    since = _since(24)
    for key, label in SERVICES.items():
        last = db.scalar(select(m.MonitorSample).where(m.MonitorSample.service == key).order_by(m.MonitorSample.id.desc()))
        day = list(db.scalars(select(m.MonitorSample).where(m.MonitorSample.service == key, m.MonitorSample.at >= since)
                              .order_by(m.MonitorSample.id.desc()).limit(2000)))
        known = [s for s in day if s.status != "unknown"]
        up = sum(1 for s in known if s.status == "up")
        services.append({
            "service": key, "label": label,
            "status": last.status if last else "unknown", "latency_ms": last.latency_ms if last else None,
            "detail": last.detail if last else "Not checked yet", "metrics": last.metrics if last else {}, "at": last.at if last else None,
            "uptime_24h": round(100 * up / len(known), 1) if known else None,
            "recent": [{"at": s.at, "status": s.status, "latency_ms": s.latency_ms} for s in reversed(day[:60])],
        })
    open_alerts = db.scalars(select(m.MonitorAlert).where(m.MonitorAlert.resolved_at.is_(None)).order_by(m.MonitorAlert.opened_at.desc()))
    return {"services": services, "open_alerts": [row(a) for a in open_alerts], "interval_seconds": settings.monitor_interval_seconds,
            "checked_at": max((s["at"] for s in services if s["at"]), default=None)}


@router.get("/history")
def history(db: DB, user: User, service: str, hours: int = 24) -> list[dict]:
    require(user, "monitor.read")
    if service not in SERVICES:
        raise HTTPException(404, "Unknown service")
    q = select(m.MonitorSample).where(m.MonitorSample.service == service, m.MonitorSample.at >= _since(min(hours, 24 * 7))).order_by(m.MonitorSample.id)
    return [{"at": s.at, "status": s.status, "latency_ms": s.latency_ms, "detail": s.detail} for s in db.scalars(q)]


@router.get("/alerts")
def alerts(db: DB, user: User, state: str = "all", limit: int = 200) -> list[dict]:
    require(user, "monitor.read")
    q = select(m.MonitorAlert).order_by(m.MonitorAlert.opened_at.desc()).limit(min(limit, 1000))
    if state == "open":
        q = q.where(m.MonitorAlert.resolved_at.is_(None))
    return [row(a) for a in db.scalars(q)]


@router.post("/alerts/{alert_id}/ack")
def acknowledge(alert_id: int, db: DB, user: User) -> dict:
    require(user, "monitor.read")
    a = db.get(m.MonitorAlert, alert_id)
    if not a:
        raise HTTPException(404, "Alert not found")
    if not a.acknowledged_at:
        a.acknowledged_by, a.acknowledged_at = user.email, datetime.now(timezone.utc)
        record(db, user.email, "alert_acknowledged", "monitor_alert", a.id, after={"message": a.message})
        db.commit()
    return row(a)
