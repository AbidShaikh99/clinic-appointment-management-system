from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SQLAlchemyEnum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import (
    AppointmentType,
    WaitingListPriority,
    WaitingListStatus,
)


def enum_values(enum_class):
    return [item.value for item in enum_class]


class WaitingList(Base):
    __tablename__ = "waiting_list"

    __table_args__ = (
        CheckConstraint(
            """
            (doctor_id IS NOT NULL AND specialization IS NULL)
            OR
            (doctor_id IS NULL AND specialization IS NOT NULL)
            """,
            name="ck_waiting_list_doctor_or_specialization",
        ),
        CheckConstraint(
            "required_duration_minutes > 0",
            name="ck_waiting_list_positive_duration",
        ),
        Index(
            "ix_waiting_list_patient_status",
            "patient_id",
            "status",
        ),
        Index(
            "ix_waiting_list_doctor_status",
            "doctor_id",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id"),
        nullable=False,
        index=True,
    )

    doctor_id: Mapped[int | None] = mapped_column(
        ForeignKey("doctors.id"),
        nullable=True,
        index=True,
    )

    specialization: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )

    appointment_type: Mapped[AppointmentType] = mapped_column(
        SQLAlchemyEnum(
            AppointmentType,
            name="waiting_list_appointment_type_enum",
            native_enum=False,
            values_callable=enum_values,
            validate_strings=True,
        ),
        nullable=False,
    )

    preferred_time_periods: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
    )

    required_duration_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    priority: Mapped[WaitingListPriority] = mapped_column(
        SQLAlchemyEnum(
            WaitingListPriority,
            name="waiting_list_priority_enum",
            native_enum=False,
            values_callable=enum_values,
            validate_strings=True,
        ),
        nullable=False,
        default=WaitingListPriority.NORMAL,
    )

    status: Mapped[WaitingListStatus] = mapped_column(
        SQLAlchemyEnum(
            WaitingListStatus,
            name="waiting_list_status_enum",
            native_enum=False,
            values_callable=enum_values,
            validate_strings=True,
        ),
        nullable=False,
        default=WaitingListStatus.ACTIVE,
        index=True,
    )

    offered_doctor_id: Mapped[int | None] = mapped_column(
        ForeignKey("doctors.id"),
        nullable=True,
    )

    offered_start_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    offered_end_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    offer_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_offer_status: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    patient: Mapped["Patient"] = relationship()

    doctor: Mapped["Doctor"] = relationship(
        foreign_keys=[doctor_id],
    )
