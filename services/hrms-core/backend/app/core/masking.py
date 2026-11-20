"""Masking of sensitive values (PAN, Aadhaar, bank account, identity documents). Pure functions.

Rule: sensitive fields show in full only to allowed roles, and never in logs or exports without permission.
"""
from __future__ import annotations

from typing import Any

MASK = "X"


def mask_value(value: str | None, visible: int = 4) -> str | None:
    if value is None or value == "":
        return value
    s = str(value)
    if len(s) <= visible:
        return MASK * len(s)
    return MASK * (len(s) - visible) + s[-visible:]


def mask_documents(docs: Any) -> Any:
    """Identity documents: keep type and dates, mask each number."""
    if not isinstance(docs, list):
        return docs
    out = []
    for d in docs:
        if isinstance(d, dict):
            d = {**d, "number": mask_value(d.get("number"))}
        out.append(d)
    return out


def mask_for_log(values: dict[str, Any] | None, secret_names: set[str]) -> dict[str, Any] | None:
    """Audit log copy: secrets always masked, whoever made the change."""
    if values is None:
        return None
    out = {}
    for k, v in values.items():
        if k in secret_names:
            out[k] = mask_documents(v) if isinstance(v, list) else mask_value(v)
        elif k.endswith("_hash"):
            continue
        else:
            out[k] = v
    return out
