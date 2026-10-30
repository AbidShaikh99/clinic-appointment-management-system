from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.appointment import Appointment
from app.models.doctor import Doctor
from app.models.enums import AppointmentStatus
from app.models.schedule import DoctorSchedule


ACTIVE_APPOINTMENT_STATUSES = [
    AppointmentStatus.REQUESTED,
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.CHECKED_IN,
    AppointmentStatus.IN_PROGRESS,
    AppointmentStatus.RESCHEDULE_PENDING,
]


class ScheduleRepository:

    @staticmethod
    def get_doctor_for_update(
        db: Session,
        doctor_id: int,
    ) -> Doctor | None:
        statement = (
            select(Doctor)
            .where(Doctor.id == doctor_id)
            .with_for_update()
        )
        return db.scalars(statement).first()

    @staticmethod
    def get_day_schedules(
        db: Session,
        doctor_id: int,
        weekday: int,
    ) -> list[DoctorSchedule]:
        statement = (
            select(DoctorSchedule)
            .where(
                DoctorSchedule.doctor_id == doctor_id,
                DoctorSchedule.weekday == weekday,
            )
            .order_by(DoctorSchedule.start_time)
        )
        return list(db.scalars(statement).all())

    @staticmethod
    def get_confirmed_appointments(
        db: Session,
        doctor_id: int,
        weekday: int,
    ) -> list[Appointment]:
        statement = select(Appointment).where(
            Appointment.doctor_id == doctor_id,
            Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES),
            Appointment.start_at >= datetime.now(timezone.utc),
        )

        return [
            appointment
            for appointment in db.scalars(statement).all()
            if appointment.start_at.weekday() == weekday
        ]

    @staticmethod
    def delete_day_schedules(
        db: Session,
        doctor_id: int,
        weekday: int,
    ) -> None:
        for schedule in ScheduleRepository.get_day_schedules(
            db, doctor_id, weekday
        ):
            db.delete(schedule)

    @staticmethod
    def create_period(
        db: Session,
        doctor_id: int,
        weekday: int,
        period_data: dict,
    ) -> DoctorSchedule:
        schedule = DoctorSchedule(
            doctor_id=doctor_id,
            weekday=weekday,
            **period_data,
        )
        db.add(schedule)
        db.flush()
        return schedule
