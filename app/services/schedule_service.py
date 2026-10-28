from datetime import datetime, time

from sqlalchemy.orm import Session

from app.repositories.schedule_repository import ScheduleRepository
from app.schemas.schedule import DoctorScheduleCreate


class ScheduleConflictError(Exception):
    def __init__(self, affected_appointments: list[dict]):
        self.affected_appointments = affected_appointments
        super().__init__("Schedule change affects confirmed appointments.")


class DoctorNotFoundError(Exception):
    pass


def period_contains_appointment(
    appointment_start: datetime,
    appointment_end: datetime,
    period,
) -> bool:
    start = appointment_start.time().replace(tzinfo=None)
    end = appointment_end.time().replace(tzinfo=None)

    # Appointment must fit entirely inside the working period.
    if start < period.start_time or end > period.end_time:
        return False

    # Appointment cannot overlap the configured break.
    if period.break_start is not None and period.break_end is not None:
        if start < period.break_end and end > period.break_start:
            return False

    return True


class ScheduleService:

    @staticmethod
    def configure_schedule(
        db: Session,
        doctor_id: int,
        schedule_data: DoctorScheduleCreate,
    ):
        try:
            # Lock the doctor row while checking and changing schedules.
            doctor = ScheduleRepository.get_doctor_for_update(
                db, doctor_id
            )

            if doctor is None:
                raise DoctorNotFoundError("Doctor not found.")

            weekday = schedule_data.weekday
            requested_periods = schedule_data.periods

            appointments = ScheduleRepository.get_confirmed_appointments(
                db, doctor_id, weekday
            )

            affected = []

            for appointment in appointments:
                fits = any(
                    period_contains_appointment(
                        appointment.start_at,
                        appointment.end_at,
                        period,
                    )
                    for period in requested_periods
                )

                if not fits:
                    affected.append({
                        "appointment_id": appointment.id,
                        "patient_id": appointment.patient_id,
                        "start_at": appointment.start_at.isoformat(),
                        "end_at": appointment.end_at.isoformat(),
                        "reason": (
                            "Appointment would fall outside the new "
                            "working periods or overlap a break."
                        ),
                    })

            if affected:
                raise ScheduleConflictError(affected)

            # Replace this weekday's schedule only after all checks pass.
            ScheduleRepository.delete_day_schedules(
                db, doctor_id, weekday
            )
            
            db.flush()

            created = []

            for period in requested_periods:
                schedule = ScheduleRepository.create_period(
                    db=db,
                    doctor_id=doctor_id,
                    weekday=weekday,
                    period_data=period.model_dump(),
                )
                created.append(schedule)

            db.commit()

            for schedule in created:
                db.refresh(schedule)

            return created

        except Exception:
            db.rollback()
            raise
