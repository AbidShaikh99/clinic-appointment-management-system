from datetime import date, datetime, time

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    model_validator,
)

from app.models.enums import AppointmentType


class AppointmentCreate(BaseModel):
    patient_id: int = Field(gt=0)
    doctor_id: int = Field(gt=0)
    start_at: datetime
    appointment_type: AppointmentType

    @model_validator(mode="after")
    def validate_appointment_request(self):
        if self.start_at.tzinfo is None or self.start_at.utcoffset() is None:
            raise ValueError(
                "start_at must include a timezone offset."
            )

        return self


class AppointmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    doctor_id: int
    start_at: datetime
    end_at: datetime
    appointment_type: AppointmentType
    priority: str
    status: str
    booking_reference: str
    booked_at: datetime



class PatientReference(BaseModel):
    id: int
    full_name: str
    email: str | None
    phone: str

    model_config = ConfigDict(from_attributes=True)


class DoctorReference(BaseModel):
    id: int
    name: str
    specialization: str

    model_config = ConfigDict(from_attributes=True)


class AppointmentDetailResponse(BaseModel):
    id: int
    patient: PatientReference
    doctor: DoctorReference
    start_at: datetime
    end_at: datetime
    appointment_type: AppointmentType
    priority: str
    status: str
    booked_at: datetime
    checked_in_at: datetime | None = None
    no_show_at: datetime | None = None
    consultation_started_at: datetime | None = None
    consultation_ended_at: datetime | None = None
    consultation_duration_seconds: int | None = None
    booking_reference: str

    model_config = ConfigDict(from_attributes=True)

    @computed_field
    @property
    def appointment_date(self) -> date:
        return self.start_at.date()

    @computed_field
    @property
    def start_time(self) -> time:
        return self.start_at.timetz()

    @computed_field
    @property
    def end_time(self) -> time:
        return self.end_at.timetz()


class AppointmentCheckInResponse(BaseModel):
    appointment_id: int
    status: str
    checked_in_at: datetime
    is_late: bool
    minutes_late: int
    queue_position: int
    estimated_wait_minutes: int


class AppointmentConsultationStartResponse(BaseModel):
    appointment_id: int
    status: str
    consultation_started_at: datetime


class AppointmentQueueEstimate(BaseModel):
    appointment_id: int
    queue_position: int
    estimated_wait_minutes: int


class AppointmentCompletionResponse(BaseModel):
    appointment_id: int
    status: str
    consultation_started_at: datetime
    consultation_ended_at: datetime
    consultation_duration_seconds: int
    queue: list[AppointmentQueueEstimate]