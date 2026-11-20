"""Client (entity 1) from the client YAML, plus the starting data every new client gets:
India's states (country IN), default roles and permissions, the backdated-change approval workflow.

A new client = a new YAML file + its own database; no code change in the core (decision 0007).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from . import engine
from .audit import record
from .context import system_ctx
from .defaults import DEFAULT_WORKFLOWS, INDIA_STATES, default_permissions
from .specs import SPECS

START = date(2000, 1, 1)  # reference data applies from a fixed early date


def client_fields(conf: dict[str, Any]) -> dict[str, Any]:
    c = conf["client"]
    aws = conf.get("aws") or {}
    return {
        "code": str(c["code"]).strip().upper(),
        "name": str(c["name"]).strip(),
        "country": str(c.get("country") or "IN").upper(),
        "default_currency": str(c.get("default_currency") or "INR").upper(),
        "fy_start_month": int(c.get("financial_year_start_month") or 4),
        "aws_account_id": str(aws["account_id"]) if aws.get("account_id") else None,
        "aws_region": aws.get("region"),
        "domain": conf.get("domain"),
        "database_name": (conf.get("database") or {}).get("name"),
        "settings": {k: conf[k] for k in ("onboarding", "features") if k in conf},
    }


def bootstrap_client(db: Session, conf: dict[str, Any]) -> m.Client:
    """Create or update the client from its YAML. Starting data is loaded only when the client is new."""
    vals = client_fields(conf)
    row = db.scalar(select(m.Client).where(m.Client.code == vals["code"]))
    if row is None:
        row = m.Client(**vals)
        db.add(row)
        db.flush()
        ctx = system_ctx(db, row.id, "client-yaml")
        record(ctx, "create", "client", row.id, None, vals)
        load_starting_data(db, row, conf)
    else:
        changes = {k: v for k, v in vals.items() if getattr(row, k) != v}
        if changes:
            ctx = system_ctx(db, row.id, "client-yaml")
            record(ctx, "change", "client", row.id, {k: getattr(row, k) for k in changes}, changes)
            for k, v in changes.items():
                setattr(row, k, v)
            row.updated_at = datetime.now(timezone.utc)
    db.flush()
    return row


def load_starting_data(db: Session, client: m.Client, conf: dict[str, Any]) -> None:
    ctx = system_ctx(db, client.id, "client-yaml")
    if client.country == "IN":
        for code, name in INDIA_STATES:
            engine.create(ctx, SPECS["states"], {"country": "IN", "code": code, "name": name}, START)
    perms = conf.get("role_permissions") or default_permissions()
    for p in perms:
        engine.create(ctx, SPECS["role-permissions"], {"role": p["role"], "resource": p["resource"], "actions": list(p["actions"]),
                                                       "scope": p.get("scope", "scoped"), "masked_fields": list(p.get("masked_fields") or [])}, START)
    for w in conf.get("approval_workflows") or DEFAULT_WORKFLOWS:
        engine.create(ctx, SPECS["approval-workflows"], dict(w), START)
