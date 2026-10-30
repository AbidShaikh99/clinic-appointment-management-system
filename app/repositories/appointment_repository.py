from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models.appointment import Appointment
from app.models.doctor import Doctor
from app.models.leave import DoctorLeave
from app.models.patient import Patient
from app.models.schedule import DoctorSchedule
from app.models.enums import AppointmentStatus
from app.models.reschedule_proposal import RescheduleProposal
from app.models.waiting_list import WaitingList
from app.models.enums import WaitingListStatus

BLOCKING_STATUSES = [
    AppointmentStatus.REQUESTED,
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.CHECKED_IN,
    AppointmentStatus.IN_PROGRESS,
    AppointmentStatus.RESCHEDULE_PENDING,
]

CAPACITY_STATUSES = [
    AppointmentStatus.REQUESTED,
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.CHECKED_IN,
    AppointmentStatus.IN_PROGRESS,
    AppointmentStatus.COMPLETED,
    AppointmentStatus.NO_SHOW,
    AppointmentStatus.RESCHEDULE_PENDING,
]


class AppointmentRepository:

    @staticmethod
    def get_doctor_for_update(
        db: Session,
        doctor_id: int,
    ) -> Doctor | None:
        statement = (
            select(Doctor)
            .where(Doctor.id == doctor_id)
            .with_for_update()
        )
        return db.scalars(statement).first()

    @staticmethod
    def get_patient_for_update(
        db: Session,
        patient_id: int,
    ) -> Patient | None:
        statement = (
            select(Patient)
            .where(Patient.id == patient_id)
            .with_for_update()
        )
        return db.scalars(statement).first()

    @staticmethod
    def get_schedules(
        db: Session,
        doctor_id: int,
        weekday: int,
    ) -> list[DoctorSchedule]:
        statement = (
            select(DoctorSchedule)
            .where(
                DoctorSchedule.doctor_id == doctor_id,
                DoctorSchedule.weekday == weekday,
            )
            .order_by(DoctorSchedule.start_time)
        )
        return list(db.scalars(statement).all())

    @staticmethod
    def has_leave_conflict(
        db: Session,
        doctor_id: int,
        start_at: datetime,
        end_at: datetime,
    ) -> bool:
        statement = select(DoctorLeave.id).where(
            DoctorLeave.doctor_id == doctor_id,
            DoctorLeave.start_at < end_at,
            DoctorLeave.end_at > start_at,
        )
        return db.scalars(statement).first() is not None

    @staticmethod
    def has_doctor_conflict(
        db: Session,
        doctor_id: int,
        start_at: datetime,
        end_at: datetime,
        exclude_appointment_id: int | None = None,
    ) -> bool:
        statement = select(Appointment.id).where(
            Appointment.doctor_id == doctor_id,
            Appointment.status.in_(BLOCKING_STATUSES),
            Appointment.start_at < end_at,
            Appointment.end_at > start_at,
        )

        if exclude_appointment_id is not None:
            statement = statement.where(
                Appointment.id != exclude_appointment_id
            )

        if db.scalars(statement).first() is not None:
            return True

        now = datetime.now(timezone.utc)
        offer_statement = select(WaitingList.id).where(
            WaitingList.status == WaitingListStatus.OFFERED,
            WaitingList.offered_doctor_id == doctor_id,
            WaitingList.offer_expires_at > now,
            WaitingList.offered_start_at < end_at,
            WaitingList.offered_end_at > start_at,
        )
        return db.scalars(offer_statement).first() is not None

    @staticmethod
    def has_patient_conflict(
        db: Session,
        patient_id: int,
        start_at: datetime,
        end_at: datetime,
        exclude_appointment_id: int | None = None,
    ) -> bool:
        statement = select(Appointment.id).where(
            Appointment.patient_id == patient_id,
            Appointment.status.in_(BLOCKING_STATUSES),
            Appointment.start_at < end_at,
            Appointment.end_at > start_at,
        )

        if exclude_appointment_id is not None:
            statement = statement.where(
                Appointment.id != exclude_appointment_id
            )

        if db.scalars(statement).first() is not None:
            return True

        now = datetime.now(timezone.utc)
        offer_statement = select(WaitingList.id).where(
            WaitingList.status == WaitingListStatus.OFFERED,
            WaitingList.patient_id == patient_id,
            WaitingList.offer_expires_at > now,
            WaitingList.offered_start_at < end_at,
            WaitingList.offered_end_at > start_at,
        )
        return db.scalars(offer_statement).first() is not None

    @staticmethod
    def get_patient_conflicts(
        db: Session,
        patient_ids: set[int],
        start_at: datetime,
        end_at: datetime,
    ) -> list[tuple[int, datetime, datetime]]:
        if not patient_ids:
            return []

        statement = select(
            Appointment.patient_id,
            Appointment.start_at,
            Appointment.end_at,
        ).where(
            Appointment.patient_id.in_(patient_ids),
            Appointment.status.in_(BLOCKING_STATUSES),
            Appointment.start_at < end_at,
            Appointment.end_at > start_at,
        )
        return list(db.execute(statement).all())

    @staticmethod
    def get_queue_for_doctor(
        db: Session,
        doctor_id: int,
        day_start: datetime,
        next_day_start: datetime,
    ) -> list[Appointment]:
        statement = (
            select(Appointment)
            .where(
                Appointment.doctor_id == doctor_id,
                Appointment.status.in_([
                    AppointmentStatus.CHECKED_IN,
                    AppointmentStatus.IN_PROGRESS,
                ]),
                Appointment.start_at >= day_start,
                Appointment.start_at < next_day_start,
            )
            .order_by(
                Appointment.consultation_started_at,
                Appointment.checked_in_at,
                Appointment.id,
            )
        )
        return list(db.scalars(statement).all())

    @staticmethod
    def get_in_progress_for_doctor(
        db: Session,
        doctor_id: int,
    ) -> list[Appointment]:
        statement = select(Appointment).where(
            Appointment.doctor_id == doctor_id,
            Appointment.status == AppointmentStatus.IN_PROGRESS,
        )
        return list(db.scalars(statement).all())

    @staticmethod
    def count_daily_appointments(
        db: Session,
        doctor_id: int,
        day_start: datetime,
        next_day_start: datetime,
        exclude_appointment_id: int | None = None,
    ) -> int:
        statement = select(func.count(Appointment.id)).where(
            Appointment.doctor_id == doctor_id,
            Appointment.status.in_(CAPACITY_STATUSES),
            Appointment.start_at >= day_start,
            Appointment.start_at < next_day_start,
        )

        if exclude_appointment_id is not None:
            statement = statement.where(
                Appointment.id != exclude_appointment_id
            )

        appointment_count = db.scalar(statement) or 0
        now = datetime.now(timezone.utc)
        offers_statement = select(func.count(WaitingList.id)).where(
            WaitingList.status == WaitingListStatus.OFFERED,
            WaitingList.offered_doctor_id == doctor_id,
            WaitingList.offer_expires_at > now,
            WaitingList.offered_start_at >= day_start,
            WaitingList.offered_start_at < next_day_start,
        )
        return appointment_count + (db.scalar(offers_statement) or 0)

    @staticmethod
    def create(
        db: Session,
        appointment: Appointment,
    ) -> Appointment:
        db.add(appointment)
        db.flush()
        return appointment

    @staticmethod
    def get_appointments_for_day(
        db: Session,
        doctor_id: int,
        day_start: datetime,
        next_day_start: datetime,
    ) -> list[Appointment]:
        statement = select(Appointment).where(
            Appointment.doctor_id == doctor_id,
            Appointment.status.in_(BLOCKING_STATUSES),
            Appointment.start_at < next_day_start,
            Appointment.end_at > day_start,
        )
        return list(db.scalars(statement).all())

    @staticmethod
    def get_appointments_in_range(
        db: Session,
        start_at: datetime,
        end_at: datetime,
        doctor_id: int | None = None,
        status: AppointmentStatus | None = None,
    ) -> list[Appointment]:
        statement = (
            select(Appointment)
            .options(
                joinedload(Appointment.patient),
                joinedload(Appointment.doctor),
            )
            .where(
                Appointment.start_at >= start_at,
                Appointment.start_at < end_at,
            )
            .order_by(Appointment.start_at, Appointment.id)
        )
        if doctor_id is not None:
            statement = statement.where(Appointment.doctor_id == doctor_id)
        if status is not None:
            statement = statement.where(Appointment.status == status)
        return list(db.scalars(statement).all())





    @staticmethod
    def get_by_id(db: Session, appointment_id: int):
        return (
            db.query(Appointment)
            .options(
                joinedload(Appointment.patient),
                joinedload(Appointment.doctor),
            )
            .filter(Appointment.id == appointment_id)
            .first()
        )

    
    @staticmethod
    def get_by_id_for_update(
        db: Session,
        appointment_id: int,
    ) -> Appointment | None:
        statement = (
            select(Appointment)
            .where(Appointment.id == appointment_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

        return db.scalars(statement).first()
    
    @staticmethod
    def get_proposal_by_id(
        db: Session,
        proposal_id: int,
    ) -> RescheduleProposal | None:
        statement = select(RescheduleProposal).where(
            RescheduleProposal.id == proposal_id
        )
        return db.scalars(statement).first()

    @staticmethod
    def get_proposal_for_update(
        db: Session,
        proposal_id: int,
    ) -> RescheduleProposal | None:
        statement = (
            select(RescheduleProposal)
            .where(RescheduleProposal.id == proposal_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return db.scalars(statement).first()

    @staticmethod
    def get_pending_proposals_for_appointment(
        db: Session,
        appointment_id: int,
        exclude_proposal_id: int | None = None,
    ) -> list[RescheduleProposal]:
        statement = (
            select(RescheduleProposal)
            .where(
                RescheduleProposal.appointment_id == appointment_id,
                RescheduleProposal.status == "PENDING",
            )
            .order_by(RescheduleProposal.id)
        )

        if exclude_proposal_id is not None:
            statement = statement.where(
                RescheduleProposal.id != exclude_proposal_id
            )

        return list(db.scalars(statement).all())


    @staticmethod
    def create_proposal(
        db: Session,
        proposal: RescheduleProposal,
    ) -> RescheduleProposal:
        db.add(proposal)
        db.flush()
        return proposal