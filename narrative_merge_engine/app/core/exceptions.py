"""
Custom exception hierarchy + FastAPI exception handlers.
All domain errors bubble up as typed exceptions caught here.
"""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import ORJSONResponse

from app.core.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------

class NarrativeMergeException(Exception):
    """Base exception for all domain errors."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, detail: Any = None) -> None:
        self.message = message
        self.detail = detail
        super().__init__(message)


class NotFoundError(NarrativeMergeException):
    status_code = status.HTTP_404_NOT_FOUND
    error_code = "NOT_FOUND"


class ValidationError(NarrativeMergeException):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = "VALIDATION_ERROR"


class ConflictError(NarrativeMergeException):
    status_code = status.HTTP_409_CONFLICT
    error_code = "CONFLICT"


class AuthenticationError(NarrativeMergeException):
    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "UNAUTHORIZED"


class AuthorizationError(NarrativeMergeException):
    status_code = status.HTTP_403_FORBIDDEN
    error_code = "FORBIDDEN"


class LLMProviderError(NarrativeMergeException):
    """Raised when the upstream LLM call fails after all retries."""
    status_code = status.HTTP_502_BAD_GATEWAY
    error_code = "LLM_PROVIDER_ERROR"


class TimeoutError(NarrativeMergeException):
    status_code = status.HTTP_504_GATEWAY_TIMEOUT
    error_code = "TIMEOUT"


class RateLimitError(NarrativeMergeException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "RATE_LIMITED"


# ---------------------------------------------------------------------------
# Error response builder
# ---------------------------------------------------------------------------

def _error_response(
    status_code: int,
    error_code: str,
    message: str,
    detail: Any = None,
) -> ORJSONResponse:
    body: dict[str, Any] = {
        "error": {
            "code": error_code,
            "message": message,
        }
    }
    if detail is not None:
        body["error"]["detail"] = detail
    return ORJSONResponse(status_code=status_code, content=body)


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

def register_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers on the FastAPI app."""

    @app.exception_handler(NarrativeMergeException)
    async def domain_exception_handler(
        request: Request, exc: NarrativeMergeException
    ) -> ORJSONResponse:
        logger.warning(
            "Domain exception",
            error_code=exc.error_code,
            message=exc.message,
            path=str(request.url),
        )
        return _error_response(exc.status_code, exc.error_code, exc.message, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> ORJSONResponse:
        logger.warning("Request validation failed", errors=exc.errors(), path=str(request.url))
        return _error_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALIDATION_ERROR",
            "Request payload validation failed",
            exc.errors(),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> ORJSONResponse:
        logger.exception("Unhandled exception", exc_info=exc, path=str(request.url))
        return _error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "INTERNAL_ERROR",
            "An unexpected error occurred. Please try again later.",
        )
