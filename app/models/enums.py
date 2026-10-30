from enum import Enum


class AppointmentType(str, Enum):
    GENERAL = "GENERAL"
    FOLLOW_UP = "FOLLOW_UP"
    SPECIALIST = "SPECIALIST"
    EMERGENCY = "EMERGENCY"


class AppointmentPriority(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    EMERGENCY = "EMERGENCY"


class AppointmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    RESCHEDULE_PENDING = "RESCHEDULE_PENDING"


class WaitingListStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OFFERED = "OFFERED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class WaitingListPriority(str, Enum):
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"