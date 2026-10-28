from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.doctor_leave import (
    DoctorLeaveCreate,
    DoctorLeaveResponse,
)
from app.services.doctor_leave_service import (
    DoctorInactiveError,
    DoctorLeaveService,
    DoctorNotFoundError,
    OverlappingLeaveError,
)
from app.utils.response import error_response, success_response


router = APIRouter(tags=["Doctor Leave"])


@router.post(
    "/doctors/{doctor_id}/leave",
    status_code=status.HTTP_201_CREATED,
)
def record_doctor_leave(
    doctor_id: int,
    leave_data: DoctorLeaveCreate,
    db: Session = Depends(get_db),
):
    try:
        result = DoctorLeaveService.record_leave(
            db=db,
            doctor_id=doctor_id,
            leave_data=leave_data,
        )

        return success_response(
            message="Doctor leave recorded successfully. Review proposed changes before rescheduling appointments.",
            data={
                "leave": DoctorLeaveResponse.model_validate(
                    result["leave"]
                ),
                "affected_appointments_count": result[
                    "affected_appointments_count"
                ],
                "affected_appointments": result[
                    "affected_appointments"
                ],
            },
            status_code=status.HTTP_201_CREATED,
        )

    except DoctorNotFoundError:
        return error_response(
            message="Doctor not found",
            errors={"doctor_id": doctor_id},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    except DoctorInactiveError as exc:
        return error_response(
            message=str(exc),
            errors={"doctor_id": doctor_id},
            status_code=status.HTTP_409_CONFLICT,
        )

    except OverlappingLeaveError as exc:
        return error_response(
            message=str(exc),
            errors={"start_at": [str(exc)]},
            status_code=status.HTTP_409_CONFLICT,
        )
