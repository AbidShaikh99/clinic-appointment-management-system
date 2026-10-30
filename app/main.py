from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError

from app.core.config import settings
from app.routes import doctor_routes
from app.utils.response import error_response
from app.routes import schedule_routes
from app.routes import doctor_leave_routes
from app.routes import patient_routes
from app.routes import appointment_routes
from app.routes import waiting_list_routes
from app.routes import queue_routes
from app.routes import report_routes

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
):
    errors = {}

    for error in exc.errors():
        location = error.get("loc", ())
        field_name = str(location[-1]) if location else "request"
        message = error.get("msg", "Invalid value")

        errors.setdefault(field_name, []).append(message)

    return error_response(
        message="Validation failed",
        errors=errors,
        status_code=422,
    )


app.include_router(doctor_routes.router, prefix="/api/v1")
app.include_router(schedule_routes.router, prefix="/api/v1")
app.include_router(doctor_leave_routes.router, prefix="/api/v1")
app.include_router(patient_routes.router, prefix="/api/v1")
app.include_router(appointment_routes.router, prefix="/api/v1")
app.include_router(waiting_list_routes.router, prefix="/api/v1")
app.include_router(queue_routes.router, prefix="/api/v1")
app.include_router(report_routes.router, prefix="/api/v1")

@app.get("/health", tags=["Health"])
def health_check():
    return {
        "success": True,
        "message": "Clinic Management API is running",
        "data": {"status": "healthy"},
    }
