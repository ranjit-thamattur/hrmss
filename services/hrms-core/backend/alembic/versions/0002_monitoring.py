"""Monitoring: health samples and alerts for the 5 core services (SCRUM-130).

Revision ID: 0002_monitoring
Revises: 0001_baseline
Create Date: 2026-11-18
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_monitoring"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monitor_samples",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("service", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("detail", sa.String(length=300), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_monitor_samples_at"), "monitor_samples", ["at"], unique=False)
    op.create_index(op.f("ix_monitor_samples_service"), "monitor_samples", ["service"], unique=False)
    op.create_table(
        "monitor_alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("service", sa.String(length=20), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("message", sa.String(length=300), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.String(length=200), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_monitor_alerts_resolved_at"), "monitor_alerts", ["resolved_at"], unique=False)
    op.create_index(op.f("ix_monitor_alerts_service"), "monitor_alerts", ["service"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_monitor_alerts_service"), table_name="monitor_alerts")
    op.drop_index(op.f("ix_monitor_alerts_resolved_at"), table_name="monitor_alerts")
    op.drop_table("monitor_alerts")
    op.drop_index(op.f("ix_monitor_samples_service"), table_name="monitor_samples")
    op.drop_index(op.f("ix_monitor_samples_at"), table_name="monitor_samples")
    op.drop_table("monitor_samples")
