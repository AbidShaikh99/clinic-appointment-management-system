from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.enums import AppointmentStatus
from app.repositories.appointment_repository import AppointmentRepository
from app.repositories.doctor_repository import DoctorRepository
from app.repositories.schedule_repository import ScheduleRepository
from app.schemas.appointment import AppointmentDetailResponse
from app.utils.response import error_response, success_response


router = APIRouter(tags=["Clinic Queue"])


@router.get("/doctors/{doctor_id}/daily-schedule")
def get_doctor_daily_schedule(
    schedule_date: date,
    doctor_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
):
    doctor = DoctorRepository.get_by_id(db, doctor_id)
    if doctor is None:
        return error_response(
            message="Doctor not found.",
            errors={"doctor_id": doctor_id},
            status_code=404,
        )

    day_start = datetime.combine(
        schedule_date,
        time.min,
        tzinfo=timezone.utc,
    )
    next_day_start = day_start + timedelta(days=1)
    schedules = ScheduleRepository.get_day_schedules(
        db,
        doctor_id,
        schedule_date.weekday(),
    )
    appointments = AppointmentRepository.get_appointments_in_range(
        db,
        day_start,
        next_day_start,
        doctor_id=doctor_id,
    )

    return success_response(
        message="Doctor daily schedule retrieved successfully.",
        data={
            "doctor_id": doctor.id,
            "doctor_name": doctor.name,
            "specialization": doctor.specialization,
            "date": schedule_date.isoformat(),
            "timezone": "UTC",
            "working_periods": [
                {
                    "start_time": period.start_time.isoformat(),
                    "end_time": period.end_time.isoformat(),
                    "break_start": (
                        period.break_start.isoformat()
                        if period.break_start is not None
                        else None
                    ),
                    "break_end": (
                        period.break_end.isoformat()
                        if period.break_end is not None
                        else None
                    ),
                }
                for period in schedules
            ],
            "appointments": [
                AppointmentDetailResponse.model_validate(appointment)
                for appointment in appointments
            ],
        },
    )


@router.get("/doctors/{doctor_id}/queue")
def get_doctor_queue(
    schedule_date: date,
    doctor_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
):
    doctor = DoctorRepository.get_by_id(db, doctor_id)
    if doctor is None:
        return error_response(
            message="Doctor not found.",
            errors={"doctor_id": doctor_id},
            status_code=404,
        )

    day_start = datetime.combine(
        schedule_date,
        time.min,
        tzinfo=timezone.utc,
    )
    next_day_start = day_start + timedelta(days=1)
    appointments = AppointmentRepository.get_appointments_in_range(
        db,
        day_start,
        next_day_start,
        doctor_id=doctor_id,
    )
    active_queue = [
        appointment
        for appointment in appointments
        if appointment.status
        in {
            AppointmentStatus.CHECKED_IN,
            AppointmentStatus.IN_PROGRESS,
        }
    ]

    def queue_key(appointment):
        order_time = (
            appointment.consultation_started_at
            or appointment.checked_in_at
            or appointment.start_at
        )
        if order_time.tzinfo is None or order_time.utcoffset() is None:
            order_time = order_time.replace(tzinfo=timezone.utc)
        else:
            order_time = order_time.astimezone(timezone.utc)
        emergency_rank = (
            0
            if (
                appointment.status == AppointmentStatus.CHECKED_IN
                and settings.CHECK_IN_EMERGENCY_PRIORITY_ENABLED
                and appointment.priority.value == "EMERGENCY"
            )
            else 1
        )
        in_progress_rank = (
            0
            if appointment.status == AppointmentStatus.IN_PROGRESS
            else 1
        )
        return in_progress_rank, emergency_rank, order_time, appointment.id

    active_queue.sort(key=queue_key)
    estimated_wait_minutes = 0
    queue = []
    for position, appointment in enumerate(active_queue, start=1):
        queue.append({
            "appointment_id": appointment.id,
            "patient_id": appointment.patient_id,
            "patient_name": appointment.patient.full_name,
            "status": appointment.status.value,
            "queue_position": position,
            "estimated_wait_minutes": estimated_wait_minutes,
        })
        if appointment.status == AppointmentStatus.IN_PROGRESS:
            if appointment.consultation_started_at is not None:
                started_at = appointment.consultation_started_at
                if started_at.tzinfo is None or started_at.utcoffset() is None:
                    started_at = started_at.replace(tzinfo=timezone.utc)
                elapsed_seconds = max(
                    0,
                    int(
                        (
                            datetime.now(timezone.utc) - started_at
                        ).total_seconds()
                    ),
                )
                scheduled_seconds = max(
                    0,
                    int(
                        (
                            appointment.end_at - appointment.start_at
                        ).total_seconds()
                    ),
                )
                estimated_wait_minutes += max(
                    0,
                    (scheduled_seconds - elapsed_seconds + 59) // 60,
                )
        else:
            scheduled_seconds = max(
                0,
                int(
                    (
                        appointment.end_at - appointment.start_at
                    ).total_seconds()
                ),
            )
            estimated_wait_minutes += (scheduled_seconds + 59) // 60

    return success_response(
        message="Doctor queue retrieved successfully.",
        data={
            "doctor_id": doctor.id,
            "date": schedule_date.isoformat(),
            "timezone": "UTC",
            "queue": queue,
        },
    )