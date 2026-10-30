from datetime import date, time

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.enums import AppointmentType
from app.schemas.appointment import AppointmentResponse
from app.schemas.waiting_list import (
    WaitingListCreate,
    WaitingListResponse,
    WaitingListMatchQuery,
    WaitingListOfferResponse,
)
from app.services.waiting_list_service import (
    WaitingListService,
    WaitingListError,
    WaitingListMatchService,
    WaitingListMatchError,
)

from app.utils.response import (
    success_response,
    error_response,
)


router = APIRouter(
    prefix="/waiting-list",
    tags=["Waiting List"],
)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=dict,
)
def add_to_waiting_list(
    request: WaitingListCreate,
    db: Session = Depends(get_db),
):
    try:
        waiting_entry = WaitingListService.add_to_waiting_list(
            db,
            request,
        )

        data = WaitingListResponse.model_validate(
            waiting_entry
        ).model_dump(mode="json")

        return success_response(
            message="Patient added to waiting list successfully.",
            data=data,
            status_code=status.HTTP_201_CREATED,
        )

    except WaitingListError as exc:
        return error_response(
            message=str(exc),
            errors={},
            status_code=status.HTTP_400_BAD_REQUEST,
        )


@router.get(
    "/matches",
    response_model=dict,
    description=(
        "Returns candidates without reserving the slot. Candidates are ranked "
        "by configured priority order, then exact-doctor preference, then "
        "oldest waiting-list entry. Recheck availability when booking."
    ),
)
def get_waiting_list_matches(
    date: date,
    start_time: time,
    appointment_type: AppointmentType,
    doctor_id: int = Query(gt=0),
    available_duration_minutes: int = Query(gt=0, le=240),
    specialization: str | None = Query(
        default=None,
        min_length=2,
        max_length=100,
    ),
    db: Session = Depends(get_db),
):
    try:
        request = WaitingListMatchQuery(
            doctor_id=doctor_id,
            date=date,
            start_time=start_time,
            available_duration_minutes=available_duration_minutes,
            appointment_type=appointment_type,
            specialization=specialization,
        )

        candidates = WaitingListMatchService.match_waiting_patients(
            db=db,
            request=request,
        )

        data = [
            WaitingListResponse.model_validate(candidate).model_dump(
                mode="json"
            )
            for candidate in candidates
        ]

        return success_response(
            message="Waiting-list matches retrieved successfully.",
            data={
                "total_candidates": len(data),
                "candidates": data,
                "slot_reserved": False,
            },
            status_code=status.HTTP_200_OK,
        )

    except WaitingListMatchError as exc:
        return error_response(
            message=str(exc),
            errors={},
            status_code=status.HTTP_400_BAD_REQUEST,
        )


@router.post(
    "/offers",
    status_code=status.HTTP_201_CREATED,
    response_model=dict,
    description=(
        "Atomically reserves an eligible appointment slot as a temporary "
        "offer for the highest-ranked waiting-list patient."
    ),
)
def create_waiting_list_offer(
    request: WaitingListMatchQuery,
    db: Session = Depends(get_db),
):
    try:
        entry = WaitingListMatchService.allocate_offer(db, request)
        return success_response(
            message="Temporary appointment offer created.",
            data=WaitingListOfferResponse(
                entry_id=entry.id,
                patient_id=entry.patient_id,
                appointment_type=entry.appointment_type,
                status=entry.status,
                doctor_id=entry.offered_doctor_id,
                start_at=entry.offered_start_at,
                end_at=entry.offered_end_at,
                expires_at=entry.offer_expires_at,
                last_offer_status=entry.last_offer_status,
            ),
            status_code=status.HTTP_201_CREATED,
        )
    except WaitingListMatchError as exc:
        return error_response(
            message=str(exc),
            errors={},
            status_code=status.HTTP_409_CONFLICT,
        )


@router.post("/offers/{entry_id}/accept")
def accept_waiting_list_offer(
    entry_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
):
    try:
        entry, appointment = WaitingListMatchService.accept_offer(
            db,
            entry_id,
        )
        return success_response(
            message="Waiting-list offer accepted and appointment booked.",
            data={
                "waiting_list_entry": WaitingListResponse.model_validate(
                    entry
                ).model_dump(mode="json"),
                "appointment": AppointmentResponse.model_validate(
                    appointment
                ).model_dump(mode="json"),
            },
            status_code=status.HTTP_201_CREATED,
        )
    except LookupError as exc:
        return error_response(
            message=str(exc),
            status_code=status.HTTP_404_NOT_FOUND,
        )
    except WaitingListMatchError as exc:
        return error_response(
            message=str(exc),
            status_code=status.HTTP_409_CONFLICT,
        )


@router.post("/offers/{entry_id}/decline")
def decline_waiting_list_offer(
    entry_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
):
    try:
        entry = WaitingListMatchService.decline_offer(db, entry_id)
        return success_response(
            message="Waiting-list offer declined.",
            data=WaitingListResponse.model_validate(entry),
        )
    except LookupError as exc:
        return error_response(
            message=str(exc),
            status_code=status.HTTP_404_NOT_FOUND,
        )
    except WaitingListMatchError as exc:
        return error_response(
            message=str(exc),
            status_code=status.HTTP_409_CONFLICT,
        )
