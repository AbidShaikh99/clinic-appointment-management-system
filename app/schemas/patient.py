from datetime import date, datetime
import re

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
)


class PatientCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    phone: str = Field(min_length=7, max_length=16)
    email: EmailStr | None = None
    date_of_birth: date | None = None

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("Full name cannot be blank.")

        if not re.fullmatch(r"[A-Za-z][A-Za-z .'-]*", value):
            raise ValueError(
                "Full name must contain valid name characters."
            )

        return value

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        value = value.strip()

        if not re.fullmatch(r"\+?[0-9]{7,15}", value):
            raise ValueError(
                "Phone must contain 7 to 15 digits and may start with +."
            )

        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr | None):
        if value is None:
            return None

        return str(value).strip().lower()

    @field_validator("date_of_birth")
    @classmethod
    def validate_date_of_birth(cls, value: date | None):
        if value is not None and value >= date.today():
            raise ValueError("Date of birth must be in the past.")

        return value


class PatientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    phone: str
    email: str | None
    date_of_birth: date | None
    created_at: datetime
