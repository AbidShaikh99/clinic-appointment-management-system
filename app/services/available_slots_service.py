from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.appointment_policy import consultation_duration_minutes
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.enums import AppointmentType
from app.repositories.appointment_repository import (
    AppointmentRepository,
)
from app.schemas.available_slots import (
    AvailableSlot,
    AvailableSlotsQuery,
)


class AvailableSlotsService:

    @staticmethod
    def _get_doctors(
        db: Session,
        filters: AvailableSlotsQuery,
    ) -> list[Doctor]:
        statement = select(Doctor).where(
            Doctor.is_active.is_(True)
        )

        if filters.doctor_id is not None:
            statement = statement.where(
                Doctor.id == filters.doctor_id
            )

        if filters.specialization is not None:
            statement = statement.where(
                func.lower(Doctor.specialization)
                == filters.specialization.lower()
            )

        statement = statement.order_by(Doctor.id)

        return list(db.scalars(statement).all())

    @staticmethod
    def _fits_schedule(
        db: Session,
        doctor_id: int,
        start_at: datetime,
        end_at: datetime,
    ) -> bool:
        schedules = AppointmentRepository.get_schedules(
            db,
            doctor_id,
            start_at.weekday(),
        )

        start_clock = start_at.time().replace(tzinfo=None)
        end_clock = end_at.time().replace(tzinfo=None)

        for schedule in schedules:
            if (
                start_clock < schedule.start_time
                or end_clock > schedule.end_time
            ):
                continue

            if (
                schedule.break_start is not None
                and schedule.break_end is not None
                and start_clock < schedule.break_end
                and end_clock > schedule.break_start
            ):
                continue

            return True

        return False

    @staticmethod
    def _capacity_available(
        db: Session,
        doctor: Doctor,
        start_at: datetime,
        timezone: ZoneInfo,
    ) -> bool:
        local_day_start = datetime.combine(
            start_at.date(),
            time.min,
            tzinfo=timezone,
        )
        next_day_start = local_day_start + timedelta(days=1)

        count = AppointmentRepository.count_daily_appointments(
            db,
            doctor.id,
            local_day_start,
            next_day_start,
        )

        return count < doctor.max_daily_appointments

    
    @staticmethod
    def _find_slots_for_date(
        db: Session,
        doctor: Doctor,
        search_date: date,
        duration_minutes: int,
        timezone: ZoneInfo,
        interval_minutes: int,
        patient_id: int | None,
        preferred_time: time | None = None,
    ) -> list[AvailableSlot]:
        duration = timedelta(minutes=duration_minutes)

        day_start = datetime.combine(
            search_date,
            time.min,
            tzinfo=timezone,
        )
        next_day_start = day_start + timedelta(days=1)
        now = datetime.now(timezone)

        schedules = AppointmentRepository.get_schedules(
            db,
            doctor.id,
            search_date.weekday(),
        )

        slots = []

        for schedule in schedules:
            period_start = datetime.combine(
                search_date,
                schedule.start_time,
                tzinfo=timezone,
            )
            period_end = datetime.combine(
                search_date,
                schedule.end_time,
                tzinfo=timezone,
            )

            candidate_start = period_start

            if preferred_time is not None:
                preferred_start = datetime.combine(
                    search_date,
                    preferred_time,
                    tzinfo=timezone,
                )
                candidate_start = max(
                    candidate_start,
                    preferred_start,
                )

            candidate_start = max(candidate_start, now)

            # Align the first candidate to the configured interval.
            if candidate_start > period_start and interval_minutes > 0:
                elapsed_seconds = (
                    candidate_start - period_start
                ).total_seconds()

                elapsed_minutes = elapsed_seconds / 60

                interval_steps = int(
                    (elapsed_minutes + interval_minutes - 1e-9)
                    // interval_minutes
                )

                candidate_start = period_start + timedelta(
                    minutes=interval_steps * interval_minutes
                )

            while candidate_start + duration <= period_end:
                candidate_end = candidate_start + duration

                fits_schedule = AvailableSlotsService._fits_schedule(
                    db,
                    doctor.id,
                    candidate_start,
                    candidate_end,
                )

                has_leave = AppointmentRepository.has_leave_conflict(
                    db,
                    doctor.id,
                    candidate_start,
                    candidate_end,
                )

                has_doctor_conflict = (
                    AppointmentRepository.has_doctor_conflict(
                        db,
                        doctor.id,
                        candidate_start,
                        candidate_end,
                    )
                )

                has_patient_conflict = False

                if patient_id is not None:
                    has_patient_conflict = (
                        AppointmentRepository.has_patient_conflict(
                            db,
                            patient_id,
                            candidate_start,
                            candidate_end,
                        )
                    )

                has_capacity = (
                    AvailableSlotsService._capacity_available(
                        db,
                        doctor,
                        candidate_start,
                        timezone,
                    )
                )

                if (
                    fits_schedule
                    and not has_leave
                    and not has_doctor_conflict
                    and not has_patient_conflict
                    and has_capacity
                ):
                    slots.append(
                        AvailableSlot(
                            doctor_id=doctor.id,
                            doctor_name=doctor.name,
                            specialization=doctor.specialization,
                            start_at=candidate_start.isoformat(),
                            end_at=candidate_end.isoformat(),
                            duration_minutes=duration_minutes,
                        )
                    )

                candidate_start += timedelta(
                    minutes=interval_minutes
                )

        return slots


    @staticmethod
    def search(
        db: Session,
        filters: AvailableSlotsQuery,
    ) -> dict:
        timezone = ZoneInfo(filters.timezone_name)

        if filters.patient_id is not None:
            patient = db.get(Patient, filters.patient_id)
            if patient is None:
                raise ValueError("Patient not found.")

        doctors = AvailableSlotsService._get_doctors(
            db,
            filters,
        )

        if filters.doctor_id is not None and not any(
            doctor.id == filters.doctor_id for doctor in doctors
        ):
            raise LookupError(
                "Doctor not found or is inactive, or does not match the supplied specialization."
            )

        available_slots = []

        for doctor in doctors:
            slots = AvailableSlotsService._find_slots_for_date(
                db=db,
                doctor=doctor,
                search_date=filters.appointment_date,
                duration_minutes=consultation_duration_minutes(
                    doctor,
                    filters.appointment_type,
                ),
                timezone=timezone,
                interval_minutes=filters.slot_interval_minutes,
                patient_id=filters.patient_id,
                preferred_time=filters.preferred_time,
            )
            available_slots.extend(slots)

        available_slots.sort(
            key=lambda slot: (
                slot.start_at,
                slot.doctor_id,
            )
        )

        nearest_alternatives = []

        # If the requested date has no available slots, look at
        # the next seven days and return the earliest alternatives.
        if not available_slots:
            for day_offset in range(1, 8):
                alternative_date = (
                    filters.appointment_date
                    + timedelta(days=day_offset)
                )

                for doctor in doctors:
                    slots = AvailableSlotsService._find_slots_for_date(
                        db=db,
                        doctor=doctor,
                        search_date=alternative_date,
                        duration_minutes=consultation_duration_minutes(
                            doctor,
                            filters.appointment_type,
                        ),
                        timezone=timezone,
                        interval_minutes=filters.slot_interval_minutes,
                        patient_id=filters.patient_id,
                        preferred_time=None,
                    )
                    nearest_alternatives.extend(slots)

                if nearest_alternatives:
                    break

        nearest_alternatives.sort(
            key=lambda slot: (
                slot.start_at,
                slot.doctor_id,
            )
        )

        return {
            "appointment_date": filters.appointment_date,
            "appointment_type": filters.appointment_type,
            "timezone_name": filters.timezone_name,
            "available_slots": available_slots,
            "nearest_alternatives": nearest_alternatives[:10],
        }
