"""Low-level helpers for versioned records: find versions, encode secrets, read values back."""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import date
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

from .. import models as m
from ..config import get_settings
from .context import Ctx, current
from .security import decrypt, encrypt
from .specs import SPECS, Spec


def model(spec: Spec) -> Any:
    return m.MODELS[spec.key]


def versions(ctx: Ctx, spec: Spec, rid: int) -> list[Any]:
    md = model(spec)
    return list(ctx.db.scalars(select(md).where(md.client_id == ctx.client_id, md.rid == rid).order_by(md.valid_from)))


def at(ctx: Ctx, spec: Spec, rid: int | None, on: date) -> Any | None:
    """The version of record `rid` that applies on `on` (active or not), or None."""
    if rid is None:
        return None
    md = model(spec)
    return ctx.db.scalar(select(md).where(md.client_id == ctx.client_id, md.rid == rid, current(md, on)))


def active_at(ctx: Ctx, key: str, rid: int | None, on: date) -> Any | None:
    row = at(ctx, SPECS[key], rid, on)
    return row if row is not None and row.is_active else None


def must_exist(ctx: Ctx, spec: Spec, rid: int) -> list[Any]:
    vs = versions(ctx, spec, rid)
    if not vs:
        raise HTTPException(404, f"{spec.title} {rid} not found.")
    return vs


def secret_hash(value: str) -> str:
    """Keyed hash of a secret (e.g. PAN) so duplicates can be found without decrypting."""
    key = get_settings().jwt_secret.encode()
    return hmac.new(key, value.strip().upper().encode(), hashlib.sha256).hexdigest()


def encode(spec: Spec, values: dict[str, Any]) -> dict[str, Any]:
    """Plain values -> column values (secrets encrypted, dedupe hash added)."""
    out = {}
    for f in spec.fields:
        if f.name not in values:
            continue
        v = values[f.name]
        if f.kind == "secret":
            out[f.name] = encrypt(v) if v else None
        elif f.kind == "secret_json":
            out[f.name] = encrypt(json.dumps(v)) if v else None
        else:
            out[f.name] = v
    if spec.dedupe_hash and spec.dedupe_hash in values:
        v = values[spec.dedupe_hash]
        out[f"{spec.dedupe_hash}_hash"] = secret_hash(v) if v else None
    return out


def plain(spec: Spec, row: Any) -> dict[str, Any]:
    """Column values -> plain values (secrets decrypted). Only for the server's own use, never sent as is."""
    out = {}
    for f in spec.fields:
        v = getattr(row, f.name)
        if f.kind == "secret":
            v = decrypt(v)
        elif f.kind == "secret_json":
            raw = decrypt(v)
            v = json.loads(raw) if raw else None
        out[f.name] = v
    return out


def display(spec: Spec, row: Any) -> str:
    if spec.key == "persons":
        return " ".join(x for x in (row.first_name, row.last_name) if x)
    if spec.name_field:
        return str(getattr(row, spec.name_field) or "")
    return str(row.rid)
