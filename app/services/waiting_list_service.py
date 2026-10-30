from sqlalchemy.orm import Session
from datetime import datetime, time, timedelta, timezone
import secrets

from app.core.config import settings
from app.core.appointment_policy import consultation_duration_minutes
from app.models.doctor import Doctor
from app.models.waiting_list import WaitingList
from app.models.appointment import Appointment
from app.models.enums import AppointmentPriority, AppointmentStatus
from app.models.enums import (
    AppointmentType,
    WaitingListPriority,
    WaitingListStatus,
)
from app.repositories.appointment_repository import AppointmentRepository

from app.repositories.waiting_list_repository import (
    WaitingListRepository,
)
from app.schemas.waiting_list import (
    WaitingListCreate,
    WaitingListMatchQuery,
)
from app.repositories.doctor_repository import DoctorRepository


class WaitingListError(Exception):
    pass

class WaitingListMatchError(Exception):
    pass

class WaitingListService:

    @staticmethod
    def calculate_priority(
        appointment_type: AppointmentType,
    ) -> WaitingListPriority:
        priority = settings.WAITING_LIST_PRIORITY_BY_APPOINTMENT_TYPE.get(
            appointment_type.value,
            WaitingListPriority.NORMAL.value,
        )
        return WaitingListPriority(priority)

    @staticmethod
    def add_to_waiting_list(
        db: Session,
        request: WaitingListCreate,
    ):

        try:
            # 1. Check patient
            patient = WaitingListRepository.get_patient(
                db,
                request.patient_id,
            )

            if not patient:
                raise WaitingListError(
                    "Patient not found."
                )

            doctor = None

            # 2. Validate doctor-based preference
            if request.doctor_id is not None:

                doctor = WaitingListRepository.get_doctor(
                    db,
                    request.doctor_id,
                )

                if not doctor:
                    raise WaitingListError(
                        "Doctor not found."
                    )

                if not doctor.is_active:
                    raise WaitingListError(
                        "Selected doctor is not active."
                    )

            # 3. Validate specialization-based preference
            if request.specialization:

                exists = (
                    WaitingListRepository.specialization_exists(
                        db,
                        request.specialization,
                    )
                )

                if not exists:
                    raise WaitingListError(
                        "No active doctor found for this specialization."
                    )

            # 4. Determine consultation duration
            if request.required_duration_minutes is not None:
                duration = request.required_duration_minutes

            elif doctor is not None:
                duration = consultation_duration_minutes(
                    doctor,
                    request.appointment_type,
                )

            else:
                raise WaitingListError(
                    "required_duration_minutes is required "
                    "for specialization-based waiting-list entries."
                )

            if duration <= 0:
                raise WaitingListError(
                    "Consultation duration must be greater than zero."
                )

            # 5. Check duplicate active entry
            duplicate = WaitingListRepository.get_duplicate(
                db=db,
                patient_id=request.patient_id,
                doctor_id=request.doctor_id,
                specialization=request.specialization,
                appointment_type=request.appointment_type,
            )

            if duplicate:
                raise WaitingListError(
                    "Patient already has an active waiting-list entry "
                    "for this preference."
                )

            # 6. Calculate priority using configured policy
            priority = WaitingListService.calculate_priority(
                request.appointment_type,
            )

            # 7. Convert time objects into JSON-compatible strings
            preferred_periods = [
                {
                    "start_time": period.start_time.isoformat(),
                    "end_time": period.end_time.isoformat(),
                }
                for period in request.preferred_time_periods
            ]

            # 8. Create waiting-list record
            waiting_entry = WaitingList(
                patient_id=request.patient_id,
                doctor_id=request.doctor_id,
                specialization=request.specialization,
                appointment_type=request.appointment_type,
                preferred_time_periods=preferred_periods,
                required_duration_minutes=duration,
                priority=priority,
                status=WaitingListStatus.ACTIVE,
            )

            WaitingListRepository.create(
                db,
                waiting_entry,
            )

            # 9. Commit transaction
            db.commit()
            db.refresh(waiting_entry)

            return waiting_entry

        except WaitingListError:
            db.rollback()
            raise

        except Exception:
            db.rollback()
            raise

