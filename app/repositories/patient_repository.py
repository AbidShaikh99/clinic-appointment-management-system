from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.patient import Patient
from app.schemas.patient import PatientCreate


class PatientRepository:

    @staticmethod
    def get_by_phone(
        db: Session,
        phone: str,
    ) -> Patient | None:
        statement = select(Patient).where(
            Patient.phone == phone
        )
        return db.scalars(statement).first()

    @staticmethod
    def get_by_email(
        db: Session,
        email: str,
    ) -> Patient | None:
        statement = select(Patient).where(
            func.lower(Patient.email) == email.lower()
        )
        return db.scalars(statement).first()

    @staticmethod
    def create(
        db: Session,
        patient_data: PatientCreate,
    ) -> Patient:
        patient = Patient(**patient_data.model_dump())

        db.add(patient)
        db.flush()

        return patient

    @staticmethod
    def get_by_id(
        db: Session,
        patient_id: int,
    ) -> Patient | None:
        return db.get(Patient, patient_id)
