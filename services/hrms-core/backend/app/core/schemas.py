"""Request schemas built from the catalogue (pydantic only, no database), so every entity validates the
same way in the API, in Excel imports and in OpenAPI / Postman.

Unknown keys are ignored, including any client_id sent in a request (rule: the client comes from the login).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, create_model

from .specs import PATTERNS, SPECS, F, Spec

UPPER = {"pan", "tan", "gstin", "cin", "ifsc"}
EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
TIME = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"
PERIOD = r"^[0-9]{4}-(0[1-9]|1[0-2])$"


class Base(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


def _upper(v: Any) -> Any:
    return v.strip().upper() if isinstance(v, str) else v


def py_type(f: F) -> Any:
    pat = PATTERNS.get(f.pattern) if f.pattern else None
    up = f.pattern in UPPER
    if f.kind in ("str", "secret"):
        c = StringConstraints(strip_whitespace=True, max_length=f.max_len if f.kind == "str" else 100, pattern=pat)
        # PAN, TAN, GSTIN, CIN and IFSC are accepted in any case and stored upper-case
        return Annotated[str, BeforeValidator(_upper), c] if up else Annotated[str, c]
    if f.kind == "text":
        return Annotated[str, StringConstraints(max_length=4000)]
    if f.kind == "email":
        return Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=f.max_len, pattern=EMAIL)]
    if f.kind == "enum":
        return Literal[f.choices]  # type: ignore[valid-type]
    if f.kind == "time":
        return Annotated[str, StringConstraints(pattern=TIME)]
    if f.kind == "period":
        return Annotated[str, StringConstraints(pattern=PERIOD)]
    if f.kind == "int":
        return int
    if f.kind == "year":
        return Annotated[int, Field(ge=1990, le=2100)]
    if f.kind == "decimal":
        return Decimal
    if f.kind == "bool":
        return bool
    if f.kind == "date":
        return date
    if f.kind == "datetime":
        return datetime
    if f.kind == "ref":
        return Annotated[int, Field(gt=0)]
    if f.kind == "refs":
        return list[Annotated[int, Field(gt=0)]]
    if f.kind == "secret_json":
        return list[dict[str, Any]]
    return Any  # json


def _model_name(spec: Spec, suffix: str) -> str:
    return spec.model + suffix


@lru_cache(maxsize=None)
def create_schema(key: str) -> type[BaseModel]:
    spec = SPECS[key]
    fields: dict[str, Any] = {}
    for f in spec.input_fields:
        t = py_type(f)
        if f.required and f.default is None:
            fields[f.name] = (t, Field(..., description=f.title))
        else:
            fields[f.name] = (Optional[t], Field(f.default, description=f.title))
    fields["valid_from"] = (Optional[date], Field(None, description="First day this record applies (default: today)"))
    fields["valid_to"] = (Optional[date], Field(None, description="Last day (empty = open)"))
    fields["change_reason"] = (Optional[str], Field(None, max_length=300))
    return create_model(_model_name(spec, "Create"), __base__=Base, **fields)


@lru_cache(maxsize=None)
def change_schema(key: str) -> type[BaseModel]:
    spec = SPECS[key]
    fields: dict[str, Any] = {f.name: (Optional[py_type(f)], Field(None, description=f.title)) for f in spec.input_fields}
    fields["effective_from"] = (Optional[date], Field(None, description="The change applies from this day (default: today). "
                                                                          "Before today = backdated: needs approval."))
    fields["change_reason"] = (Optional[str], Field(None, max_length=300))
    return create_model(_model_name(spec, "Change"), __base__=Base, **fields)


class StatusChange(Base):
    effective_from: Optional[date] = Field(None, description="Default: today. Before today needs approval.")
    change_reason: Optional[str] = Field(None, max_length=300)


class EndRecord(Base):
    end_date: date = Field(..., description="Last day the record applies. Before today needs approval.")
    change_reason: Optional[str] = Field(None, max_length=300)


def split_create(data: dict[str, Any]) -> tuple[dict[str, Any], date | None, date | None, str | None]:
    """Separate entity values from the dating fields of a create request."""
    d = dict(data)
    return d, d.pop("valid_from", None), d.pop("valid_to", None), d.pop("change_reason", None)


def split_change(data: dict[str, Any]) -> tuple[dict[str, Any], date | None, str | None]:
    d = dict(data)
    return d, d.pop("effective_from", None), d.pop("change_reason", None)
