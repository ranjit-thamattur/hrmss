"""Baseline schema for Peak HRMS.

Builds the tables that existed on 13-Nov-2026 from the models (BASELINE_TABLES). Every later table or
column gets its own migration (0002 onward):  alembic revision --autogenerate -m "what changed"
CI runs `alembic check` to catch a model change without a migration.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-13
"""
from alembic import op

from app import models  # noqa: F401
from app.db import Base

BASELINE_TABLES = [
    "entities", "locations", "departments", "designations", "grades", "shifts", "holidays", "policy_versions", "statutory_rule_versions",
    "app_settings", "employees", "assignments", "salary_structures", "entity_allocations", "employee_documents", "change_requests",
    "app_users", "provisioning_tasks", "audit_log", "import_batches", "roster", "punches", "attendance_days", "regularisations",
    "leave_types", "leave_balances", "leave_requests", "monthly_inputs", "payroll_runs", "payroll_lines", "statutory_challans",
    "exit_cases", "clearance_tasks", "review_cycles", "reviews", "increments", "circulars", "circular_reads", "outbox",
]

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None

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
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables[t] for t in BASELINE_TABLES])
    if bind.dialect.name == "postgresql":
        op.execute(AUDIT_GUARD)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_log_no_change ON audit_log; DROP FUNCTION IF EXISTS audit_log_append_only();")
    Base.metadata.drop_all(bind=bind, tables=[Base.metadata.tables[t] for t in BASELINE_TABLES])
