"""initial schema

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_pw", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "services",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("method", sa.String(10), server_default="GET", nullable=False),
        sa.Column("interval_secs", sa.Integer(), server_default="60", nullable=False),
        sa.Column("timeout_ms", sa.Integer(), server_default="5000", nullable=False),
        sa.Column("expected_status", sa.Integer(), server_default="200", nullable=False),
        sa.Column("headers", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_service_user_name"),
    )
    op.create_index("idx_services_user_active", "services", ["user_id", "is_active"])

    op.create_table(
        "check_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("checker_node_id", sa.String(128), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("raw_headers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("idx_cr_service_time", "check_results", ["service_id", "checked_at"])
    op.create_index("idx_cr_node_time", "check_results", ["checker_node_id", "checked_at"])

    op.create_table(
        "service_status",
        sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("current_status", sa.String(20), server_default="unknown", nullable=False),
        sa.Column("since", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("uptime_7d", sa.Numeric(5, 2), nullable=True),
        sa.Column("p50_ms", sa.Integer(), nullable=True),
        sa.Column("p99_ms", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("service_id"),
    )

    op.create_table(
        "incidents",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trigger_reason", sa.String(512), nullable=False),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("ai_generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("alert_sent", sa.Boolean(), server_default="false", nullable=False),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_incidents_service", "incidents", ["service_id", "started_at"])
    op.execute("CREATE INDEX idx_incidents_open ON incidents (service_id) WHERE resolved_at IS NULL")

    op.create_table(
        "incident_context",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_ic_incident", "incident_context", ["incident_id"])

    op.create_table(
        "alert_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("destination", sa.Text(), nullable=False),
        sa.Column("on_incident", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("on_resolve", sa.Boolean(), server_default="true", nullable=False),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("service_id", "channel", "destination", name="uq_alert_rule"),
    )


def downgrade() -> None:
    op.drop_table("alert_rules")
    op.drop_table("incident_context")
    op.drop_table("incidents")
    op.drop_table("service_status")
    op.drop_table("check_results")
    op.drop_table("services")
    op.drop_table("users")
