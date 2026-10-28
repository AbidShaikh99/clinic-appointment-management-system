from datetime import time

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Integer,
    SmallInteger,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class DoctorSchedule(Base):
    __tablename__ = "doctor_schedules"

    __table_args__ = (
        CheckConstraint(
            "weekday >= 0 AND weekday <= 6",
            name="ck_schedule_valid_weekday",
        ),
        CheckConstraint(
            "start_time < end_time",
            name="ck_schedule_start_before_end",
        ),
        CheckConstraint(
            "(break_start IS NULL AND break_end IS NULL) OR "
            "(break_start IS NOT NULL AND break_end IS NOT NULL)",
            name="ck_schedule_break_pair",
        ),
        CheckConstraint(
            "break_start IS NULL OR "
            "(break_start >= start_time AND break_end <= end_time "
            "AND break_start < break_end)",
            name="ck_schedule_break_inside_period",
        ),
        UniqueConstraint(
            "doctor_id",
            "weekday",
            "start_time",
            name="uq_schedule_doctor_day_start",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Monday = 0, Tuesday = 1, ... Sunday = 6
    weekday: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
    )

    start_time: Mapped[time] = mapped_column(
        Time,
        nullable=False,
    )

    end_time: Mapped[time] = mapped_column(
        Time,
        nullable=False,
    )

    break_start: Mapped[time | None] = mapped_column(
        Time,
        nullable=True,
    )

    break_end: Mapped[time | None] = mapped_column(
        Time,
        nullable=True,
    )

    doctor = relationship(
        "Doctor",
        back_populates="schedules",
    )
