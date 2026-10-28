from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.patient import PatientCreate, PatientResponse
from app.services.patient_service import (
    DuplicatePatientError,
    PatientService,
)
from app.utils.response import error_response, success_response


router = APIRouter(
    prefix="/patients",
    tags=["Patients"],
)


@router.post("", status_code=status.HTTP_201_CREATED)
def register_patient(
    patient_data: PatientCreate,
    db: Session = Depends(get_db),
):
    try:
        patient = PatientService.register_patient(
            db,
            patient_data,
        )

        return success_response(
            message="Patient registered successfully.",
            data=PatientResponse.model_validate(patient),
            status_code=status.HTTP_201_CREATED,
        )

    except DuplicatePatientError as exc:
        return error_response(
            message="Patient registration failed because a unique field already exists.",
            errors={exc.field: [str(exc)]},
            status_code=status.HTTP_409_CONFLICT,
        )
