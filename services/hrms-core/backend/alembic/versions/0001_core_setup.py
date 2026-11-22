"""HRMS core baseline: Company Setup (stages 1-3), users, audit log, approvals of backdated changes.

Revision ID: 0001_core_setup
Revises:
Create Date: 2026-11-20

Builds the tables that exist on 20-Nov-2026 (CORE_TABLES) from the models. Every later table or column gets
its own migration:  alembic revision --autogenerate -m "what changed"   (CI runs `alembic check`).
On Postgres, a trigger makes audit_log append-only (UPDATE and DELETE are refused).
"""
from alembic import op

from app import models  # noqa: F401 - registers the tables
from app.db import Base

revision = "0001_core_setup"
down_revision = None
branch_labels = None
depends_on = None

CORE_TABLES = [
    "app_settings", "app_users", "approval_workflows", "audit_log", "bank_accounts", "biometric_devices", "clients", "cost_centres",
    "department_entities", "departments", "designations", "documents", "employment_assignments", "employment_types", "entity_locations",
    "grades", "holiday_calendars", "leave_types", "legal_entities", "locations", "number_allocations", "number_counters", "number_series",
    "payroll_calendars", "pending_changes", "persons", "policies", "reporting_lines", "role_permissions", "shifts", "states",
    "statutory_registrations", "weekly_off_patterns",
]

AUDIT_GUARD = """
CREATE OR REPLACE FUNCTION audit_log_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'audit_log is append-only';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS audit_log_no_change ON audit_log;
CREATE TRIGGER audit_log_no_change BEFORE UPDATE OR DELETE ON audit_log
FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();
"""


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables[t] for t in CORE_TABLES])
    if bind.dialect.name == "postgresql":
        op.execute(AUDIT_GUARD)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_log_no_change ON audit_log; DROP FUNCTION IF EXISTS audit_log_append_only();")
    Base.metadata.drop_all(bind=bind, tables=[Base.metadata.tables[t] for t in CORE_TABLES])
