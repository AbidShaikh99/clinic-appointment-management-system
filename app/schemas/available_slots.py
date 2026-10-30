from datetime import date, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import AppointmentType


class AvailableSlotsQuery(BaseModel):
    appointment_date: date
    doctor_id: int | None = Field(default=None, gt=0)
    specialization: str | None = Field(default=None, min_length=2, max_length=100)
    appointment_type: AppointmentType = AppointmentType.GENERAL
    preferred_time: time | None = None
    patient_id: int | None = Field(default=None, gt=0)
    timezone_name: str = "Asia/Kolkata"
    slot_interval_minutes: int = Field(default=15, ge=5, le=60)

    @field_validator("specialization")
    @classmethod
    def normalize_specialization(cls, value: str | None):
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Specialization cannot be blank.")
        return value

    @field_validator("preferred_time")
    @classmethod
    def validate_preferred_time(cls, value: time | None):
        if value is not None and value.tzinfo is not None:
            raise ValueError(
                "preferred_time should be a local time without a timezone."
            )
        return value

    @field_validator("timezone_name")
    @classmethod
    def validate_timezone(cls, value: str):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Unknown timezone name.") from exc
        return value

    @model_validator(mode="after")
    def validate_doctor_or_specialization(self):
        if self.doctor_id is None and self.specialization is None:
            raise ValueError(
                "Provide either doctor_id, specialization, or both."
            )
        return self


class AvailableSlot(BaseModel):
    doctor_id: int
    doctor_name: str
    specialization: str
    start_at: str
    end_at: str
    duration_minutes: int


class AvailableSlotsResponse(BaseModel):
    appointment_date: date
    appointment_type: AppointmentType
    timezone_name: str
    available_slots: list[AvailableSlot]
    nearest_alternatives: list[AvailableSlot]
