from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.schedule import (
    DoctorScheduleCreate,
    SchedulePeriodResponse,
)
from app.services.schedule_service import (
    DoctorNotFoundError,
    ScheduleConflictError,
    ScheduleService,
)
from app.utils.response import error_response, success_response


router = APIRouter(tags=["Doctor Schedules"])


@router.post(
    "/doctors/{doctor_id}/schedules",
    status_code=status.HTTP_201_CREATED,
)
def configure_doctor_schedule(
    doctor_id: int,
    schedule_data: DoctorScheduleCreate,
    db: Session = Depends(get_db),
):
    try:
        schedules = ScheduleService.configure_schedule(
            db=db,
            doctor_id=doctor_id,
            schedule_data=schedule_data,
        )

        return success_response(
            message="Doctor schedule configured successfully",
            data=[
                SchedulePeriodResponse.model_validate(schedule)
                for schedule in schedules
            ],
            status_code=status.HTTP_201_CREATED,
        )

    except DoctorNotFoundError:
        return error_response(
            message="Doctor not found",
            errors={"doctor_id": doctor_id},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    except ScheduleConflictError as exc:
        return error_response(
            message="Schedule change would affect confirmed appointments.",
            errors={
                "affected_appointments": exc.affected_appointments,
                "action": (
                    "Existing appointments were preserved. "
                    "Resolve the conflicts before changing the schedule."
                ),
            },
            status_code=status.HTTP_409_CONFLICT,
        )
