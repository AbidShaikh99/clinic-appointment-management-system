from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RescheduleRequest(BaseModel):
    proposed_start_at: datetime
    proposed_doctor_id: int | None = Field(
        default=None,
        gt=0,
    )
    required_specialization: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )

    @model_validator(mode="after")
    def validate_start_at(self):
        if (
            self.proposed_start_at.tzinfo is None
            or self.proposed_start_at.utcoffset() is None
        ):
            raise ValueError(
                "proposed_start_at must include a timezone offset."
            )

        if self.required_specialization is not None:
            self.required_specialization = (
                self.required_specialization.strip()
            )

            if not self.required_specialization:
                raise ValueError(
                    "required_specialization cannot be blank."
                )

        return self


class RescheduleProposalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    leave_id: int | None
    appointment_id: int
    proposed_doctor_id: int
    proposed_start_at: datetime
    proposed_end_at: datetime
    status: str
    created_at: datetime
