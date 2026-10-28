from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.appointment import Appointment
from app.models.doctor import Doctor
from app.models.leave import DoctorLeave
from app.models.enums import AppointmentStatus
from app.models.reschedule_proposal import RescheduleProposal
from app.models.schedule import DoctorSchedule


ACTIVE_APPOINTMENT_STATUSES = [
    AppointmentStatus.REQUESTED,
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.CHECKED_IN,
    AppointmentStatus.IN_PROGRESS,
    AppointmentStatus.RESCHEDULE_PENDING,
]


class DoctorLeaveRepository:

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
    def create_leave(
        db: Session,
        doctor_id: int,
        start_at: datetime,
        end_at: datetime,
        reason: str | None,
    ) -> DoctorLeave:
        leave = DoctorLeave(
            doctor_id=doctor_id,
            start_at=start_at,
            end_at=end_at,
            reason=reason,
        )
        db.add(leave)
        db.flush()
        return leave

    @staticmethod
    def find_affected_appointments(
        db: Session,
        doctor_id: int,
        start_at: datetime,
        end_at: datetime,
    ) -> list[Appointment]:
        statement = (
            select(Appointment)
            .where(
                Appointment.doctor_id == doctor_id,
                Appointment.start_at < end_at,
                Appointment.end_at > start_at,
                Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES),
            )
            .order_by(Appointment.start_at)
        )
        return list(db.scalars(statement).all())

    @staticmethod
    def get_eligible_doctors(
        db: Session,
        specialization: str,
    ) -> list[Doctor]:
        statement = (
            select(Doctor)
            .where(
                Doctor.is_active.is_(True),
                Doctor.specialization == specialization,
            )
            .order_by(Doctor.id)
        )
        return list(db.scalars(statement).all())

    @staticmethod
    def get_schedules_for_weekday(
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
    def has_overlapping_leave(
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
    def has_overlapping_appointment(
        db: Session,
        doctor_id: int,
        patient_id: int,
        start_at: datetime,
        end_at: datetime,
        exclude_appointment_id: int,
    ) -> bool:
        doctor_conflict = select(Appointment.id).where(
            Appointment.doctor_id == doctor_id,
            Appointment.id != exclude_appointment_id,
            Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES),
            Appointment.start_at < end_at,
            Appointment.end_at > start_at,
        )

        patient_conflict = select(Appointment.id).where(
            Appointment.patient_id == patient_id,
            Appointment.id != exclude_appointment_id,
            Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES),
            Appointment.start_at < end_at,
            Appointment.end_at > start_at,
        )

        return (
            db.scalars(doctor_conflict).first() is not None
            or db.scalars(patient_conflict).first() is not None
        )

    @staticmethod
    def save_proposal(
        db: Session,
        leave_id: int,
        appointment_id: int,
        proposed_doctor_id: int,
        proposed_start_at: datetime,
        proposed_end_at: datetime,
    ) -> RescheduleProposal:
        proposal = RescheduleProposal(
            leave_id=leave_id,
            appointment_id=appointment_id,
            proposed_doctor_id=proposed_doctor_id,
            proposed_start_at=proposed_start_at,
            proposed_end_at=proposed_end_at,
            status="PENDING",
        )
        db.add(proposal)
        db.flush()
        return proposal
