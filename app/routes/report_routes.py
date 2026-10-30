from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.enums import AppointmentStatus
from app.repositories.appointment_repository import AppointmentRepository
from app.repositories.doctor_repository import DoctorRepository
from app.schemas.appointment import AppointmentDetailResponse
from app.utils.response import error_response, success_response


router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/appointments")
def get_appointment_report(
    start_date: date,
    end_date: date,
    doctor_id: int | None = Query(default=None, gt=0),
    appointment_status: AppointmentStatus | None = None,
    db: Session = Depends(get_db),
):
    if start_date > end_date:
        return error_response(
            message="start_date must be on or before end_date.",
            errors={"start_date": ["Invalid date range."]},
            status_code=422,
        )

    if (
        doctor_id is not None
        and DoctorRepository.get_by_id(db, doctor_id) is None
    ):
        return error_response(
            message="Doctor not found.",
            errors={"doctor_id": doctor_id},
            status_code=404,
        )

    start_at = datetime.combine(
        start_date,
        time.min,
        tzinfo=timezone.utc,
    )
    end_at = datetime.combine(
        end_date + timedelta(days=1),
        time.min,
        tzinfo=timezone.utc,
    )
    appointments = AppointmentRepository.get_appointments_in_range(
        db,
        start_at,
        end_at,
        doctor_id=doctor_id,
        status=appointment_status,
    )

    status_counts = {status.value: 0 for status in AppointmentStatus}
    for appointment in appointments:
        status_counts[appointment.status.value] += 1

    return success_response(
        message="Appointment report generated successfully.",
        data={
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "timezone": "UTC",
            "doctor_id": doctor_id,
            "status_filter": (
                appointment_status.value
                if appointment_status is not None
                else None
            ),
            "total_appointments": len(appointments),
            "status_counts": status_counts,
            "appointments": [
                AppointmentDetailResponse.model_validate(appointment)
                for appointment in appointments
            ],
        },
    )