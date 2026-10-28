from datetime import datetime, time, timedelta

from sqlalchemy.orm import Session

from app.models.leave import DoctorLeave
from app.repositories.doctor_leave_repository import DoctorLeaveRepository
from app.schemas.doctor_leave import DoctorLeaveCreate


class DoctorNotFoundError(Exception):
    pass


class DoctorInactiveError(Exception):
    pass


class OverlappingLeaveError(Exception):
    pass


class DoctorLeaveService:

    @staticmethod
    def _find_alternative_slots(
        db: Session,
        leave: DoctorLeave,
        appointment,
        original_doctor,
        max_options: int = 3,
    ) -> list[dict]:
        """
        Find possible slots after the leave and after the original
        appointment, using the same doctor or an active doctor with
        the same specialization.
        """
        duration = appointment.end_at - appointment.start_at

        search_start = max(leave.end_at, appointment.end_at)
        search_end = search_start + timedelta(days=30)

        doctors = DoctorLeaveRepository.get_eligible_doctors(
            db,
            original_doctor.specialization,
        )

        alternatives = []

        for candidate_doctor in doctors:
            day = search_start.date()

            while day <= search_end.date():
                schedules = (
                    DoctorLeaveRepository.get_schedules_for_weekday(
                        db,
                        candidate_doctor.id,
                        day.weekday(),
                    )
                )

                for schedule in schedules:
                    period_start = datetime.combine(
                        day,
                        schedule.start_time,
                        tzinfo=search_start.tzinfo,
                    )
                    period_end = datetime.combine(
                        day,
                        schedule.end_time,
                        tzinfo=search_start.tzinfo,
                    )

                    candidate_start = max(period_start, search_start)

                    while candidate_start + duration <= period_end:
                        candidate_end = candidate_start + duration

                        start_clock = candidate_start.time().replace(
                            tzinfo=None
                        )
                        end_clock = candidate_end.time().replace(
                            tzinfo=None
                        )

                        overlaps_break = (
                            schedule.break_start is not None
                            and schedule.break_end is not None
                            and start_clock < schedule.break_end
                            and end_clock > schedule.break_start
                        )

                        if overlaps_break:
                            candidate_start += timedelta(minutes=15)
                            continue

                        has_leave = (
                            DoctorLeaveRepository.has_overlapping_leave(
                                db,
                                candidate_doctor.id,
                                candidate_start,
                                candidate_end,
                            )
                        )

                        has_conflict = (
                            DoctorLeaveRepository.has_overlapping_appointment(
                                db,
                                candidate_doctor.id,
                                appointment.patient_id,
                                candidate_start,
                                candidate_end,
                                appointment.id,
                            )
                        )

                        if not has_leave and not has_conflict:
                            alternatives.append(
                                {
                                    "proposed_doctor_id": candidate_doctor.id,
                                    "proposed_doctor_name": candidate_doctor.name,
                                    "proposed_start_at": candidate_start,
                                    "proposed_end_at": candidate_end,
                                }
                            )

                            if len(alternatives) >= max_options:
                                return alternatives

                        candidate_start += timedelta(minutes=15)

                day += timedelta(days=1)

        return alternatives

    @staticmethod
    def record_leave(
        db: Session,
        doctor_id: int,
        leave_data: DoctorLeaveCreate,
    ) -> dict:
        try:
            doctor = DoctorLeaveRepository.get_doctor_for_update(
                db,
                doctor_id,
            )

            if doctor is None:
                raise DoctorNotFoundError("Doctor not found.")

            if not doctor.is_active:
                raise DoctorInactiveError(
                    "Leave cannot be recorded for an inactive doctor."
                )

            if DoctorLeaveRepository.has_overlapping_leave(
                db,
                doctor_id,
                leave_data.start_at,
                leave_data.end_at,
            ):
                raise OverlappingLeaveError(
                    "This doctor already has leave during the requested period."
                )

            affected = (
                DoctorLeaveRepository.find_affected_appointments(
                    db,
                    doctor_id,
                    leave_data.start_at,
                    leave_data.end_at,
                )
            )

            leave = DoctorLeaveRepository.create_leave(
                db=db,
                doctor_id=doctor_id,
                start_at=leave_data.start_at,
                end_at=leave_data.end_at,
                reason=leave_data.reason,
            )

            proposed_changes = []

            for appointment in affected:
                alternatives = (
                    DoctorLeaveService._find_alternative_slots(
                        db=db,
                        leave=leave,
                        appointment=appointment,
                        original_doctor=doctor,
                    )
                )

                saved_proposals = []

                for alternative in alternatives:
                    proposal = DoctorLeaveRepository.save_proposal(
                        db=db,
                        leave_id=leave.id,
                        appointment_id=appointment.id,
                        proposed_doctor_id=alternative[
                            "proposed_doctor_id"
                        ],
                        proposed_start_at=alternative[
                            "proposed_start_at"
                        ],
                        proposed_end_at=alternative[
                            "proposed_end_at"
                        ],
                    )

                    saved_proposals.append(
                        {
                            "proposal_id": proposal.id,
                            **alternative,
                            "status": proposal.status,
                        }
                    )

                proposed_changes.append(
                    {
                        "appointment_id": appointment.id,
                        "patient_id": appointment.patient_id,
                        "original_start_at": appointment.start_at,
                        "original_end_at": appointment.end_at,
                        "original_status": appointment.status.value,
                        "proposals": saved_proposals,
                    }
                )

            db.commit()
            db.refresh(leave)

            return {
                "leave": leave,
                "affected_appointments_count": len(affected),
                "affected_appointments": proposed_changes,
            }

        except Exception:
            db.rollback()
            raise
