from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    specialization: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )

    consultation_duration: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=30,
    )

    max_daily_appointments: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    schedules: Mapped[list["DoctorSchedule"]] = relationship(
        back_populates="doctor",
        cascade="all, delete-orphan",
    )

    leaves: Mapped[list["DoctorLeave"]] = relationship(
        back_populates="doctor",
        cascade="all, delete-orphan",
    )

    appointments: Mapped[list["Appointment"]] = relationship(
        back_populates="doctor",
    )
