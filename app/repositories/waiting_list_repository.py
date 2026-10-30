from datetime import datetime

from sqlalchemy import func, and_, or_, select
from sqlalchemy.orm import Session

from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.waiting_list import WaitingList
from app.models.enums import WaitingListStatus


class WaitingListRepository:

    @staticmethod
    def get_patient(db: Session, patient_id: int):
        statement = (
            select(Patient)
            .where(Patient.id == patient_id)
            .with_for_update()
        )
        return db.scalar(statement)

    @staticmethod
    def get_doctor(db: Session, doctor_id: int):
        statement = (
            select(Doctor)
            .where(Doctor.id == doctor_id)
            .with_for_update()
        )
        return db.scalar(statement)

    @staticmethod
    def specialization_exists(
        db: Session,
        specialization: str,
    ) -> bool:
        statement = select(Doctor.id).where(
            func.lower(Doctor.specialization)
            == specialization.lower(),
            Doctor.is_active.is_(True),
        )

        return db.scalar(statement) is not None

    @staticmethod
    def get_duplicate(
        db: Session,
        patient_id: int,
        doctor_id: int | None,
        specialization: str | None,
        appointment_type,
    ):
        statement = select(WaitingList).where(
            WaitingList.patient_id == patient_id,
            WaitingList.status.in_([
                WaitingListStatus.ACTIVE,
                WaitingListStatus.OFFERED,
            ]),
            WaitingList.appointment_type == appointment_type,
        )

        if doctor_id is not None:
            statement = statement.where(
                WaitingList.doctor_id == doctor_id
            )
        else:
            statement = statement.where(
                func.lower(WaitingList.specialization)
                == specialization.lower()
            )

        return db.scalar(statement)

    @staticmethod
    def create(
        db: Session,
        waiting_entry: WaitingList,
    ):
        db.add(waiting_entry)
        db.flush()
        db.refresh(waiting_entry)
        return waiting_entry


    @staticmethod
    def get_active_matching_entries(
        db,
        doctor_id: int,
        specialization: str,
        appointment_type,
    ):
        statement = (
            select(WaitingList)
            .where(
                WaitingList.status == WaitingListStatus.ACTIVE,
                WaitingList.appointment_type == appointment_type,
                or_(
                    WaitingList.doctor_id == doctor_id,
                    and_(
                        WaitingList.doctor_id.is_(None),
                        func.lower(WaitingList.specialization)
                        == specialization.lower(),
                    ),
                ),
            )
        )

        return list(db.scalars(statement).all())

    @staticmethod
    def get_offer_for_update(db: Session, entry_id: int) -> WaitingList | None:
        statement = (
            select(WaitingList)
            .where(WaitingList.id == entry_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return db.scalar(statement)

    @staticmethod
    def get_active_offer_for_patient(
        db: Session,
        patient_id: int,
        now: datetime,
    ) -> WaitingList | None:
        statement = (
            select(WaitingList)
            .where(
                WaitingList.patient_id == patient_id,
                WaitingList.status == WaitingListStatus.OFFERED,
                WaitingList.offer_expires_at > now,
            )
            .with_for_update()
        )
        return db.scalar(statement)

    @staticmethod
    def get_offer(db: Session, entry_id: int) -> WaitingList | None:
        return db.get(WaitingList, entry_id)

    @staticmethod
    def expire_offers(
        db: Session,
        now: datetime,
        doctor_id: int | None = None,
    ) -> list[WaitingList]:
        statement = (
            select(WaitingList)
            .where(
                WaitingList.status == WaitingListStatus.OFFERED,
                WaitingList.offer_expires_at <= now,
            )
            .with_for_update()
        )
        if doctor_id is not None:
            statement = statement.where(
                WaitingList.offered_doctor_id == doctor_id
            )

        expired = list(db.scalars(statement).all())
        for entry in expired:
            entry.status = WaitingListStatus.ACTIVE
            entry.last_offer_status = "EXPIRED"
            entry.offered_doctor_id = None
            entry.offered_start_at = None
            entry.offered_end_at = None
            entry.offer_expires_at = None
        return expired