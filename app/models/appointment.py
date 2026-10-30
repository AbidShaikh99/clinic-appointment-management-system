from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SQLAlchemyEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import (
    AppointmentPriority,
    AppointmentStatus,
    AppointmentType,
)


def enum_values(enum_class):
    return [item.value for item in enum_class]


class Appointment(Base):
    __tablename__ = "appointments"

    __table_args__ = (
        CheckConstraint(
            "start_at < end_at",
            name="ck_appointment_start_before_end",
        ),
        Index(
            "ix_appointment_doctor_start_end",
            "doctor_id",
            "start_at",
            "end_at",
        ),
        Index(
            "ix_appointment_patient_start_end",
            "patient_id",
            "start_at",
            "end_at",
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

    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctors.id"),
        nullable=False,
        index=True,
    )

    start_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    end_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    appointment_type: Mapped[AppointmentType] = mapped_column(
        SQLAlchemyEnum(
            AppointmentType,
            name="appointment_type_enum",
            native_enum=False,
            values_callable=enum_values,
            validate_strings=True,
        ),
        nullable=False,
    )

    priority: Mapped[AppointmentPriority] = mapped_column(
        SQLAlchemyEnum(
            AppointmentPriority,
            name="appointment_priority_enum",
            native_enum=False,
            values_callable=enum_values,
            validate_strings=True,
        ),
        nullable=False,
        default=AppointmentPriority.NORMAL,
    )

    status: Mapped[AppointmentStatus] = mapped_column(
        SQLAlchemyEnum(
            AppointmentStatus,
            name="appointment_status_enum",
            native_enum=False,
            values_callable=enum_values,
            validate_strings=True,
        ),
        nullable=False,
        default=AppointmentStatus.REQUESTED,
        index=True,
    )

    booking_reference: Mapped[str] = mapped_column(
        String(30),
        unique=True,
        nullable=False,
        index=True,
    )

    booked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    checked_in_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    no_show_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    consultation_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    consultation_ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    consultation_duration_seconds: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    patient: Mapped["Patient"] = relationship(
        back_populates="appointments",
    )

    doctor: Mapped["Doctor"] = relationship(
        back_populates="appointments",
    )
