from datetime import datetime, time, timedelta, timezone
import math
import secrets
from app.core.config import settings
from app.core.appointment_policy import consultation_duration_minutes
from app.models.doctor import Doctor
from app.models.enums import (
    AppointmentPriority,
    AppointmentStatus,
    AppointmentType,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.models.reschedule_proposal import RescheduleProposal
from app.schemas.reschedule_proposal import RescheduleRequest
from app.models.appointment import Appointment
from app.repositories.appointment_repository import (
    AppointmentRepository,
)
from app.schemas.appointment import AppointmentCreate
from app.schemas.waiting_list import WaitingListMatchQuery
from app.services.waiting_list_service import (
    WaitingListMatchError,
    WaitingListMatchService,
)


class AppointmentBookingError(Exception):
    def __init__(
        self,
        message: str,
        alternatives: list[dict] | None = None,
    ):
        self.alternatives = alternatives or []
        super().__init__(message)

class AppointmentCancellationError(Exception):
    pass

class AppointmentCheckInError(Exception):
    pass

class AppointmentLifecycleError(Exception):
    pass

class AppointmentRescheduleError(Exception):
    pass

class AppointmentService:

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

        for schedule in schedules:
            if (
                start_at.time().replace(tzinfo=None)
                < schedule.start_time
                or end_at.time().replace(tzinfo=None)
                > schedule.end_time
            ):
                continue

            if (
                schedule.break_start is not None
                and schedule.break_end is not None
            ):
                start_clock = start_at.time().replace(tzinfo=None)
                end_clock = end_at.time().replace(tzinfo=None)

                overlaps_break = (
                    start_clock < schedule.break_end
                    and end_clock > schedule.break_start
                )

                if overlaps_break:
                    continue

            return True

        return False

    @staticmethod
    def _daily_capacity_available(
        db: Session,
        doctor_id: int,
        start_at: datetime,
        max_daily_appointments: int,
        exclude_appointment_id: int | None = None,
    ) -> bool:
        tz = start_at.tzinfo

        day_start = datetime.combine(
            start_at.date(),
            time.min,
            tzinfo=tz,
        )
        next_day_start = day_start + timedelta(days=1)

        count = AppointmentRepository.count_daily_appointments(
            db,
            doctor_id,
            day_start,
            next_day_start,
            exclude_appointment_id=exclude_appointment_id,
        )

        return count < max_daily_appointments

    @staticmethod
    def _find_alternatives(
        db: Session,
        patient_id: int,
        doctor_id: int,
        requested_start: datetime,
        duration: timedelta,
        max_options: int = 3,
    ) -> list[dict]:
        doctor = db.get(Doctor, doctor_id)

        if doctor is None:
            return []

        alternatives = []
        tz = requested_start.tzinfo

        # Include the following week so recurring schedules can provide
        # alternatives when no later slot exists on the requested day.
        for day_offset in range(14):
            day = requested_start.date() + timedelta(days=day_offset)

            schedules = AppointmentRepository.get_schedules(
                db,
                doctor_id,
                day.weekday(),
            )

            for schedule in schedules:
                period_start = datetime.combine(
                    day,
                    schedule.start_time,
                    tzinfo=tz,
                )
                period_end = datetime.combine(
                    day,
                    schedule.end_time,
                    tzinfo=tz,
                )

                candidate_start = period_start

                if day_offset == 0:
                    candidate_start = max(
                        candidate_start,
                        requested_start + timedelta(minutes=15),
                    )

                while candidate_start + duration <= period_end:
                    candidate_end = candidate_start + duration

                    fits_schedule = AppointmentService._fits_schedule(
                        db,
                        doctor_id,
                        candidate_start,
                        candidate_end,
                    )

                    has_leave = (
                        AppointmentRepository.has_leave_conflict(
                            db,
                            doctor_id,
                            candidate_start,
                            candidate_end,
                        )
                    )

                    has_doctor_conflict = (
                        AppointmentRepository.has_doctor_conflict(
                            db,
                            doctor_id,
                            candidate_start,
                            candidate_end,
                        )
                    )

                    has_patient_conflict = (
                        AppointmentRepository.has_patient_conflict(
                            db,
                            patient_id,
                            candidate_start,
                            candidate_end,
                        )
                    )

                    has_capacity = (
                        AppointmentService._daily_capacity_available(
                            db,
                            doctor_id,
                            candidate_start,
                            doctor.max_daily_appointments,
                        )
                    )

                    if (
                        fits_schedule
                        and not has_leave
                        and not has_doctor_conflict
                        and not has_patient_conflict
                        and has_capacity
                    ):
                        alternatives.append(
                            {
                                "doctor_id": doctor_id,
                                "start_at": candidate_start.isoformat(),
                                "end_at": candidate_end.isoformat(),
                            }
                        )

                        if len(alternatives) >= max_options:
                            return alternatives

                    candidate_start += timedelta(minutes=15)

        return alternatives

    @staticmethod
    def book_appointment(
        db: Session,
        appointment_data: AppointmentCreate,
    ) -> tuple[Appointment, list[dict]]:
        try:
            # Lock the doctor first so bookings for the same doctor
            # are serialized in PostgreSQL.
            doctor = AppointmentRepository.get_doctor_for_update(
                db,
                appointment_data.doctor_id,
            )

            if doctor is None:
                raise AppointmentBookingError("Doctor not found.")

            if not doctor.is_active:
                raise AppointmentBookingError(
                    "The selected doctor is inactive."
                )

            # Lock the patient as well to serialize simultaneous
            # bookings for the same patient across different doctors.
            patient = AppointmentRepository.get_patient_for_update(
                db,
                appointment_data.patient_id,
            )

            if patient is None:
                raise AppointmentBookingError("Patient not found.")

            start_at = appointment_data.start_at
            duration = timedelta(
                minutes=consultation_duration_minutes(
                    doctor,
                    appointment_data.appointment_type,
                )
            )
            end_at = start_at + duration

            if start_at <= datetime.now(timezone.utc):
                raise AppointmentBookingError(
                    "Appointments must be booked for a future time."
                )

            # Validate working hours and breaks.
            if not AppointmentService._fits_schedule(
                db,
                doctor.id,
                start_at,
                end_at,
            ):
                alternatives = AppointmentService._find_alternatives(
                    db,
                    patient.id,
                    doctor.id,
                    start_at,
                    duration,
                )
                raise AppointmentBookingError(
                    "Requested time is outside working hours or overlaps a break.",
                    alternatives,
                )

            # Check doctor leave.
            if AppointmentRepository.has_leave_conflict(
                db,
                doctor.id,
                start_at,
                end_at,
            ):
                alternatives = AppointmentService._find_alternatives(
                    db,
                    patient.id,
                    doctor.id,
                    start_at,
                    duration,
                )
                raise AppointmentBookingError(
                    "Doctor is on leave during the requested time.",
                    alternatives,
                )

            # Check other appointments for this doctor.
            if AppointmentRepository.has_doctor_conflict(
                db,
                doctor.id,
                start_at,
                end_at,
            ):
                alternatives = AppointmentService._find_alternatives(
                    db,
                    patient.id,
                    doctor.id,
                    start_at,
                    duration,
                )
                raise AppointmentBookingError(
                    "Doctor already has an appointment during this period.",
                    alternatives,
                )

            # Check if this patient already has another appointment
            # at the requested time, even with a different doctor.
            if AppointmentRepository.has_patient_conflict(
                db,
                patient.id,
                start_at,
                end_at,
            ):
                alternatives = AppointmentService._find_alternatives(
                    db,
                    patient.id,
                    doctor.id,
                    start_at,
                    duration,
                )
                raise AppointmentBookingError(
                    "Patient already has an overlapping appointment.",
                    alternatives,
                )

            # Enforce daily capacity.
            if not AppointmentService._daily_capacity_available(
                db,
                doctor.id,
                start_at,
                doctor.max_daily_appointments,
            ):
                alternatives = AppointmentService._find_alternatives(
                    db,
                    patient.id,
                    doctor.id,
                    start_at,
                    duration,
                )
                raise AppointmentBookingError(
                    "Doctor has reached the daily appointment capacity.",
                    alternatives,
                )

            priority = (
                AppointmentPriority.EMERGENCY
                if appointment_data.appointment_type
                == AppointmentType.EMERGENCY
                else AppointmentPriority.NORMAL
            )

            appointment = Appointment(
                patient_id=patient.id,
                doctor_id=doctor.id,
                start_at=start_at,
                end_at=end_at,
                appointment_type=appointment_data.appointment_type,
                priority=priority,
                status=AppointmentStatus.CONFIRMED,
                booking_reference=(
                    f"APT-{start_at:%Y%m%d}-"
                    f"{secrets.token_hex(4).upper()}"
                ),
                booked_at=datetime.now(timezone.utc),
            )

            AppointmentRepository.create(db, appointment)

            # Only confirm after the transaction commits.
            db.commit()
            db.refresh(appointment)

            return appointment, []

        except AppointmentBookingError:
            db.rollback()
            raise

        except IntegrityError as exc:
            db.rollback()
            raise AppointmentBookingError(
                "Booking could not be completed because of a database conflict. Please retry."
            ) from exc

        except Exception:
            db.rollback()
            raise

        
    @staticmethod
    def get_appointment(db: Session, appointment_id: int):
        appointment = AppointmentRepository.get_by_id(
            db,
            appointment_id,
        )

        if appointment is None:
            raise LookupError(
                f"Appointment with ID {appointment_id} not found."
            )

        return appointment
    
    @staticmethod
    def cancel_appointment(
        db: Session,
        appointment_id: int,
    ) -> tuple[Appointment, bool, dict]:
        try:
            # Lock the appointment row before checking its status.
            appointment = (
                AppointmentRepository.get_by_id_for_update(
                    db,
                    appointment_id,
                )
            )

            if appointment is None:
                raise LookupError(
                    f"Appointment with ID {appointment_id} not found."
                )

            # Do not process a cancellation twice.
            if appointment.status == AppointmentStatus.CANCELLED:
                raise AppointmentCancellationError(
                    "This appointment has already been cancelled."
                )

            # Only these statuses are cancellable under the
            # initial status-based policy.
            cancellable_statuses = {
                AppointmentStatus.REQUESTED,
                AppointmentStatus.CONFIRMED,
            }

            if appointment.status not in cancellable_statuses:
                raise AppointmentCancellationError(
                    f"Appointment cannot be cancelled because "
                    f"its current status is {appointment.status.value}."
                )

            # Update the existing appointment.
            appointment.status = AppointmentStatus.CANCELLED

            # Commit the cancellation before matching so the slot is
            # released even if matching cannot be completed.
            db.commit()
            db.refresh(appointment)

            start_at = appointment.start_at
            if start_at.tzinfo is None:
                start_at = start_at.replace(tzinfo=timezone.utc)

            if start_at <= datetime.now(timezone.utc):
                matching = {
                    "status": "NOT_REQUIRED",
                    "reason": "The cancelled appointment is not in the future.",
                    "eligible_candidates": [],
                }
            else:
                duration_minutes = int(
                    (
                        appointment.end_at - appointment.start_at
                    ).total_seconds()
                    // 60
                )
                match_request = WaitingListMatchQuery(
                    doctor_id=appointment.doctor_id,
                    date=start_at.date(),
                    start_time=start_at.time().replace(tzinfo=None),
                    available_duration_minutes=duration_minutes,
                    appointment_type=appointment.appointment_type,
                )

                try:
                    candidates = (
                        WaitingListMatchService.match_waiting_patients(
                            db,
                            match_request,
                        )
                    )
                    matching = {
                        "status": "COMPLETED",
                        "eligible_candidates": candidates,
                    }
                except WaitingListMatchError as exc:
                    matching = {
                        "status": "FAILED",
                        "error": str(exc),
                        "eligible_candidates": [],
                    }

            return appointment, True, matching

        except Exception:
            db.rollback()
            raise

    @staticmethod
    def check_in_appointment(
        db: Session,
        appointment_id: int,
    ) -> dict:
        try:
            appointment = AppointmentRepository.get_by_id_for_update(
                db,
                appointment_id,
            )
            if appointment is None:
                raise LookupError(
                    f"Appointment with ID {appointment_id} not found."
                )

            if appointment.status != AppointmentStatus.CONFIRMED:
                raise AppointmentCheckInError(
                    "Only confirmed appointments can be checked in; "
                    f"current status is {appointment.status.value}."
                )

            start_at = appointment.start_at
            if start_at.tzinfo is None or start_at.utcoffset() is None:
                start_at = start_at.replace(tzinfo=timezone.utc)
            else:
                start_at = start_at.astimezone(timezone.utc)

            checked_in_at = datetime.now(timezone.utc)
            grace_deadline = start_at + timedelta(
                minutes=settings.CHECK_IN_GRACE_PERIOD_MINUTES
            )
            if checked_in_at > grace_deadline:
                raise AppointmentCheckInError(
                    "The check-in grace period has expired."
                )

            doctor = AppointmentRepository.get_doctor_for_update(
                db,
                appointment.doctor_id,
            )
            if doctor is None:
                raise AppointmentCheckInError(
                    "The appointment's doctor could not be found."
                )

            appointment.status = AppointmentStatus.CHECKED_IN
            appointment.checked_in_at = checked_in_at
            db.flush()

            day_start = datetime.combine(
                start_at.date(),
                time.min,
                tzinfo=timezone.utc,
            )
            next_day_start = day_start + timedelta(days=1)
            queue = AppointmentRepository.get_queue_for_doctor(
                db,
                doctor.id,
                day_start,
                next_day_start,
            )

            def queue_key(
                item: Appointment,
            ) -> tuple[int, int, datetime, int]:
                is_in_progress = (
                    item.status == AppointmentStatus.IN_PROGRESS
                )
                is_emergency = (
                    settings.CHECK_IN_EMERGENCY_PRIORITY_ENABLED
                    and item.priority == AppointmentPriority.EMERGENCY
                )
                check_in_time = item.checked_in_at or item.start_at
                if (
                    check_in_time.tzinfo is None
                    or check_in_time.utcoffset() is None
                ):
                    check_in_time = check_in_time.replace(tzinfo=timezone.utc)
                else:
                    check_in_time = check_in_time.astimezone(timezone.utc)
                return (
                    0 if is_in_progress else 1,
                    0 if is_emergency else 1,
                    check_in_time,
                    item.id,
                )

            queue.sort(key=queue_key)
            queue_position = next(
                index
                for index, queued_appointment in enumerate(queue, start=1)
                if queued_appointment.id == appointment.id
            )
            estimated_wait_minutes = sum(
                max(
                    0,
                    math.ceil(
                        AppointmentService._remaining_queue_minutes(
                            queued_appointment,
                            checked_in_at,
                        )
                    ),
                )
                for queued_appointment in queue[: queue_position - 1]
            )

            db.commit()
            db.refresh(appointment)

            minutes_late = max(
                0,
                math.ceil(
                    (checked_in_at - start_at).total_seconds() / 60
                ),
            )
            return {
                "appointment_id": appointment.id,
                "status": appointment.status.value,
                "checked_in_at": appointment.checked_in_at,
                "is_late": checked_in_at > start_at,
                "minutes_late": minutes_late,
                "queue_position": queue_position,
                "estimated_wait_minutes": estimated_wait_minutes,
            }

        except (LookupError, AppointmentCheckInError):
            db.rollback()
            raise

        except Exception:
            db.rollback()
            raise

    @staticmethod
    def start_consultation(
        db: Session,
        appointment_id: int,
    ) -> dict:
        try:
            appointment = AppointmentRepository.get_by_id_for_update(
                db,
                appointment_id,
            )
            if appointment is None:
                raise LookupError(
                    f"Appointment with ID {appointment_id} not found."
                )
            if appointment.status != AppointmentStatus.CHECKED_IN:
                raise AppointmentLifecycleError(
                    "Only checked-in appointments can start a consultation; "
                    f"current status is {appointment.status.value}."
                )

            doctor = AppointmentRepository.get_doctor_for_update(
                db,
                appointment.doctor_id,
            )
            if doctor is None:
                raise AppointmentLifecycleError(
                    "The appointment's doctor could not be found."
                )

            active_consultations = (
                AppointmentRepository.get_in_progress_for_doctor(
                    db,
                    doctor.id,
                )
            )
            if active_consultations:
                raise AppointmentLifecycleError(
                    "The doctor already has an in-progress consultation "
                    f"(appointment {active_consultations[0].id})."
                )

            appointment.consultation_started_at = datetime.now(timezone.utc)
            appointment.status = AppointmentStatus.IN_PROGRESS
            db.commit()
            db.refresh(appointment)

            return {
                "appointment_id": appointment.id,
                "status": appointment.status.value,
                "consultation_started_at": appointment.consultation_started_at,
            }

        except (LookupError, AppointmentLifecycleError):
            db.rollback()
            raise

        except Exception:
            db.rollback()
            raise

    @staticmethod
    def complete_consultation(
        db: Session,
        appointment_id: int,
    ) -> dict:
        try:
            appointment = AppointmentRepository.get_by_id_for_update(
                db,
                appointment_id,
            )
            if appointment is None:
                raise LookupError(
                    f"Appointment with ID {appointment_id} not found."
                )
            if appointment.status != AppointmentStatus.IN_PROGRESS:
                raise AppointmentLifecycleError(
                    "Only in-progress consultations can be completed; "
                    f"current status is {appointment.status.value}."
                )
            if appointment.consultation_started_at is None:
                raise AppointmentLifecycleError(
                    "The consultation must have a recorded start time "
                    "before it can be completed."
                )

            doctor = AppointmentRepository.get_doctor_for_update(
                db,
                appointment.doctor_id,
            )
            if doctor is None:
                raise AppointmentLifecycleError(
                    "The appointment's doctor could not be found."
                )

            consultation_started_at = appointment.consultation_started_at
            if (
                consultation_started_at.tzinfo is None
                or consultation_started_at.utcoffset() is None
            ):
                consultation_started_at = consultation_started_at.replace(
                    tzinfo=timezone.utc
                )
            else:
                consultation_started_at = consultation_started_at.astimezone(
                    timezone.utc
                )

            consultation_ended_at = datetime.now(timezone.utc)
            if consultation_ended_at < consultation_started_at:
                raise AppointmentLifecycleError(
                    "Consultation completion time cannot precede its start."
                )

            appointment.consultation_ended_at = consultation_ended_at
            appointment.consultation_duration_seconds = int(
                (consultation_ended_at - consultation_started_at).total_seconds()
            )
            appointment.status = AppointmentStatus.COMPLETED
            db.flush()

            day_start = datetime.combine(
                appointment.start_at.date(),
                time.min,
                tzinfo=timezone.utc,
            )
            next_day_start = day_start + timedelta(days=1)
            waiting_queue = AppointmentRepository.get_queue_for_doctor(
                db,
                doctor.id,
                day_start,
                next_day_start,
            )

            def waiting_queue_key(item: Appointment):
                check_in_time = item.checked_in_at or item.start_at
                if (
                    check_in_time.tzinfo is None
                    or check_in_time.utcoffset() is None
                ):
                    check_in_time = check_in_time.replace(
                        tzinfo=timezone.utc
                    )
                else:
                    check_in_time = check_in_time.astimezone(timezone.utc)
                return (
                    0
                    if (
                        settings.CHECK_IN_EMERGENCY_PRIORITY_ENABLED
                        and item.priority == AppointmentPriority.EMERGENCY
                    )
                    else 1,
                    check_in_time,
                    item.id,
                )

            waiting_queue.sort(
                key=waiting_queue_key
            )

            estimated_wait_minutes = 0
            queue = []
            for position, queued_appointment in enumerate(
                waiting_queue,
                start=1,
            ):
                if queued_appointment.id == appointment.id:
                    continue
                queue.append({
                    "appointment_id": queued_appointment.id,
                    "queue_position": position,
                    "estimated_wait_minutes": estimated_wait_minutes,
                })
                duration = max(
                    0,
                    math.ceil(
                        (
                            queued_appointment.end_at
                            - queued_appointment.start_at
                        ).total_seconds()
                        / 60
                    ),
                )
                estimated_wait_minutes += duration

            db.commit()
            db.refresh(appointment)

            return {
                "appointment_id": appointment.id,
                "status": appointment.status.value,
                "consultation_started_at": appointment.consultation_started_at,
                "consultation_ended_at": appointment.consultation_ended_at,
                "consultation_duration_seconds": (
                    appointment.consultation_duration_seconds
                ),
                "queue": queue,
            }

        except (LookupError, AppointmentLifecycleError):
            db.rollback()
            raise

        except Exception:
            db.rollback()
            raise

    @staticmethod
    def mark_no_show(
        db: Session,
        appointment_id: int,
    ) -> dict:
        try:
            appointment = AppointmentRepository.get_by_id_for_update(
                db,
                appointment_id,
            )
            if appointment is None:
                raise LookupError(
                    f"Appointment with ID {appointment_id} not found."
                )
            if appointment.status != AppointmentStatus.CONFIRMED:
                raise AppointmentLifecycleError(
                    "Only confirmed appointments can be marked as no-show; "
                    f"current status is {appointment.status.value}."
                )

            start_at = appointment.start_at
            if start_at.tzinfo is None or start_at.utcoffset() is None:
                start_at = start_at.replace(tzinfo=timezone.utc)
            else:
                start_at = start_at.astimezone(timezone.utc)

            no_show_at = datetime.now(timezone.utc)
            grace_deadline = start_at + timedelta(
                minutes=settings.CHECK_IN_GRACE_PERIOD_MINUTES
            )
            if no_show_at <= grace_deadline:
                raise AppointmentLifecycleError(
                    "The appointment cannot be marked as no-show until "
                    "the check-in grace period has expired."
                )

            doctor = AppointmentRepository.get_doctor_for_update(
                db,
                appointment.doctor_id,
            )
            if doctor is None:
                raise AppointmentLifecycleError(
                    "The appointment's doctor could not be found."
                )

            appointment.status = AppointmentStatus.NO_SHOW
            appointment.no_show_at = no_show_at
            db.commit()
            db.refresh(appointment)

            return {
                "appointment_id": appointment.id,
                "status": appointment.status.value,
                "no_show_at": appointment.no_show_at,
                "slot_released": True,
            }

        except (LookupError, AppointmentLifecycleError):
            db.rollback()
            raise

        except Exception:
            db.rollback()
            raise

    @staticmethod
    def _remaining_queue_minutes(
        appointment: Appointment,
        now: datetime,
    ) -> float:
        scheduled_seconds = max(
            0,
            (
                appointment.end_at - appointment.start_at
            ).total_seconds(),
        )
        if appointment.status != AppointmentStatus.IN_PROGRESS:
            return scheduled_seconds / 60

        started_at = appointment.consultation_started_at
        if started_at is None:
            return scheduled_seconds / 60
        if started_at.tzinfo is None or started_at.utcoffset() is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        else:
            started_at = started_at.astimezone(timezone.utc)
        return max(
            0,
            scheduled_seconds - max(0, (now - started_at).total_seconds()),
        ) / 60


    @staticmethod
    def _validate_reschedule_slot(
        db: Session,
        appointment: Appointment,
        doctor: Doctor,
        start_at: datetime,
    ) -> datetime:
        if start_at.tzinfo is None or start_at.utcoffset() is None:
            start_at = start_at.replace(tzinfo=timezone.utc)

        if not doctor.is_active:
            raise AppointmentRescheduleError(
                "The proposed doctor is inactive."
            )

        if start_at <= datetime.now(timezone.utc):
            raise AppointmentRescheduleError(
                "The proposed appointment must be in the future."
            )

        duration = timedelta(
            minutes=consultation_duration_minutes(
                doctor,
                appointment.appointment_type,
            )
        )
        end_at = start_at + duration

        if not AppointmentService._fits_schedule(
            db, doctor.id, start_at, end_at
        ):
            raise AppointmentRescheduleError(
                "The proposed time is outside working hours "
                "or overlaps a break."
            )

        if AppointmentRepository.has_leave_conflict(
            db, doctor.id, start_at, end_at
        ):
            raise AppointmentRescheduleError(
                "The proposed doctor is on leave during this period."
            )

        if AppointmentRepository.has_doctor_conflict(
            db,
            doctor.id,
            start_at,
            end_at,
            exclude_appointment_id=appointment.id,
        ):
            raise AppointmentRescheduleError(
                "The proposed doctor already has an overlapping appointment."
            )

        if AppointmentRepository.has_patient_conflict(
            db,
            appointment.patient_id,
            start_at,
            end_at,
            exclude_appointment_id=appointment.id,
        ):
            raise AppointmentRescheduleError(
                "The patient already has an overlapping appointment."
            )

        if not AppointmentService._daily_capacity_available(
            db,
            doctor.id,
            start_at,
            doctor.max_daily_appointments,
            exclude_appointment_id=(
                appointment.id
                if doctor.id == appointment.doctor_id
                else None
            ),
        ):
            raise AppointmentRescheduleError(
                "The proposed doctor has reached the daily appointment capacity."
            )

        return end_at

    @staticmethod
    def request_reschedule(
        db: Session,
        appointment_id: int,
        request_data: RescheduleRequest,
    ) -> RescheduleProposal:
        try:
            appointment = (
                AppointmentRepository.get_by_id_for_update(
                    db, appointment_id
                )
            )

            if appointment is None:
                raise LookupError(
                    f"Appointment with ID {appointment_id} not found."
                )

            if appointment.status != AppointmentStatus.CONFIRMED:
                raise AppointmentRescheduleError(
                    "Only confirmed appointments can be rescheduled."
                )

            patient = AppointmentRepository.get_patient_for_update(
                db, appointment.patient_id
            )

            if patient is None:
                raise AppointmentRescheduleError(
                    "The appointment's patient was not found."
                )

            original_doctor = db.get(
                Doctor, appointment.doctor_id
            )

            if original_doctor is None:
                raise AppointmentRescheduleError(
                    "The original doctor was not found."
                )

            target_doctor_id = (
                request_data.proposed_doctor_id
                or appointment.doctor_id
            )

            doctor = AppointmentRepository.get_doctor_for_update(
                db, target_doctor_id
            )

            if doctor is None:
                raise AppointmentRescheduleError(
                    "The proposed doctor was not found."
                )

            # A replacement doctor must have the same specialization
            # as the original doctor.
            if (
                doctor.id != original_doctor.id
                and doctor.specialization.strip().casefold()
                != original_doctor.specialization.strip().casefold()
            ):
                raise AppointmentRescheduleError(
                    "The proposed doctor does not have the required "
                    "specialization."
                )

            end_at = AppointmentService._validate_reschedule_slot(
                db,
                appointment,
                doctor,
                request_data.proposed_start_at,
            )

            proposal = RescheduleProposal(
                leave_id=None,
                appointment_id=appointment.id,
                proposed_doctor_id=doctor.id,
                proposed_start_at=request_data.proposed_start_at,
                proposed_end_at=end_at,
                status="PENDING",
            )

            AppointmentRepository.create_proposal(db, proposal)

            # Do not change the original appointment here.
            db.commit()
            db.refresh(proposal)
            return proposal

        except Exception:
            db.rollback()
            raise

    @staticmethod
    def accept_reschedule(
        db: Session,
        proposal_id: int,
    ) -> tuple[RescheduleProposal, Appointment]:
        try:
            proposal = (
                AppointmentRepository.get_proposal_for_update(
                    db, proposal_id
                )
            )

            if proposal is None:
                raise LookupError(
                    f"Reschedule proposal {proposal_id} not found."
                )

            if proposal.status != "PENDING":
                raise AppointmentRescheduleError(
                    "Only pending proposals can be accepted."
                )

            appointment = (
                AppointmentRepository.get_by_id_for_update(
                    db, proposal.appointment_id
                )
            )

            if appointment is None:
                raise LookupError(
                    "The appointment associated with this proposal was not found."
                )

            if appointment.status != AppointmentStatus.CONFIRMED:
                raise AppointmentRescheduleError(
                    "The appointment is no longer confirmed."
                )

            patient = AppointmentRepository.get_patient_for_update(
                db, appointment.patient_id
            )

            if patient is None:
                raise AppointmentRescheduleError(
                    "The appointment's patient was not found."
                )

            original_doctor = db.get(
                Doctor, appointment.doctor_id
            )

            doctor = AppointmentRepository.get_doctor_for_update(
                db, proposal.proposed_doctor_id
            )

            if original_doctor is None or doctor is None:
                raise AppointmentRescheduleError(
                    "The original or proposed doctor no longer exists."
                )

            if (
                doctor.id != original_doctor.id
                and doctor.specialization.strip().casefold()
                != original_doctor.specialization.strip().casefold()
            ):
                raise AppointmentRescheduleError(
                    "The proposed doctor does not have the required "
                    "specialization."
                )

            # Revalidate because availability may have changed
            # after the proposal was created.
            end_at = AppointmentService._validate_reschedule_slot(
                db,
                appointment,
                doctor,
                proposal.proposed_start_at,
            )

            # Update both records in the same transaction.
            appointment.doctor_id = doctor.id
            appointment.start_at = proposal.proposed_start_at
            appointment.end_at = end_at
            proposal.status = "ACCEPTED"

            db.commit()
            db.refresh(appointment)
            db.refresh(proposal)

            return proposal, appointment

        except Exception:
            db.rollback()
            raise

    @staticmethod
    def reject_reschedule(
        db: Session,
        proposal_id: int,
    ) -> RescheduleProposal:
        try:
            proposal = (
                AppointmentRepository.get_proposal_for_update(
                    db, proposal_id
                )
            )

            if proposal is None:
                raise LookupError(
                    f"Reschedule proposal {proposal_id} not found."
                )

            if proposal.status != "PENDING":
                raise AppointmentRescheduleError(
                    "Only pending proposals can be rejected."
                )

            proposal.status = "REJECTED"

            db.commit()
            db.refresh(proposal)
            return proposal

        except Exception:
            db.rollback()
            raise

    @staticmethod
    def _validate_reschedule_slot(
        db: Session,
        appointment: Appointment,
        doctor: Doctor,
        start_at: datetime,
    ) -> datetime:
        if start_at.tzinfo is None or start_at.utcoffset() is None:
            start_at = start_at.replace(tzinfo=timezone.utc)

        if not doctor.is_active:
            raise AppointmentRescheduleError(
                "The proposed doctor is inactive."
            )

        if start_at <= datetime.now(timezone.utc):
            raise AppointmentRescheduleError(
                "The proposed appointment must be in the future."
            )

        end_at = start_at + timedelta(
            minutes=consultation_duration_minutes(
                doctor,
                appointment.appointment_type,
            )
        )

        if not AppointmentService._fits_schedule(
            db, doctor.id, start_at, end_at
        ):
            raise AppointmentRescheduleError(
                "The proposed time is outside working hours "
                "or overlaps a break."
            )

        if AppointmentRepository.has_leave_conflict(
            db, doctor.id, start_at, end_at
        ):
            raise AppointmentRescheduleError(
                "The proposed doctor is on leave."
            )

        if AppointmentRepository.has_doctor_conflict(
            db,
            doctor.id,
            start_at,
            end_at,
            exclude_appointment_id=appointment.id,
        ):
            raise AppointmentRescheduleError(
                "The proposed doctor already has an overlapping appointment."
            )

        if AppointmentRepository.has_patient_conflict(
            db,
            appointment.patient_id,
            start_at,
            end_at,
            exclude_appointment_id=appointment.id,
        ):
            raise AppointmentRescheduleError(
                "The patient already has an overlapping appointment."
            )

        exclude_id = (
            appointment.id
            if doctor.id == appointment.doctor_id
            else None
        )

        if not AppointmentService._daily_capacity_available(
            db,
            doctor.id,
            start_at,
            doctor.max_daily_appointments,
            exclude_appointment_id=exclude_id,
        ):
            raise AppointmentRescheduleError(
                "The proposed doctor has reached daily capacity."
            )

        return end_at

    @staticmethod
    def request_reschedule(
        db: Session,
        appointment_id: int,
        request_data: RescheduleRequest,
    ) -> RescheduleProposal:
        try:
            appointment = (
                AppointmentRepository.get_by_id_for_update(
                    db, appointment_id
                )
            )

            if appointment is None:
                raise LookupError(
                    f"Appointment with ID {appointment_id} not found."
                )

            if appointment.status != AppointmentStatus.CONFIRMED:
                raise AppointmentRescheduleError(
                    "Only confirmed appointments can be rescheduled."
                )

            original_doctor = db.get(
                Doctor, appointment.doctor_id
            )

            if original_doctor is None:
                raise AppointmentRescheduleError(
                    "The original doctor was not found."
                )

            target_doctor_id = (
                request_data.proposed_doctor_id
                if request_data.proposed_doctor_id is not None
                else appointment.doctor_id
            )

            # Lock the target doctor before checking availability.
            doctor = AppointmentRepository.get_doctor_for_update(
                db, target_doctor_id
            )

            if doctor is None:
                raise AppointmentRescheduleError(
                    "The proposed doctor was not found."
                )

            required_specialization = original_doctor.specialization
            if (
                request_data.required_specialization is not None
                and request_data.required_specialization.strip().casefold()
                != required_specialization.strip().casefold()
            ):
                raise AppointmentRescheduleError(
                    "The requested specialization does not match the "
                    "appointment's required specialization."
                )
            if (
                doctor.specialization.strip().casefold()
                != original_doctor.specialization.strip().casefold()
            ):
                raise AppointmentRescheduleError(
                    "The proposed doctor does not have the required "
                    "specialization."
                )

            # Follow the existing booking service's lock order:
            # doctor first, then patient.
            patient = AppointmentRepository.get_patient_for_update(
                db, appointment.patient_id
            )

            if patient is None:
                raise AppointmentRescheduleError(
                    "The appointment's patient was not found."
                )

            end_at = AppointmentService._validate_reschedule_slot(
                db,
                appointment,
                doctor,
                request_data.proposed_start_at,
            )

            proposal = RescheduleProposal(
                leave_id=None,
                appointment_id=appointment.id,
                proposed_doctor_id=doctor.id,
                proposed_start_at=request_data.proposed_start_at,
                proposed_end_at=end_at,
                status="PENDING",
            )

            AppointmentRepository.create_proposal(db, proposal)

            # The confirmed appointment is not changed here.
            db.commit()
            db.refresh(proposal)
            return proposal

        except Exception:
            db.rollback()
            raise

    @staticmethod
    def accept_reschedule(
        db: Session,
        proposal_id: int,
    ) -> tuple[RescheduleProposal, Appointment]:
        try:
            proposal = (
                AppointmentRepository.get_proposal_by_id(
                    db, proposal_id
                )
            )

            if proposal is None:
                raise LookupError(
                    f"Reschedule proposal {proposal_id} not found."
                )

            appointment = (
                AppointmentRepository.get_by_id_for_update(
                    db, proposal.appointment_id
                )
            )

            if appointment is None:
                raise LookupError(
                    "The associated appointment was not found."
                )

            proposal = (
                AppointmentRepository.get_proposal_for_update(
                    db, proposal_id
                )
            )

            if proposal is None:
                raise LookupError(
                    f"Reschedule proposal {proposal_id} not found."
                )

            if proposal.status != "PENDING":
                raise AppointmentRescheduleError(
                    "Only pending proposals can be accepted."
                )

            if appointment.status != AppointmentStatus.CONFIRMED:
                raise AppointmentRescheduleError(
                    "The appointment is no longer confirmed."
                )

            original_doctor = db.get(
                Doctor, appointment.doctor_id
            )

            if original_doctor is None:
                raise AppointmentRescheduleError(
                    "The original doctor was not found."
                )

            doctor = AppointmentRepository.get_doctor_for_update(
                db, proposal.proposed_doctor_id
            )

            if doctor is None:
                raise AppointmentRescheduleError(
                    "The proposed doctor was not found."
                )

            if (
                doctor.id != original_doctor.id
                and doctor.specialization.strip().casefold()
                != original_doctor.specialization.strip().casefold()
            ):
                raise AppointmentRescheduleError(
                    "The proposed doctor does not have the required "
                    "specialization."
                )

            patient = AppointmentRepository.get_patient_for_update(
                db, appointment.patient_id
            )

            if patient is None:
                raise AppointmentRescheduleError(
                    "The appointment's patient was not found."
                )

            # Availability may have changed since the proposal
            # was created, so validate everything again.
            proposed_start_at = proposal.proposed_start_at
            if (
                proposed_start_at.tzinfo is None
                or proposed_start_at.utcoffset() is None
            ):
                proposed_start_at = proposed_start_at.replace(
                    tzinfo=timezone.utc
                )

            end_at = AppointmentService._validate_reschedule_slot(
                db,
                appointment,
                doctor,
                proposed_start_at,
            )

            appointment.doctor_id = doctor.id
            appointment.start_at = proposed_start_at
            appointment.end_at = end_at
            proposal.status = "ACCEPTED"
            for other_proposal in (
                AppointmentRepository.get_pending_proposals_for_appointment(
                    db,
                    appointment.id,
                    exclude_proposal_id=proposal.id,
                )
            ):
                other_proposal.status = "REJECTED"

            # Commit both changes together.
            db.commit()
            db.refresh(appointment)
            db.refresh(proposal)

            return proposal, appointment

        except Exception:
            db.rollback()
            raise

    @staticmethod
    def reject_reschedule(
        db: Session,
        proposal_id: int,
    ) -> RescheduleProposal:
        try:
            proposal = (
                AppointmentRepository.get_proposal_for_update(
                    db, proposal_id
                )
            )

            if proposal is None:
                raise LookupError(
                    f"Reschedule proposal {proposal_id} not found."
                )

            if proposal.status != "PENDING":
                raise AppointmentRescheduleError(
                    "Only pending proposals can be rejected."
                )

            proposal.status = "REJECTED"

            db.commit()
            db.refresh(proposal)
            return proposal

        except Exception:
            db.rollback()
            raise

    @staticmethod
    def get_reschedule_proposal(
        db: Session,
        proposal_id: int,
    ) -> RescheduleProposal:
        proposal = AppointmentRepository.get_proposal_by_id(
            db, proposal_id
        )

        if proposal is None:
            raise LookupError(
                f"Reschedule proposal {proposal_id} not found."
            )

        return proposal
