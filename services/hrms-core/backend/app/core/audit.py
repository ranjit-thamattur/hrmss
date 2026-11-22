"""Audit log: every create, change, deactivation and approval, with who, when, before and after.
Append-only (Postgres trigger). Sensitive values are always masked here (rule: never in logs).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .. import models as m
from .context import Ctx
from .masking import mask_for_log


def jsonable(v: Any) -> Any:
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [jsonable(x) for x in v]
    return v


def record(ctx: Ctx, action: str, resource: str, rid: int | None, before: dict[str, Any] | None = None, after: dict[str, Any] | None = None,
           reason: str | None = None, secret: set[str] | None = None, approved_by: str | None = None) -> None:
    secret = secret or set()
    ctx.db.add(m.AuditLog(client_id=ctx.client_id, actor=ctx.actor, action=action, resource=resource, rid=rid,
                          before=jsonable(mask_for_log(before, secret)), after=jsonable(mask_for_log(after, secret)),
                          reason=reason, approved_by=approved_by))


def diff(before: dict[str, Any], after: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    keys = [k for k in after if before.get(k) != after.get(k)]
    return {k: before.get(k) for k in keys}, {k: after.get(k) for k in keys}
