from datetime import time

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SchedulePeriodCreate(BaseModel):
    start_time: time
    end_time: time
    break_start: time | None = None
    break_end: time | None = None

    @model_validator(mode="after")
    def validate_period(self):
        if self.start_time >= self.end_time:
            raise ValueError(
                "Schedule start_time must be earlier than end_time."
            )

        if (self.break_start is None) != (self.break_end is None):
            raise ValueError(
                "Both break_start and break_end must be provided together."
            )

        if self.break_start is not None and self.break_end is not None:
            if self.break_start >= self.break_end:
                raise ValueError(
                    "Break start must be earlier than break end."
                )

            if (
                self.break_start < self.start_time
                or self.break_end > self.end_time
            ):
                raise ValueError(
                    "Break must be inside the working period."
                )

        return self


class DoctorScheduleCreate(BaseModel):
    weekday: int = Field(ge=0, le=6)
    periods: list[SchedulePeriodCreate] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_no_overlapping_periods(self):
        periods = sorted(self.periods, key=lambda p: p.start_time)

        for previous, current in zip(periods, periods[1:]):
            if current.start_time < previous.end_time:
                raise ValueError(
                    "Working periods must not overlap."
                )

        return self


class SchedulePeriodResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doctor_id: int
    weekday: int
    start_time: time
    end_time: time
    break_start: time | None
    break_end: time | None
