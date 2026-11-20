
from alembic import op
import sqlalchemy as sa


revision = "a91f62c4d810"
down_revision = "cb8fe1124ce2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(length=20),
            nullable=False,
            server_default="user",
        ),
    )

    # Existing admin flags are intentionally NOT promoted.
    # The configured Super Admin will be initialized separately.


def downgrade() -> None:
    op.drop_column("users", "role")
