"""Request ID middleware and structured exception handling (Section 11)."""

from __future__ import annotations

import logging
import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.errors import AppError, ErrorCode

logger = logging.getLogger("code_navi")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = rid
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response


def app_error_to_api_error(exc: AppError) -> dict:
    """Convert an AppError to the ApiError shape."""
    return {
        "code": exc.code.value,
        "message": exc.message,
        "retryable": exc.retryable,
        "details": exc.details,
    }


def log_app_error(request_id: str, exc: AppError) -> None:
    logger.warning(
        "app_error",
        extra={
            "request_id": request_id,
            "code": exc.code.value,
            "message": exc.message,
            "retryable": exc.retryable,
        },
    )
