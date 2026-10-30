"""add waiting-list temporary offers

Revision ID: e7a51d84c203
Revises: d6e741b902ac
Create Date: 2026-10-30 18:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e7a51d84c203"
down_revision: Union[str, Sequence[str], None] = "d6e741b902ac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "waiting_list",
        sa.Column("offered_doctor_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "waiting_list",
        sa.Column("offered_start_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "waiting_list",
        sa.Column("offered_end_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "waiting_list",
        sa.Column("offer_expires_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "waiting_list",
        sa.Column("last_offer_status", sa.String(length=20)),
    )
    op.create_foreign_key(
        "fk_waiting_list_offered_doctor_id_doctors",
        "waiting_list",
        "doctors",
        ["offered_doctor_id"],
        ["id"],
    )
    op.create_index(
        "ix_waiting_list_offer_expiration",
        "waiting_list",
        ["status", "offer_expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_waiting_list_offer_expiration",
        table_name="waiting_list",
    )
    op.drop_constraint(
        "fk_waiting_list_offered_doctor_id_doctors",
        "waiting_list",
        type_="foreignkey",
    )
    op.drop_column("waiting_list", "last_offer_status")
    op.drop_column("waiting_list", "offer_expires_at")
    op.drop_column("waiting_list", "offered_end_at")
    op.drop_column("waiting_list", "offered_start_at")
    op.drop_column("waiting_list", "offered_doctor_id")
