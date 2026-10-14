"""Custom exception classes and global exception handlers."""

from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppException(Exception):
    """Base exception for the application."""

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"
    message: str = "An unexpected error occurred"

    def __init__(
        self,
        message: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        self.message = message or self.__class__.message
        self.details = details or {}
        super().__init__(self.message)


class NotFoundError(AppException):
    """Resource not found."""

    status_code = 404
    error_code = "NOT_FOUND"
    message = "Resource not found"


class TicketNotFoundError(NotFoundError):
    """Ticket not found."""

    error_code = "TICKET_NOT_FOUND"
    message = "Ticket not found"

    def __init__(self, ticket_id: str) -> None:
        super().__init__(
            message=f"Ticket with id '{ticket_id}' not found",
            details={"ticket_id": ticket_id},
        )


class TicketAlreadyApprovedError(AppException):
    """Attempt to reject/act on a ticket that is already approved."""

    status_code = 409
    error_code = "TICKET_ALREADY_APPROVED"
    message = "Ticket has already been approved"

    def __init__(self, ticket_id: str) -> None:
        super().__init__(
            message=f"Ticket '{ticket_id}' has already been approved",
            details={"ticket_id": ticket_id},
        )


class ProjectNotFoundError(NotFoundError):
    """Project not found."""

    error_code = "PROJECT_NOT_FOUND"
    message = "Project not found"

    def __init__(self, project_id: str) -> None:
        super().__init__(
            message=f"Project with id '{project_id}' not found",
            details={"project_id": project_id},
        )


class ValidationError(AppException):
    """Input validation failed."""

    status_code = 400
    error_code = "VALIDATION_ERROR"
    message = "Validation failed"


class UnauthorizedError(AppException):
    """Authentication required or failed."""

    status_code = 401
    error_code = "UNAUTHORIZED"
    message = "Authentication required"


class ForbiddenError(AppException):
    """Insufficient permissions."""

    status_code = 403
    error_code = "FORBIDDEN"
    message = "Insufficient permissions"


class ConflictError(AppException):
    """Resource conflict (e.g., duplicate)."""

    status_code = 409
    error_code = "CONFLICT"
    message = "Resource already exists"


class IntegrationError(AppException):
    """External service integration failure."""

    status_code = 502
    error_code = "INTEGRATION_ERROR"
    message = "External service error"


def register_exception_handlers(app: FastAPI) -> None:
    """Register global exception handlers on the FastAPI app."""

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.error_code,
                "message": exc.message,
                "details": exc.details,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # TODO: Log to CloudWatch in production
        print(f"Unhandled exception: {exc}")
        return JSONResponse(
            status_code=500,
            content={
                "error": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
                "details": {},
            },
        )
