"""Add encrypted daily health check-ins."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c6a8f0312d4e"
down_revision: Union[str, Sequence[str], None] = "f6a2026a1c90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_health_checkins",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("timezone_name", sa.String(length=100), nullable=False),
        sa.Column("encrypted_data", sa.Text(), nullable=False),
        sa.Column("encryption_version", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "local_date", name="uq_daily_health_checkins_user_date"),
    )


def downgrade() -> None:
    op.drop_table("daily_health_checkins")
