"""Run the Hotel Vivek tests against hrms-core: put both on the import path and select the HV client."""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]  # services/hotel_vivek_backend
CORE = HERE.parent / "hrms-core" / "backend"  # services/hrms-core/backend
for p in (str(HERE), str(CORE)):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("TENANT", "HV")
os.environ.setdefault("TENANT_PACKAGE", "hotel_vivek")
