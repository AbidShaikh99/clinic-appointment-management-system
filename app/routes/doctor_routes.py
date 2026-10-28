from fastapi import APIRouter, Depends, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.doctor import DoctorCreate, DoctorResponse
from app.services.doctor_service import DoctorService
from app.utils.response import error_response, success_response


router = APIRouter(prefix="/doctors", tags=["Doctors"])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_doctor(
    doctor_data: DoctorCreate,
    db: Session = Depends(get_db),
):
    try:
        doctor = DoctorService.create_doctor(db, doctor_data)

        return success_response(
            message="Doctor registered successfully",
            data=DoctorResponse.model_validate(doctor),
            status_code=status.HTTP_201_CREATED,
        )

    except IntegrityError:
        return error_response(
            message="Doctor registration conflicts with a database constraint.",
            errors={"reason": "DATABASE_CONSTRAINT_CONFLICT"},
            status_code=status.HTTP_409_CONFLICT,
        )


@router.get("/{doctor_id}")
def get_doctor(
    doctor_id: int,
    db: Session = Depends(get_db),
):
    doctor = DoctorService.get_doctor(db, doctor_id)

    if doctor is None:
        return error_response(
            message="Doctor not found",
            errors={"doctor_id": doctor_id},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return success_response(
        message="Doctor retrieved successfully",
        data=DoctorResponse.model_validate(doctor),
    )


@router.get("")
def list_doctors(db: Session = Depends(get_db)):
    doctors = DoctorService.get_doctors(db)

    return success_response(
        message="Doctors retrieved successfully",
        data=[
            DoctorResponse.model_validate(doctor)
            for doctor in doctors
        ],
    )