class WaitingListMatchService:

    @staticmethod
    def match_waiting_patients(
        db: Session,
        request: WaitingListMatchQuery,
    ) -> list[WaitingList]:
        doctor = DoctorRepository.get_by_id(db, request.doctor_id)

        if not doctor:
            raise WaitingListMatchError("Doctor not found.")

        if not doctor.is_active:
            raise WaitingListMatchError("Doctor is not active.")

        if (
            request.specialization is not None
            and request.specialization.casefold()
            != doctor.specialization.strip().casefold()
        ):
            raise WaitingListMatchError(
                "The requested specialization does not match the selected doctor."
            )

        slot_start = datetime.combine(
            request.date,
            request.start_time,
            tzinfo=timezone.utc,
        )
        slot_end = slot_start + timedelta(
            minutes=request.available_duration_minutes
        )

        if slot_start <= datetime.now(slot_start.tzinfo):
            raise WaitingListMatchError(
                "The available slot must be in the future."
            )

        if slot_end.date() != request.date:
            raise WaitingListMatchError(
                "The available slot must end on the same date."
            )

        schedules = AppointmentRepository.get_schedules(
            db,
            doctor.id,
            slot_start.weekday(),
        )
        slot_start_time = slot_start.timetz().replace(tzinfo=None)
        slot_end_time = slot_end.timetz().replace(tzinfo=None)
        if not any(
            schedule.start_time <= slot_start_time
            and slot_end_time <= schedule.end_time
            and not (
                schedule.break_start is not None
                and schedule.break_end is not None
                and slot_start_time < schedule.break_end
                and slot_end_time > schedule.break_start
            )
            for schedule in schedules
        ):
            raise WaitingListMatchError(
                "The requested slot is outside the doctor's working hours "
                "or overlaps a break."
            )

        if AppointmentRepository.has_leave_conflict(
            db, doctor.id, slot_start, slot_end
        ):
            raise WaitingListMatchError(
                "The doctor is on leave during the requested slot."
            )

        if AppointmentRepository.has_doctor_conflict(
            db, doctor.id, slot_start, slot_end
        ):
            raise WaitingListMatchError(
                "The doctor already has an appointment during the requested slot."
            )

        if (
            AppointmentRepository.count_daily_appointments(
                db,
                doctor.id,
                datetime.combine(
                    request.date,
                    time.min,
                    tzinfo=slot_start.tzinfo,
                ),
                datetime.combine(
                    request.date + timedelta(days=1),
                    time.min,
                    tzinfo=slot_start.tzinfo,
                ),
            )
            >= doctor.max_daily_appointments
        ):
            raise WaitingListMatchError(
                "The doctor has reached the daily appointment capacity."
            )

        entries = WaitingListRepository.get_active_matching_entries(
            db=db,
            doctor_id=doctor.id,
            specialization=doctor.specialization,
            appointment_type=request.appointment_type,
        )

        priority_order = {
            priority: index
            for index, priority in enumerate(
                settings.WAITING_LIST_MATCH_PRIORITY_ORDER
            )
        }

        eligible_candidates = []
        patient_ids = {entry.patient_id for entry in entries}
        patient_conflicts = AppointmentRepository.get_patient_conflicts(
            db,
            patient_ids,
            slot_start,
            slot_end,
        )
        conflicts_by_patient: dict[int, list[tuple[datetime, datetime]]] = {}
        for patient_id, conflict_start, conflict_end in patient_conflicts:
            if conflict_start.tzinfo is None:
                conflict_start = conflict_start.replace(tzinfo=timezone.utc)
            else:
                conflict_start = conflict_start.astimezone(timezone.utc)
            if conflict_end.tzinfo is None:
                conflict_end = conflict_end.replace(tzinfo=timezone.utc)
            else:
                conflict_end = conflict_end.astimezone(timezone.utc)
            conflicts_by_patient.setdefault(patient_id, []).append(
                (conflict_start, conflict_end)
            )

        for entry in entries:
            if (
                entry.required_duration_minutes
                > request.available_duration_minutes
            ):
                continue

            patient_end = slot_start + timedelta(
                minutes=entry.required_duration_minutes
            )
            if any(
                conflict_start < patient_end and conflict_end > slot_start
                for conflict_start, conflict_end in conflicts_by_patient.get(
                    entry.patient_id,
                    [],
                )
            ):
                continue

            preference_matches = any(
                time.fromisoformat(period["start_time"])
                <= slot_start_time
                and patient_end.timetz().replace(tzinfo=None)
                <= time.fromisoformat(period["end_time"])
                for period in entry.preferred_time_periods
            )
            if not preference_matches:
                continue

            preference_rank = (
                0 if entry.doctor_id == doctor.id else 1
            )

            eligible_candidates.append({
                "entry": entry,
                "preference_rank": preference_rank,
                "priority_rank": priority_order.get(
                    entry.priority.value
                    if isinstance(entry.priority, WaitingListPriority)
                    else str(entry.priority),
                    len(priority_order),
                ),
            })

        eligible_candidates.sort(
            key=lambda item: (
                item["priority_rank"],
                item["preference_rank"],
                item["entry"].created_at,
            )
        )

        return [
            item["entry"]
            for item in eligible_candidates
        ]

    @staticmethod
    def allocate_offer(
        db: Session,
        request: WaitingListMatchQuery,
    ) -> WaitingList:
        try:
            doctor = AppointmentRepository.get_doctor_for_update(
                db,
                request.doctor_id,
            )
            if doctor is None:
                raise WaitingListMatchError("Doctor not found.")
            if not doctor.is_active:
                raise WaitingListMatchError("Doctor is not active.")

            now = datetime.now(timezone.utc)
            WaitingListRepository.expire_offers(
                db,
                now,
                doctor_id=request.doctor_id,
            )
            candidates = WaitingListMatchService.match_waiting_patients(
                db,
                request,
            )

            for candidate in candidates:
                entry = WaitingListRepository.get_offer_for_update(
                    db,
                    candidate.id,
                )
                if (
                    entry is None
                    or entry.status != WaitingListStatus.ACTIVE
                ):
                    continue

                patient = AppointmentRepository.get_patient_for_update(
                    db,
                    entry.patient_id,
                )
                if patient is None:
                    continue

                existing_offer = (
                    WaitingListRepository.get_active_offer_for_patient(
                        db,
                        entry.patient_id,
                        now,
                    )
                )
                if existing_offer is not None:
                    continue

                current_candidates = (
                    WaitingListMatchService.match_waiting_patients(
                        db,
                        request,
                    )
                )
                if not any(
                    current.id == entry.id
                    for current in current_candidates
                ):
                    continue

                start_at = datetime.combine(
                    request.date,
                    request.start_time,
                    tzinfo=timezone.utc,
                )
                end_at = start_at + timedelta(
                    minutes=request.available_duration_minutes
                )
                entry.status = WaitingListStatus.OFFERED
                entry.offered_doctor_id = doctor.id
                entry.offered_start_at = start_at
                entry.offered_end_at = end_at
                entry.offer_expires_at = now + timedelta(
                    minutes=settings.WAITING_LIST_OFFER_DURATION_MINUTES
                )
                entry.last_offer_status = "PENDING"
                db.commit()
                db.refresh(entry)
                return entry

            db.commit()
            raise WaitingListMatchError(
                "No eligible waiting-list patient is available for this slot."
            )

        except WaitingListMatchError:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def accept_offer(
        db: Session,
        entry_id: int,
    ) -> tuple[WaitingList, Appointment]:
        try:
            entry_snapshot = WaitingListRepository.get_offer(db, entry_id)
            if entry_snapshot is None:
                raise LookupError(
                    f"Waiting-list entry {entry_id} was not found."
                )
            doctor_id = entry_snapshot.offered_doctor_id
            if doctor_id is None:
                raise WaitingListMatchError(
                    "This entry has no active appointment offer."
                )

            doctor = AppointmentRepository.get_doctor_for_update(
                db,
                doctor_id,
            )
            entry = WaitingListRepository.get_offer_for_update(
                db,
                entry_id,
            )
            if entry is None:
                raise LookupError(
                    f"Waiting-list entry {entry_id} was not found."
                )
            if (
                entry.status != WaitingListStatus.OFFERED
                or entry.offered_start_at is None
                or entry.offered_end_at is None
                or entry.offer_expires_at is None
            ):
                raise WaitingListMatchError(
                    "This entry has no active appointment offer."
                )

            now = datetime.now(timezone.utc)
            if (
                WaitingListMatchService._as_utc(entry.offer_expires_at)
                <= now
            ):
                entry.status = WaitingListStatus.ACTIVE
                entry.last_offer_status = "EXPIRED"
                WaitingListMatchService._clear_offer(entry)
                db.commit()
                raise WaitingListMatchError(
                    "This appointment offer has expired."
                )

            patient = AppointmentRepository.get_patient_for_update(
                db,
                entry.patient_id,
            )
            if patient is None:
                WaitingListMatchService._release_offer(
                    db,
                    entry,
                    "UNAVAILABLE",
                )
                raise WaitingListMatchError("Patient not found.")
            if doctor is None or not doctor.is_active:
                WaitingListMatchService._release_offer(
                    db,
                    entry,
                    "UNAVAILABLE",
                )
                raise WaitingListMatchError(
                    "The offered doctor is no longer available."
                )
            if (
                entry.doctor_id is None
                and (
                    entry.specialization is None
                    or entry.specialization.strip().casefold()
                    != doctor.specialization.strip().casefold()
                )
            ):
                WaitingListMatchService._release_offer(
                    db,
                    entry,
                    "UNAVAILABLE",
                )
                raise WaitingListMatchError(
                    "The offered doctor does not match the patient's specialization."
                )
            if (
                entry.doctor_id is not None
                and entry.doctor_id != doctor.id
            ):
                WaitingListMatchService._release_offer(
                    db,
                    entry,
                    "UNAVAILABLE",
                )
                raise WaitingListMatchError(
                    "The offered doctor does not match the patient's doctor preference."
                )

            start_at = entry.offered_start_at
            end_at = start_at + timedelta(
                minutes=entry.required_duration_minutes
            )
            offered_end_at = entry.offered_end_at
            if end_at > offered_end_at:
                WaitingListMatchService._release_offer(
                    db,
                    entry,
                    "UNAVAILABLE",
                )
                raise WaitingListMatchError(
                    "The consultation duration no longer fits the offered slot."
                )
            start_at_utc = WaitingListMatchService._as_utc(start_at)
            end_at_utc = WaitingListMatchService._as_utc(end_at)

            if (
                start_at_utc <= now
                or not WaitingListMatchService._fits_schedule(
                    db,
                    doctor.id,
                    start_at_utc,
                    end_at_utc,
                )
                or AppointmentRepository.has_leave_conflict(
                    db,
                    doctor.id,
                    start_at_utc,
                    end_at_utc,
                )
            ):
                WaitingListMatchService._release_offer(
                    db,
                    entry,
                    "UNAVAILABLE",
                )
                raise WaitingListMatchError(
                    "The offered slot is no longer available."
                )

            entry.status = WaitingListStatus.ACTIVE
            db.flush()
            if AppointmentRepository.has_doctor_conflict(
                db,
                doctor.id,
                start_at_utc,
                end_at_utc,
            ):
                WaitingListMatchService._release_offer(
                    db,
                    entry,
                    "UNAVAILABLE",
                )
                raise WaitingListMatchError(
                    "The offered doctor is no longer available at that time."
                )
            if AppointmentRepository.has_patient_conflict(
                db,
                patient.id,
                start_at_utc,
                end_at_utc,
            ):
                WaitingListMatchService._release_offer(
                    db,
                    entry,
                    "UNAVAILABLE",
                )
                raise WaitingListMatchError(
                    "The patient now has a conflicting appointment."
                )
            if (
                AppointmentRepository.count_daily_appointments(
                    db,
                    doctor.id,
                    datetime.combine(
                        start_at_utc.date(),
                        time.min,
                        tzinfo=timezone.utc,
                    ),
                    datetime.combine(
                        start_at_utc.date() + timedelta(days=1),
                        time.min,
                        tzinfo=timezone.utc,
                    ),
                )
                >= doctor.max_daily_appointments
            ):
                WaitingListMatchService._release_offer(
                    db,
                    entry,
                    "UNAVAILABLE",
                )
                raise WaitingListMatchError(
                    "The doctor has reached daily appointment capacity."
                )

            entry.status = WaitingListStatus.FULFILLED
            entry.last_offer_status = "ACCEPTED"
            WaitingListMatchService._clear_offer(entry)
            appointment = Appointment(
                patient_id=patient.id,
                doctor_id=doctor.id,
                start_at=start_at_utc,
                end_at=end_at_utc,
                appointment_type=entry.appointment_type,
                priority=(
                    AppointmentPriority.EMERGENCY
                    if entry.appointment_type == AppointmentType.EMERGENCY
                    else AppointmentPriority.NORMAL
                ),
                status=AppointmentStatus.CONFIRMED,
                booking_reference=(
                    f"APT-{start_at_utc:%Y%m%d}-"
                    f"{secrets.token_hex(4).upper()}"
                ),
                booked_at=now,
            )
            AppointmentRepository.create(db, appointment)
            db.commit()
            db.refresh(entry)
            db.refresh(appointment)
            return entry, appointment

        except (LookupError, WaitingListMatchError):
            db.rollback()
            raise
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def decline_offer(
        db: Session,
        entry_id: int,
    ) -> WaitingList:
        try:
            entry_snapshot = WaitingListRepository.get_offer(db, entry_id)
            if entry_snapshot is None:
                raise LookupError(
                    f"Waiting-list entry {entry_id} was not found."
                )
            if entry_snapshot.offered_doctor_id is not None:
                AppointmentRepository.get_doctor_for_update(
                    db,
                    entry_snapshot.offered_doctor_id,
                )
            entry = WaitingListRepository.get_offer_for_update(
                db,
                entry_id,
            )
            if (
                entry is None
                or entry.status != WaitingListStatus.OFFERED
                or entry.offer_expires_at is None
            ):
                raise WaitingListMatchError(
                    "This entry has no active appointment offer."
                )
            if (
                WaitingListMatchService._as_utc(entry.offer_expires_at)
                <= datetime.now(timezone.utc)
            ):
                entry.status = WaitingListStatus.ACTIVE
                entry.last_offer_status = "EXPIRED"
                WaitingListMatchService._clear_offer(entry)
                db.commit()
                raise WaitingListMatchError(
                    "This appointment offer has expired."
                )

            entry.status = WaitingListStatus.ACTIVE
            entry.last_offer_status = "DECLINED"
            WaitingListMatchService._clear_offer(entry)
            db.commit()
            db.refresh(entry)
            return entry

        except (LookupError, WaitingListMatchError):
            db.rollback()
            raise
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _fits_schedule(
        db: Session,
        doctor_id: int,
        start_at: datetime,
        end_at: datetime,
    ) -> bool:
        start_clock = start_at.time().replace(tzinfo=None)
        end_clock = end_at.time().replace(tzinfo=None)
        schedules = AppointmentRepository.get_schedules(
            db,
            doctor_id,
            start_at.weekday(),
        )
        return any(
            schedule.start_time <= start_clock
            and end_clock <= schedule.end_time
            and not (
                schedule.break_start is not None
                and schedule.break_end is not None
                and start_clock < schedule.break_end
                and end_clock > schedule.break_start
            )
            for schedule in schedules
        )

    @staticmethod
    def _clear_offer(entry: WaitingList) -> None:
        entry.offered_doctor_id = None
        entry.offered_start_at = None
        entry.offered_end_at = None
        entry.offer_expires_at = None

    @staticmethod
    def _release_offer(
        db: Session,
        entry: WaitingList,
        reason: str,
    ) -> None:
        entry.status = WaitingListStatus.ACTIVE
        entry.last_offer_status = reason
        WaitingListMatchService._clear_offer(entry)
        db.commit()