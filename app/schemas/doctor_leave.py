from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DoctorLeaveCreate(BaseModel):
    start_at: datetime
    end_at: datetime
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_leave_period(self):
        if self.start_at.tzinfo is None or self.start_at.utcoffset() is None:
            raise ValueError("start_at must include a timezone.")

        if self.end_at.tzinfo is None or self.end_at.utcoffset() is None:
            raise ValueError("end_at must include a timezone.")

        if self.start_at >= self.end_at:
            raise ValueError("start_at must be earlier than end_at.")

        if self.reason is not None:
            self.reason = self.reason.strip() or None

        return self


class DoctorLeaveResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doctor_id: int
    start_at: datetime
    end_at: datetime
    reason: str | None
    created_at: datetime
