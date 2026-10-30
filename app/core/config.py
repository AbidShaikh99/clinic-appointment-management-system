from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "Healthcare Appointment and Clinic Management System"
    APP_ENV: str = "development"

    DATABASE_URL: str

    CHECK_IN_GRACE_PERIOD_MINUTES: int = 15
    CHECK_IN_EMERGENCY_PRIORITY_ENABLED: bool = False
    WAITING_LIST_OFFER_DURATION_MINUTES: int = 15
    APPOINTMENT_TYPE_DURATION_MINUTES: dict[str, int] = {}
    WAITING_LIST_MATCH_PRIORITY_ORDER: list[str] = [
        "URGENT",
        "HIGH",
        "NORMAL",
    ]
    WAITING_LIST_PRIORITY_BY_APPOINTMENT_TYPE: dict[str, str] = {}

    @field_validator("CHECK_IN_GRACE_PERIOD_MINUTES")
    @classmethod
    def validate_check_in_grace_period(cls, minutes: int) -> int:
        if minutes < 0:
            raise ValueError(
                "CHECK_IN_GRACE_PERIOD_MINUTES cannot be negative."
            )
        return minutes

    @field_validator("WAITING_LIST_OFFER_DURATION_MINUTES")
    @classmethod
    def validate_waiting_list_offer_duration(cls, minutes: int) -> int:
        if minutes <= 0 or minutes > 1440:
            raise ValueError(
                "WAITING_LIST_OFFER_DURATION_MINUTES must be between 1 and 1440."
            )
        return minutes

    @field_validator("APPOINTMENT_TYPE_DURATION_MINUTES")
    @classmethod
    def validate_appointment_type_durations(
        cls,
        durations: dict[str, int],
    ) -> dict[str, int]:
        supported_types = {
            "GENERAL",
            "FOLLOW_UP",
            "SPECIALIST",
            "EMERGENCY",
        }
        normalized = {
            appointment_type.strip().upper(): duration
            for appointment_type, duration in durations.items()
        }
        invalid_types = normalized.keys() - supported_types
        if invalid_types:
            raise ValueError(
                "Unsupported appointment types in duration settings: "
                f"{', '.join(sorted(invalid_types))}."
            )
        invalid_durations = {
            appointment_type: duration
            for appointment_type, duration in normalized.items()
            if duration <= 0 or duration > 240
        }
        if invalid_durations:
            raise ValueError(
                "Appointment type durations must be between 1 and 240 minutes."
            )
        return normalized

    @field_validator("WAITING_LIST_MATCH_PRIORITY_ORDER")
    @classmethod
    def validate_waiting_list_match_priority_order(
        cls,
        order: list[str],
    ) -> list[str]:
        normalized_order = [priority.strip().upper() for priority in order]
        supported_priorities = {"NORMAL", "HIGH", "URGENT"}
        if (
            len(normalized_order) != len(supported_priorities)
            or set(normalized_order) != supported_priorities
        ):
            raise ValueError(
                "WAITING_LIST_MATCH_PRIORITY_ORDER must contain each of "
                "NORMAL, HIGH, and URGENT exactly once."
            )
        return normalized_order

    @field_validator("WAITING_LIST_PRIORITY_BY_APPOINTMENT_TYPE")
    @classmethod
    def validate_waiting_list_priority_rules(
        cls,
        rules: dict[str, str],
    ) -> dict[str, str]:
        appointment_types = {
            "GENERAL",
            "FOLLOW_UP",
            "SPECIALIST",
            "EMERGENCY",
        }
        priorities = {"NORMAL", "HIGH", "URGENT"}
        normalized_rules = {
            appointment_type.strip().upper(): priority.strip().upper()
            for appointment_type, priority in rules.items()
        }

        invalid_types = normalized_rules.keys() - appointment_types
        if invalid_types:
            raise ValueError(
                "Waiting-list priority rules contain unsupported "
                f"appointment types: {', '.join(sorted(invalid_types))}."
            )

        invalid_priorities = set(normalized_rules.values()) - priorities
        if invalid_priorities:
            raise ValueError(
                "Waiting-list priority rules contain unsupported "
                f"priorities: {', '.join(sorted(invalid_priorities))}."
            )

        return normalized_rules

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()
