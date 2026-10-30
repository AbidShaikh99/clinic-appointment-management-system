from fastapi import APIRouter, Depends, status, Path
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.appointment import (
    AppointmentCreate,
    AppointmentCheckInResponse,
    AppointmentCompletionResponse,
    AppointmentConsultationStartResponse,
    AppointmentDetailResponse,
    AppointmentResponse,
)
from app.schemas.reschedule_proposal import (
    RescheduleRequest,
    RescheduleProposalResponse,
)
from app.services.appointment_service import (
    AppointmentBookingError,
    AppointmentCancellationError,
    AppointmentCheckInError,
    AppointmentLifecycleError,
    AppointmentRescheduleError,
    AppointmentService
    
)
from datetime import date, time
from fastapi import Query
from app.models.enums import AppointmentType
from app.utils.response import error_response, success_response
from app.schemas.available_slots import AvailableSlotsQuery
from app.services.available_slots_service import AvailableSlotsService
from app.schemas.waiting_list import WaitingListResponse


router = APIRouter(
    prefix="/appointments",
    tags=["Appointments"],
)


@router.post("", status_code=status.HTTP_201_CREATED)
def book_appointment(
    appointment_data: AppointmentCreate,
    db: Session = Depends(get_db),
):
    try:
        appointment, alternatives = AppointmentService.book_appointment(
            db,
            appointment_data,
        )

        return success_response(
            message="Appointment booked and confirmed successfully.",
            data={
                "appointment": AppointmentResponse.model_validate(
                    appointment
                ),
                "alternatives": alternatives,
            },
            status_code=status.HTTP_201_CREATED,
        )

    except AppointmentBookingError as exc:
        http_status = (
            status.HTTP_404_NOT_FOUND
            if str(exc) in {
                "Doctor not found.",
                "Patient not found.",
            }
            else status.HTTP_409_CONFLICT
        )

        return error_response(
            message=str(exc),
            errors={
                "alternatives": exc.alternatives,
            },
            status_code=http_status,
        )



@router.get("/available-slots")
def get_available_slots(
    appointment_date: date,
    doctor_id: int | None = Query(default=None, gt=0),
    specialization: str | None = Query(
        default=None,
        min_length=2,
        max_length=100,
    ),
    appointment_type: AppointmentType = AppointmentType.GENERAL,
    preferred_time: time | None = None,
    patient_id: int | None = Query(default=None, gt=0),
    timezone_name: str = "Asia/Kolkata",
    slot_interval_minutes: int = Query(default=15, ge=5, le=60),
    db: Session = Depends(get_db),
):
    try:
        filters = AvailableSlotsQuery(
            appointment_date=appointment_date,
            doctor_id=doctor_id,
            specialization=specialization,
            appointment_type=appointment_type,
            preferred_time=preferred_time,
            patient_id=patient_id,
            timezone_name=timezone_name,
            slot_interval_minutes=slot_interval_minutes,
        )

        result = AvailableSlotsService.search(db, filters)

        return success_response(
            message="Available appointment slots retrieved successfully.",
            data=result,
        )

    except LookupError as exc:
        return error_response(
            message=str(exc),
            errors={"doctor_id": doctor_id},
            status_code=404,
        )

    except ValueError as exc:
        return error_response(
            message=str(exc),
            errors={"filters": [str(exc)]},
            status_code=422,
        )


@router.get("/{appointment_id}")
def get_appointment(
    appointment_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
):
    try:
        appointment = AppointmentService.get_appointment(
            db,
            appointment_id,
        )

        return success_response(
            message="Appointment details retrieved successfully.",
            data=AppointmentDetailResponse.model_validate(appointment),
        )

    except LookupError as exc:
        return error_response(
            message=str(exc),
            status_code=404,
        )

@router.post("/{appointment_id}/cancel")
def cancel_appointment(
    appointment_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
):
    try:
        appointment, newly_cancelled, waiting_list_matching = (
            AppointmentService.cancel_appointment(
                db,
                appointment_id,
            )
        )

        return success_response(
            message="Appointment cancelled successfully.",
            data={
                "appointment_id": appointment.id,
                "booking_reference": appointment.booking_reference,
                "status": appointment.status.value,
                "slot_released": newly_cancelled,
                "waiting_list_matching": {
                    "status": waiting_list_matching["status"],
                    **(
                        {"reason": waiting_list_matching["reason"]}
                        if "reason" in waiting_list_matching
                        else {}
                    ),
                    **(
                        {"error": waiting_list_matching["error"]}
                        if "error" in waiting_list_matching
                        else {}
                    ),
                    "eligible_candidates": [
                        WaitingListResponse.model_validate(
                            candidate
                        ).model_dump(mode="json")
                        for candidate in waiting_list_matching[
                            "eligible_candidates"
                        ]
                    ],
                },
            },
        )

    except LookupError as exc:
        return error_response(
            message=str(exc),
            status_code=404,
        )

    except AppointmentCancellationError as exc:
        return error_response(
            message=str(exc),
            status_code=409,
        )

