from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from .. import models as m

SENSITIVE_KEYS = {"pan_enc", "bank_account_enc", "password_hash", "pan", "bank_account", "aadhaar"}


def _plain(v: Any) -> Any:
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, dict):
        return {k: ("***" if k in SENSITIVE_KEYS and val else _plain(val)) for k, val in v.items()}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    return v


def snapshot(obj: Any, fields: list[str] | None = None) -> dict[str, Any]:
    cols = fields or [c.key for c in obj.__table__.columns]
    return _plain({c: getattr(obj, c) for c in cols})


def record(db: Session, actor: str, action: str, entity_type: str, entity_id: Any = None, *, before: Any = None, after: Any = None,
           employee_id: int | None = None) -> None:
    db.add(m.AuditLog(actor=actor, action=action, entity_type=entity_type, entity_id=None if entity_id is None else str(entity_id),
                      employee_id=employee_id, before=_plain(before), after=_plain(after)))


def diff(before: dict[str, Any], after: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    keys = [k for k in after if before.get(k) != after.get(k)]
    return {k: before.get(k) for k in keys}, {k: after.get(k) for k in keys}
