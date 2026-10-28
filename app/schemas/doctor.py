from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DoctorCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    specialization: str = Field(min_length=2, max_length=100)
    consultation_duration: int = Field(gt=0, le=240)
    max_daily_appointments: int = Field(gt=0, le=500)

    @field_validator("name", "specialization")
    @classmethod
    def validate_text(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("This field cannot be blank.")

        return value


class DoctorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    specialization: str
    consultation_duration: int
    max_daily_appointments: int
    is_active: bool
    created_at: datetime
