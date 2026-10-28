from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RescheduleProposal(Base):
    __tablename__ = "reschedule_proposals"

    __table_args__ = (
        CheckConstraint(
            "proposed_start_at < proposed_end_at",
            name="ck_proposal_start_before_end",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    leave_id: Mapped[int] = mapped_column(
        ForeignKey("doctor_leaves.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    proposed_doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctors.id", ondelete="RESTRICT"),
        nullable=False,
    )

    proposed_start_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    proposed_end_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="PENDING",
        server_default="PENDING",
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
