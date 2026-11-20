"""The client's own backend package (e.g. hotel_vivek): its APIs and business operations, plus synthetic demo
data for laptops. Named in the client YAML (`package:`); the core never imports a client by name.

A client package provides <package>/client.py with:
    CODE          the client code (must match the YAML)
    ROUTERS       list of FastAPI routers (the client's own APIs, e.g. /api/employee/add)
    load_demo(db, client)   optional: synthetic data for laptops
"""
from __future__ import annotations

import importlib
import sys
from functools import lru_cache
from pathlib import Path
from types import ModuleType

from .config import get_settings


@lru_cache
def get_client_package() -> ModuleType | None:
    s = get_settings()
    conf = s.client
    name = conf.get("package")
    if not name:
        return None
    if s.client_package_path:
        p = str(Path(s.client_package_path).resolve())
        if p not in sys.path:
            sys.path.insert(0, p)
    mod = importlib.import_module(f"{name}.client")
    code = str(getattr(mod, "CODE", "")).upper()
    if code != str(conf["client"]["code"]).upper():
        raise SystemExit(f"Client package {name} is for client {code}, but the YAML is for {conf['client']['code']}.")
    return mod
