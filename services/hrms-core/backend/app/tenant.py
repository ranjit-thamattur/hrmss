"""Client (tenant) hook — decision 0006.

hrms-core holds everything common to every client. A client package (for Hotel Vivek: the
`hotel_vivek` package in services/hotel_vivek_backend) adds what is specific to that client:

    CODE            short client code, e.g. "HV"
    NAME            client name shown in the app, e.g. "Hotel Vivek"
    DEMO_USERS      [(email, display name, roles, link)] for laptops; link "EMP"/"HOD" or None
    KRA_TEMPLATES   {department: [KRA, ...], "_default": [...]} for review cycles      (optional)
    IMPORT_EXAMPLES {kind: [example row]} for the Excel templates                     (optional)
    IMPORT_NOTES    {kind: [extra line]} shown in the template's "How to" sheet        (optional)
    seed_org(db)                organisation masters (synthetic on laptops)
    seed_employees(db, count)   synthetic employees; returns {"EMP": id, "HOD": id}

One deployment and one database per client: the database is stamped with the client code on first
start, and the API refuses to start against another client's database (see app/startup.py).
"""
from __future__ import annotations

import importlib
import sys
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .config import get_settings

DEFAULT_KRAS = {"_default": ["Quality of work", "Attendance and punctuality", "Teamwork", "Learning"]}


def _no_seed(*_: Any, **__: Any) -> Any:
    raise SystemExit("No client package configured (set TENANT and TENANT_PACKAGE), so there is no demo data to load.")


CORE_DEFAULT = SimpleNamespace(CODE="CORE", NAME="Peak HRMS", DEMO_USERS=[], KRA_TEMPLATES=DEFAULT_KRAS, IMPORT_EXAMPLES={}, IMPORT_NOTES={},
                               seed_org=_no_seed, seed_employees=_no_seed)


@lru_cache
def get_tenant() -> Any:
    s = get_settings()
    if not s.tenant_package:
        if s.tenant:
            raise SystemExit(f"TENANT={s.tenant} is set but TENANT_PACKAGE is empty.")
        return CORE_DEFAULT
    if s.tenant_path:
        p = str(Path(s.tenant_path).resolve())
        if p not in sys.path:
            sys.path.insert(0, p)
    mod = importlib.import_module(f"{s.tenant_package}.tenant")
    code = str(getattr(mod, "CODE", "")).upper()
    if s.tenant and code != s.tenant:
        raise SystemExit(f"TENANT={s.tenant} but package {s.tenant_package} is client {code}.")
    for name, default in (("KRA_TEMPLATES", DEFAULT_KRAS), ("IMPORT_EXAMPLES", {}), ("IMPORT_NOTES", {}), ("DEMO_USERS", [])):
        if not hasattr(mod, name):
            setattr(mod, name, default)
    return mod


def tenant_code() -> str:
    return str(get_tenant().CODE).upper()


def tenant_name() -> str:
    return str(get_tenant().NAME)
