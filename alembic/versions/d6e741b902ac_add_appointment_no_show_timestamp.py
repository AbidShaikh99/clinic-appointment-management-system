"""add appointment no-show timestamp

Revision ID: d6e741b902ac
Revises: c6f2a9d4e813
Create Date: 2026-10-30 17:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d6e741b902ac"
down_revision: Union[str, Sequence[str], None] = "c6f2a9d4e813"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "appointments",
        sa.Column("no_show_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_column("appointments", "no_show_at")
