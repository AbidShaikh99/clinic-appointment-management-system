from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.repositories.patient_repository import PatientRepository
from app.schemas.patient import PatientCreate


class DuplicatePatientError(Exception):
    def __init__(self, field: str):
        self.field = field
        super().__init__(f"A patient with this {field} is already registered.")


class PatientService:

    @staticmethod
    def register_patient(
        db: Session,
        patient_data: PatientCreate,
    ):
        try:
            # Check phone uniqueness before inserting.
            existing_phone = PatientRepository.get_by_phone(
                db,
                patient_data.phone,
            )

            if existing_phone is not None:
                raise DuplicatePatientError("phone number")

            # Email is optional, so check it only when supplied.
            if patient_data.email is not None:
                existing_email = PatientRepository.get_by_email(
                    db,
                    patient_data.email,
                )

                if existing_email is not None:
                    raise DuplicatePatientError("email")

            patient = PatientRepository.create(
                db,
                patient_data,
            )

            db.commit()
            db.refresh(patient)

            return patient

        except DuplicatePatientError:
            db.rollback()
            raise

        except IntegrityError as exc:
            db.rollback()

            # The database uniqueness constraint also protects
            # against simultaneous registration requests.
            raise DuplicatePatientError(
                "phone number or email"
            ) from exc

        except Exception:
            db.rollback()
            raise
