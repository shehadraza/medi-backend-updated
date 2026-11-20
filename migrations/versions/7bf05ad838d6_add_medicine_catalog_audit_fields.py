
"""add medicine catalog audit fields

Revision ID: 7bf05ad838d6
Revises: cb8fe1124ce2
Create Date: 2026-11-18 00:46:43.753207

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7bf05ad838d6"
down_revision: Union[str, Sequence[str], None] = "cb8fe1124ce2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # 1. Add audit columns.
    op.add_column(
        "medicine_catalog",
        sa.Column("created_by", sa.String(length=36), nullable=True),
    )

    op.add_column(
        "medicine_catalog",
        sa.Column("updated_by", sa.String(length=36), nullable=True),
    )

    op.add_column(
        "medicine_catalog",
        sa.Column("verified_by", sa.String(length=36), nullable=True),
    )

    # 2. Create indexes.
    op.create_index(
        "ix_medicine_catalog_created_by",
        "medicine_catalog",
        ["created_by"],
        unique=False,
    )

    op.create_index(
        "ix_medicine_catalog_updated_by",
        "medicine_catalog",
        ["updated_by"],
        unique=False,
    )

    op.create_index(
        "ix_medicine_catalog_verified_by",
        "medicine_catalog",
        ["verified_by"],
        unique=False,
    )

    # 3. Create named foreign keys.
    op.create_foreign_key(
        "fk_medicine_catalog_created_by_users",
        "medicine_catalog",
        "users",
        ["created_by"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_foreign_key(
        "fk_medicine_catalog_updated_by_users",
        "medicine_catalog",
        "users",
        ["updated_by"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_foreign_key(
        "fk_medicine_catalog_verified_by_users",
        "medicine_catalog",
        "users",
        ["verified_by"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""

    # 1. Drop foreign keys.
    op.drop_constraint(
        "fk_medicine_catalog_verified_by_users",
        "medicine_catalog",
        type_="foreignkey",
    )

    op.drop_constraint(
        "fk_medicine_catalog_updated_by_users",
        "medicine_catalog",
        type_="foreignkey",
    )

    op.drop_constraint(
        "fk_medicine_catalog_created_by_users",
        "medicine_catalog",
        type_="foreignkey",
    )

    # 2. Drop indexes.
    op.drop_index(
        "ix_medicine_catalog_verified_by",
        table_name="medicine_catalog",
    )

    op.drop_index(
        "ix_medicine_catalog_updated_by",
        table_name="medicine_catalog",
    )

    op.drop_index(
        "ix_medicine_catalog_created_by",
        table_name="medicine_catalog",
    )

    # 3. Drop columns.
    op.drop_column("medicine_catalog", "verified_by")
    op.drop_column("medicine_catalog", "updated_by")
    op.drop_column("medicine_catalog", "created_by")
