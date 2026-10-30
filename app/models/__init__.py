from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.schedule import DoctorSchedule
from app.models.leave import DoctorLeave
from app.models.appointment import Appointment
from app.models.reschedule_proposal import RescheduleProposal
from app.models.waiting_list import WaitingList
__all__ = [
    "Doctor",
    "Patient",
    "DoctorSchedule",
    "DoctorLeave",
    "Appointment",
]
