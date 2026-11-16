"""Baseline schema for Peak HRMS.

The first migration builds every table from the models, so it cannot drift from them. From here on,
each model change gets its own migration:  alembic revision --autogenerate -m "what changed"
and CI runs `alembic check` to catch a model change without a migration.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-13
"""
from alembic import op

from app import models  # noqa: F401
from app.db import Base

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
    Base.metadata.create_all(bind=bind)
    if bind.dialect.name == "postgresql":
        op.execute(AUDIT_GUARD)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_log_no_change ON audit_log; DROP FUNCTION IF EXISTS audit_log_append_only();")
    Base.metadata.drop_all(bind=bind)
