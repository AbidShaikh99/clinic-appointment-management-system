from datetime import datetime, time, date

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from app.models.enums import (
    AppointmentType,
    WaitingListPriority,
    WaitingListStatus,
)


class PreferredTimePeriod(BaseModel):
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def validate_time_period(self):
        if self.start_time.tzinfo is not None or self.end_time.tzinfo is not None:
            raise ValueError("Preferred times must use local time without a timezone.")
        if self.start_time >= self.end_time:
            raise ValueError(
                "Start time must be earlier than end time."
            )
        return self


class WaitingListCreate(BaseModel):
    patient_id: int = Field(gt=0)

    doctor_id: int | None = Field(default=None, gt=0)

    specialization: str | None = Field(
        default=None,
        min_length=2,
        max_length=100,
    )

    appointment_type: AppointmentType

    preferred_time_periods: list[PreferredTimePeriod] = Field(
        min_length=1,
    )

    required_duration_minutes: int | None = Field(
        default=None,
        gt=0,
        le=240,
    )

    @model_validator(mode="after")
    def validate_preferences(self):
        if self.specialization is not None:
            self.specialization = self.specialization.strip() or None

        has_doctor = self.doctor_id is not None
        has_specialization = self.specialization is not None

        if has_doctor == has_specialization:
            raise ValueError(
                "Provide either doctor_id or specialization, not both."
            )

        periods = sorted(
            self.preferred_time_periods,
            key=lambda period: period.start_time,
        )
        for previous, current in zip(periods, periods[1:]):
            if current.start_time < previous.end_time:
                raise ValueError("Preferred time periods must not overlap.")

        return self


class WaitingListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    doctor_id: int | None
    specialization: str | None
    appointment_type: AppointmentType
    preferred_time_periods: list[dict]
    required_duration_minutes: int
    priority: WaitingListPriority
    status: WaitingListStatus
    created_at: datetime
    offered_doctor_id: int | None = None
    offered_start_at: datetime | None = None
    offered_end_at: datetime | None = None
    offer_expires_at: datetime | None = None
    last_offer_status: str | None = None


class WaitingListOfferResponse(BaseModel):
    entry_id: int
    patient_id: int
    appointment_type: AppointmentType
    status: WaitingListStatus
    doctor_id: int
    start_at: datetime
    end_at: datetime
    expires_at: datetime
    last_offer_status: str | None = None

class WaitingListMatchQuery(BaseModel):
    doctor_id: int = Field(gt=0)
    date: date
    start_time: time
    available_duration_minutes: int = Field(gt=0, le=240)
    appointment_type: AppointmentType
    specialization: str | None = Field(
        default=None,
        min_length=2,
        max_length=100,
    )

    @model_validator(mode="after")
    def validate_match_query(self):
        if self.start_time.tzinfo is not None:
            raise ValueError(
                "Slot start_time must be local time without a timezone."
            )
        if self.specialization is not None:
            self.specialization = self.specialization.strip() or None
        return self