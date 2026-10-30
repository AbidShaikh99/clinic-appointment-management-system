from app.core.config import settings
from app.models.enums import AppointmentType


def consultation_duration_minutes(
    doctor,
    appointment_type: AppointmentType,
) -> int:
    return settings.APPOINTMENT_TYPE_DURATION_MINUTES.get(
        appointment_type.value,
        doctor.consultation_duration,
    )
