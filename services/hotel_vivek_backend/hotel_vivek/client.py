"""Entry point the HRMS core loads for this client (named in client.yaml: package: hotel_vivek)."""
from __future__ import annotations

from .api import employees

CODE = "HV"
ROUTERS = [employees.router]


def load_demo(db, client) -> None:  # noqa: ANN001 - called by the core on laptops only
    from .demo import load

    load(db, client)