@router.post(
    "/{appointment_id}/check-in",
    description=(
        "Checks in a confirmed appointment through the configured grace "
        "period (15 minutes by default). After the deadline, check-in is "
        "rejected and the appointment remains confirmed. Queue position "
        "uses stored emergency priority only when explicitly enabled in "
        "settings; otherwise patients are ordered by check-in time. Estimated "
        "wait is the sum of scheduled durations for patients ahead."
    ),
)
def check_in_appointment(
    appointment_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
):
    try:
        result = AppointmentService.check_in_appointment(
            db,
            appointment_id,
        )
        return success_response(
            message="Patient checked in successfully.",
            data=AppointmentCheckInResponse.model_validate(result),
        )

    except LookupError as exc:
        return error_response(
            message=str(exc),
            status_code=status.HTTP_404_NOT_FOUND,
        )

    except AppointmentCheckInError as exc:
        return error_response(
            message=str(exc),
            status_code=status.HTTP_409_CONFLICT,
        )

@router.post("/{appointment_id}/start")
def start_consultation(
    appointment_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
):
    try:
        result = AppointmentService.start_consultation(
            db,
            appointment_id,
        )
        return success_response(
            message="Consultation started successfully.",
            data=AppointmentConsultationStartResponse.model_validate(result),
        )

    except LookupError as exc:
        return error_response(
            message=str(exc),
            status_code=status.HTTP_404_NOT_FOUND,
        )

    except AppointmentLifecycleError as exc:
        return error_response(
            message=str(exc),
            status_code=status.HTTP_409_CONFLICT,
        )


@router.post("/{appointment_id}/complete")
def complete_consultation(
    appointment_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
):
    try:
        result = AppointmentService.complete_consultation(
            db,
            appointment_id,
        )
        return success_response(
            message="Consultation completed and waiting queue updated.",
            data=AppointmentCompletionResponse.model_validate(result),
        )

    except LookupError as exc:
        return error_response(
            message=str(exc),
            status_code=status.HTTP_404_NOT_FOUND,
        )

    except AppointmentLifecycleError as exc:
        return error_response(
            message=str(exc),
            status_code=status.HTTP_409_CONFLICT,
        )

@router.post(
    "/{appointment_id}/no-show",
    description=(
        "Marks a confirmed appointment as NO_SHOW only after the configured "
        "check-in grace period expires. The default grace period is 15 minutes."
    ),
)
def mark_appointment_no_show(
    appointment_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
):
    try:
        result = AppointmentService.mark_no_show(
            db,
            appointment_id,
        )
        return success_response(
            message="Appointment marked as no-show and its reservation released.",
            data=result,
        )

    except LookupError as exc:
        return error_response(
            message=str(exc),
            status_code=status.HTTP_404_NOT_FOUND,
        )

    except AppointmentLifecycleError as exc:
        return error_response(
            message=str(exc),
            status_code=status.HTTP_409_CONFLICT,
        )



@router.post("/{appointment_id}/reschedule")
def request_reschedule(
    request_data: RescheduleRequest,
    appointment_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
):
    try:
        proposal = AppointmentService.request_reschedule(
            db,
            appointment_id,
            request_data,
        )

        return success_response(
            message=(
                "Reschedule proposal created. "
                "The original appointment remains unchanged."
            ),
            data=RescheduleProposalResponse.model_validate(
                proposal
            ),
            status_code=status.HTTP_201_CREATED,
        )

    except LookupError as exc:
        return error_response(
            message=str(exc),
            status_code=status.HTTP_404_NOT_FOUND,
        )

    except AppointmentRescheduleError as exc:
        return error_response(
            message=str(exc),
            status_code=status.HTTP_409_CONFLICT,
        )


@router.get("/reschedule-proposals/{proposal_id}")
def get_reschedule_proposal(
    proposal_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
):
    try:
        proposal = AppointmentService.get_reschedule_proposal(
            db,
            proposal_id,
        )
        return success_response(
            message="Reschedule proposal retrieved successfully.",
            data=RescheduleProposalResponse.model_validate(proposal),
        )
    except LookupError as exc:
        return error_response(
            message=str(exc),
            status_code=status.HTTP_404_NOT_FOUND,
        )


@router.post("/reschedule-proposals/{proposal_id}/accept")
def accept_reschedule_proposal(
    proposal_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
):
    try:
        proposal, appointment = AppointmentService.accept_reschedule(
            db,
            proposal_id,
        )
        return success_response(
            message="Reschedule proposal accepted and appointment updated.",
            data={
                "proposal": RescheduleProposalResponse.model_validate(
                    proposal
                ),
                "appointment": AppointmentResponse.model_validate(
                    appointment
                ),
            },
        )
    except LookupError as exc:
        return error_response(
            message=str(exc),
            status_code=status.HTTP_404_NOT_FOUND,
        )
    except AppointmentRescheduleError as exc:
        return error_response(
            message=str(exc),
            status_code=status.HTTP_409_CONFLICT,
        )


@router.post("/reschedule-proposals/{proposal_id}/reject")
def reject_reschedule_proposal(
    proposal_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
):
    try:
        proposal = AppointmentService.reject_reschedule(
            db,
            proposal_id,
        )
        return success_response(
            message="Reschedule proposal rejected.",
            data=RescheduleProposalResponse.model_validate(proposal),
        )
    except LookupError as exc:
        return error_response(
            message=str(exc),
            status_code=status.HTTP_404_NOT_FOUND,
        )
    except AppointmentRescheduleError as exc:
        return error_response(
            message=str(exc),
            status_code=status.HTTP_409_CONFLICT,
        )
