from sqlalchemy.orm import Session

from app.repositories.doctor_repository import DoctorRepository
from app.schemas.doctor import DoctorCreate


class DoctorService:

    @staticmethod
    def create_doctor(
        db: Session,
        doctor_data: DoctorCreate,
    ):
        try:
            doctor = DoctorRepository.create(db, doctor_data)

            db.commit()
            db.refresh(doctor)

            return doctor

        except Exception:
            db.rollback()
            raise

    @staticmethod
    def get_doctor(db: Session, doctor_id: int):
        return DoctorRepository.get_by_id(db, doctor_id)

    @staticmethod
    def get_doctors(db: Session):
        return DoctorRepository.list_all(db)
