from datetime import date, datetime, time, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.config import settings
from app.core.appointment_policy import consultation_duration_minutes
from app.main import app as api
from app.models.appointment import Appointment
from app.models.doctor import Doctor
from app.models.enums import (
    AppointmentPriority,
    AppointmentStatus,
    AppointmentType,
)
from app.models.patient import Patient
from app.models.schedule import DoctorSchedule
from app.models.waiting_list import WaitingList
from app.models.enums import WaitingListPriority, WaitingListStatus
import app.models  # noqa: F401


@pytest.fixture
def api_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        with test_session() as db:
            yield db

    api.dependency_overrides[get_db] = override_get_db
    with test_session() as db:
        doctor = Doctor(
            name="Report Doctor",
            specialization="General",
            consultation_duration=30,
            max_daily_appointments=10,
        )
        patient = Patient(
            full_name="Report Patient",
            phone="55540001",
        )
        db.add_all([doctor, patient])
        db.flush()

        schedule_date = date.today() + timedelta(days=1)
        db.add(
            DoctorSchedule(
                doctor_id=doctor.id,
                weekday=schedule_date.weekday(),
                start_time=time(9),
                end_time=time(12),
                break_start=time(10),
                break_end=time(10, 15),
            )
        )
        start_at = datetime.combine(
            schedule_date,
            time(9),
            tzinfo=timezone.utc,
        )
        db.add(
            Appointment(
                patient_id=patient.id,
                doctor_id=doctor.id,
                start_at=start_at,
                end_at=start_at + timedelta(minutes=30),
                appointment_type=AppointmentType.GENERAL,
                priority=AppointmentPriority.NORMAL,
                status=AppointmentStatus.CONFIRMED,
                booking_reference="REPORT-TEST-1",
            )
        )
        db.commit()
        doctor_id = doctor.id

    with TestClient(api) as client:
        yield client, doctor_id, schedule_date, test_session

    api.dependency_overrides.pop(get_db, None)
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_daily_schedule_returns_periods_and_appointments(api_client):
    client, doctor_id, schedule_date, _ = api_client

    response = client.get(
        f"/api/v1/doctors/{doctor_id}/daily-schedule",
        params={"schedule_date": schedule_date.isoformat()},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["date"] == schedule_date.isoformat()
    assert data["timezone"] == "UTC"
    assert len(data["working_periods"]) == 1
    assert data["working_periods"][0]["break_start"] == "10:00:00"
    assert len(data["appointments"]) == 1
    assert data["appointments"][0]["status"] == "CONFIRMED"


def test_daily_schedule_returns_not_found_for_unknown_doctor(api_client):
    client, _, schedule_date, _ = api_client

    response = client.get(
        "/api/v1/doctors/999999/daily-schedule",
        params={"schedule_date": schedule_date.isoformat()},
    )

    assert response.status_code == 404


def test_appointment_report_filters_by_date_and_doctor(api_client):
    client, doctor_id, schedule_date, _ = api_client

    response = client.get(
        "/api/v1/reports/appointments",
        params={
            "start_date": schedule_date.isoformat(),
            "end_date": schedule_date.isoformat(),
            "doctor_id": doctor_id,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total_appointments"] == 1
    assert data["status_counts"]["CONFIRMED"] == 1
    assert data["appointments"][0]["doctor"]["id"] == doctor_id


def test_appointment_report_rejects_reversed_date_range(api_client):
    client, doctor_id, schedule_date, _ = api_client

    response = client.get(
        "/api/v1/reports/appointments",
        params={
            "start_date": (schedule_date + timedelta(days=1)).isoformat(),
            "end_date": schedule_date.isoformat(),
            "doctor_id": doctor_id,
        },
    )

    assert response.status_code == 422


def test_no_show_requires_expired_grace_and_is_idempotently_rejected(api_client):
    client, _, _, test_session = api_client
    with test_session() as db:
        appointment = db.query(Appointment).one()
        appointment.start_at = datetime.now(timezone.utc) - timedelta(minutes=20)
        appointment.end_at = appointment.start_at + timedelta(minutes=30)
        appointment.status = AppointmentStatus.CONFIRMED
        db.commit()
        appointment_id = appointment.id

    response = client.post(
        f"/api/v1/appointments/{appointment_id}/no-show"
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "NO_SHOW"
    assert response.json()["data"]["slot_released"] is True
    assert response.json()["data"]["no_show_at"]

    duplicate = client.post(
        f"/api/v1/appointments/{appointment_id}/no-show"
    )
    assert duplicate.status_code == 409


def test_no_show_is_rejected_before_grace_expires(api_client):
    client, _, _, test_session = api_client
    with test_session() as db:
        appointment_id = db.query(Appointment).one().id

    response = client.post(
        f"/api/v1/appointments/{appointment_id}/no-show"
    )

    assert response.status_code == 409
    assert "grace period" in response.json()["message"].lower()


def test_doctor_cannot_start_two_consultations_at_once(api_client):
    client, doctor_id, schedule_date, test_session = api_client
    with test_session() as db:
        first = db.query(Appointment).one()
        first.status = AppointmentStatus.CHECKED_IN
        first.checked_in_at = datetime.now(timezone.utc)
        second_patient = Patient(
            full_name="Second Queue Patient",
            phone="55540002",
        )
        db.add(second_patient)
        db.flush()
        second = Appointment(
            patient_id=second_patient.id,
            doctor_id=doctor_id,
            start_at=datetime.combine(
                schedule_date,
                time(9, 30),
                tzinfo=timezone.utc,
            ),
            end_at=datetime.combine(
                schedule_date,
                time(10),
                tzinfo=timezone.utc,
            ),
            appointment_type=AppointmentType.GENERAL,
            priority=AppointmentPriority.NORMAL,
            status=AppointmentStatus.CHECKED_IN,
            booking_reference="REPORT-TEST-2",
            checked_in_at=datetime.now(timezone.utc),
        )
        db.add(second)
        db.commit()
        first_id = first.id
        second_id = second.id

    assert client.post(
        f"/api/v1/appointments/{first_id}/start"
    ).status_code == 200
    response = client.post(
        f"/api/v1/appointments/{second_id}/start"
    )

    assert response.status_code == 409
    assert "already has an in-progress consultation" in (
        response.json()["message"].lower()
    )


def _create_waiting_entry(test_session, doctor_id, patient_id):
    with test_session() as db:
        entry = WaitingList(
            patient_id=patient_id,
            doctor_id=doctor_id,
            appointment_type=AppointmentType.GENERAL,
            preferred_time_periods=[
                {"start_time": "09:00:00", "end_time": "12:00:00"}
            ],
            required_duration_minutes=30,
            priority=WaitingListPriority.NORMAL,
            status=WaitingListStatus.ACTIVE,
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return entry.id


def test_waiting_list_offer_accepts_and_books_atomically(api_client):
    client, doctor_id, schedule_date, test_session = api_client
    with test_session() as db:
        patient_id = db.query(Patient).one().id
    entry_id = _create_waiting_entry(
        test_session,
        doctor_id,
        patient_id,
    )
    request = {
        "doctor_id": doctor_id,
        "date": schedule_date.isoformat(),
        "start_time": "11:00",
        "available_duration_minutes": 30,
        "appointment_type": "GENERAL",
    }

    offer_response = client.post(
        "/api/v1/waiting-list/offers",
        json=request,
    )

    assert offer_response.status_code == 201, offer_response.text
    offer = offer_response.json()["data"]
    assert offer["entry_id"] == entry_id
    assert offer["status"] == "OFFERED"
    assert offer["expires_at"]

    accepted = client.post(
        f"/api/v1/waiting-list/offers/{entry_id}/accept"
    )
    assert accepted.status_code == 201, accepted.text
    data = accepted.json()["data"]
    assert data["waiting_list_entry"]["status"] == "FULFILLED"
    assert data["appointment"]["status"] == "CONFIRMED"
    assert data["appointment"]["start_at"].startswith(schedule_date.isoformat())

    duplicate = client.post(
        f"/api/v1/waiting-list/offers/{entry_id}/accept"
    )
    assert duplicate.status_code == 409


def test_waiting_list_offer_decline_requeues_patient(api_client):
    client, doctor_id, schedule_date, test_session = api_client
    with test_session() as db:
        patient_id = db.query(Patient).one().id
    entry_id = _create_waiting_entry(
        test_session,
        doctor_id,
        patient_id,
    )

    offer = client.post(
        "/api/v1/waiting-list/offers",
        json={
            "doctor_id": doctor_id,
            "date": schedule_date.isoformat(),
            "start_time": "11:00",
            "available_duration_minutes": 30,
            "appointment_type": "GENERAL",
        },
    )
    assert offer.status_code == 201, offer.text

    declined = client.post(
        f"/api/v1/waiting-list/offers/{entry_id}/decline"
    )
    assert declined.status_code == 200, declined.text
    assert declined.json()["data"]["status"] == "ACTIVE"
    assert declined.json()["data"]["last_offer_status"] == "DECLINED"


def test_active_offer_reserves_slot_from_regular_booking(api_client):
    client, doctor_id, schedule_date, test_session = api_client
    with test_session() as db:
        patient = Patient(
            full_name="Offer Booking Patient",
            phone="55540003",
        )
        db.add(patient)
        db.commit()
        patient_id = patient.id
    entry_id = _create_waiting_entry(
        test_session,
        doctor_id,
        patient_id,
    )
    offer = client.post(
        "/api/v1/waiting-list/offers",
        json={
            "doctor_id": doctor_id,
            "date": schedule_date.isoformat(),
            "start_time": "11:00",
            "available_duration_minutes": 30,
            "appointment_type": "GENERAL",
        },
    )
    assert offer.status_code == 201, offer.text

    booking = client.post(
        "/api/v1/appointments",
        json={
            "patient_id": patient_id,
            "doctor_id": doctor_id,
            "start_at": f"{schedule_date.isoformat()}T11:00:00+00:00",
            "appointment_type": "GENERAL",
        },
    )

    assert booking.status_code == 409
    assert "appointment" in booking.json()["message"].lower()
    with test_session() as db:
        assert db.query(Appointment).count() == 1
        assert db.get(WaitingList, entry_id).status == WaitingListStatus.OFFERED


def test_appointment_type_duration_uses_configured_value_then_doctor_default(
    api_client,
    monkeypatch,
):
    _, doctor_id, _, test_session = api_client
    monkeypatch.setattr(
        settings,
        "APPOINTMENT_TYPE_DURATION_MINUTES",
        {"SPECIALIST": 60},
    )
    with test_session() as db:
        doctor = db.get(Doctor, doctor_id)
        assert consultation_duration_minutes(
            doctor,
            AppointmentType.SPECIALIST,
        ) == 60
        assert consultation_duration_minutes(
            doctor,
            AppointmentType.GENERAL,
        ) == 30


def test_expired_offer_returns_to_waiting_list(api_client, monkeypatch):
    client, doctor_id, schedule_date, test_session = api_client
    with test_session() as db:
        patient_id = db.query(Patient).one().id
    entry_id = _create_waiting_entry(
        test_session,
        doctor_id,
        patient_id,
    )
    monkeypatch.setattr(settings, "WAITING_LIST_OFFER_DURATION_MINUTES", -1)

    offer = client.post(
        "/api/v1/waiting-list/offers",
        json={
            "doctor_id": doctor_id,
            "date": schedule_date.isoformat(),
            "start_time": "11:00",
            "available_duration_minutes": 30,
            "appointment_type": "GENERAL",
        },
    )
    assert offer.status_code == 201, offer.text

    accepted = client.post(
        f"/api/v1/waiting-list/offers/{entry_id}/accept"
    )
    assert accepted.status_code == 409
    with test_session() as db:
        entry = db.get(WaitingList, entry_id)
        assert entry.status == WaitingListStatus.ACTIVE
        assert entry.last_offer_status == "EXPIRED"
        assert entry.offer_expires_at is None


def test_offer_acceptance_revalidates_doctor_and_releases_stale_offer(
    api_client,
):
    client, doctor_id, schedule_date, test_session = api_client
    with test_session() as db:
        patient_id = db.query(Patient).one().id
    entry_id = _create_waiting_entry(
        test_session,
        doctor_id,
        patient_id,
    )
    offer = client.post(
        "/api/v1/waiting-list/offers",
        json={
            "doctor_id": doctor_id,
            "date": schedule_date.isoformat(),
            "start_time": "11:00",
            "available_duration_minutes": 30,
            "appointment_type": "GENERAL",
        },
    )
    assert offer.status_code == 201, offer.text

    with test_session() as db:
        doctor = db.get(Doctor, doctor_id)
        doctor.is_active = False
        db.commit()

    accepted = client.post(
        f"/api/v1/waiting-list/offers/{entry_id}/accept"
    )
    assert accepted.status_code == 409
    with test_session() as db:
        entry = db.get(WaitingList, entry_id)
        assert entry.status == WaitingListStatus.ACTIVE
        assert entry.last_offer_status == "UNAVAILABLE"
        assert entry.offered_start_at is None
