import subprocess
import sys
from pathlib import Path

from app.core.specs import SPECS, check_catalogue

ROOT = Path(__file__).resolve().parents[1]


def test_catalogue_is_consistent():
    assert check_catalogue() == []


def test_stage_1_and_2_entities_are_present():
    for key in ("legal-entities", "locations", "entity-locations", "departments", "department-entities", "designations", "cost-centres",
                "persons", "statutory-registrations", "holiday-calendars", "biometric-devices", "payroll-calendars", "employment-assignments",
                "reporting-lines", "role-permissions"):
        assert key in SPECS


def test_models_file_is_up_to_date():
    r = subprocess.run([sys.executable, "scripts/gen_models.py", "--check"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
