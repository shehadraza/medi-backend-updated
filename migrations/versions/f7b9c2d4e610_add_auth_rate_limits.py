"""add shared authentication rate limits

Revision ID: f7b9c2d4e610
Revises: c6a8f0312d4e
Create Date: 2026-11-20
"""
from alembic import op
import sqlalchemy as sa


revision = "f7b9c2d4e610"
down_revision = "c6a8f0312d4e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_rate_limits",
        sa.Column("key_digest", sa.String(length=64), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("request_count >= 0", name="ck_auth_rate_limits_count_nonnegative"),
    )
    op.create_index(
        "ix_auth_rate_limits_window_start",
        "auth_rate_limits",
        ["window_start"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_auth_rate_limits_window_start", table_name="auth_rate_limits")
    op.drop_table("auth_rate_limits")
