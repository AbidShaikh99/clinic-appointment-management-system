"""add consultation lifecycle timestamps and duration

Revision ID: c6f2a9d4e813
Revises: b4e8c0f1d2a3
Create Date: 2026-10-30 17:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c6f2a9d4e813"
down_revision: Union[str, Sequence[str], None] = "b4e8c0f1d2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "appointments",
        sa.Column("consultation_started_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "appointments",
        sa.Column("consultation_ended_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "appointments",
        sa.Column("consultation_duration_seconds", sa.Integer()),
    )


def downgrade() -> None:
    op.drop_column("appointments", "consultation_duration_seconds")
    op.drop_column("appointments", "consultation_ended_at")
    op.drop_column("appointments", "consultation_started_at")
