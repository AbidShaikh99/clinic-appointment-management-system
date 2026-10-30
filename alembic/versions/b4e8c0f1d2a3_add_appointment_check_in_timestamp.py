"""add appointment check-in timestamp

Revision ID: b4e8c0f1d2a3
Revises: 9973652c5299
Create Date: 2026-10-30 15:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b4e8c0f1d2a3"
down_revision: Union[str, Sequence[str], None] = "9973652c5299"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "appointments",
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("appointments", "checked_in_at")
