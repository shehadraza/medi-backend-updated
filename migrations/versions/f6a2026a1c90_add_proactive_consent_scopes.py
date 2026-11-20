"""Add explicit proactive analysis and notification consent scopes."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a2026a1c90"
down_revision: Union[str, Sequence[str], None] = "a41c90d2e6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "health_profiles",
        sa.Column(
            "proactive_health_analysis_consent",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "health_profiles",
        sa.Column(
            "proactive_health_analysis_consent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "health_profiles",
        sa.Column(
            "proactive_wellness_notifications_consent",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "health_profiles",
        sa.Column(
            "proactive_wellness_notifications_consent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("health_profiles", "proactive_wellness_notifications_consent_at")
    op.drop_column("health_profiles", "proactive_wellness_notifications_consent")
    op.drop_column("health_profiles", "proactive_health_analysis_consent_at")
    op.drop_column("health_profiles", "proactive_health_analysis_consent")
