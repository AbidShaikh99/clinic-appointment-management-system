from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.doctor import Doctor
from app.schemas.doctor import DoctorCreate


class DoctorRepository:

    @staticmethod
    def create(
        db: Session,
        doctor_data: DoctorCreate,
    ) -> Doctor:
        doctor = Doctor(**doctor_data.model_dump())

        db.add(doctor)
        db.flush()

        return doctor

    @staticmethod
    def get_by_id(
        db: Session,
        doctor_id: int,
    ) -> Doctor | None:
        return db.get(Doctor, doctor_id)

    @staticmethod
    def list_all(db: Session) -> list[Doctor]:
        statement = select(Doctor).order_by(Doctor.id.asc())

        return list(db.scalars(statement).all())
