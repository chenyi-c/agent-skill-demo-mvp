"""Structured error codes for the Code Navi MVP.

Each error carries a machine-readable code, a user-facing message,
retryability, and an HTTP status — so callers never need to parse
strings to decide what happened.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    """Stable machine-readable error codes."""

    # --- Validation ---
    VALIDATION_ERROR = "VALIDATION_ERROR"

    # --- Skills ---
    SKILL_NOT_FOUND = "SKILL_NOT_FOUND"
    SKILL_DISABLED = "SKILL_DISABLED"

    # --- Sessions ---
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    SESSION_CONFLICT = "SESSION_CONFLICT"

    # --- LLM ---
    LLM_AUTH_FAILED = "LLM_AUTH_FAILED"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_INVALID_RESPONSE = "LLM_INVALID_RESPONSE"

    # --- Academic sources ---
    ACADEMIC_CLI_MISSING = "ACADEMIC_CLI_MISSING"
    ACADEMIC_SOURCE_TIMEOUT = "ACADEMIC_SOURCE_TIMEOUT"
    ACADEMIC_RATE_LIMITED = "ACADEMIC_RATE_LIMITED"
    ACADEMIC_SOURCE_UNAVAILABLE = "ACADEMIC_SOURCE_UNAVAILABLE"
    ACADEMIC_INVALID_RESPONSE = "ACADEMIC_INVALID_RESPONSE"
    ACADEMIC_ALL_SOURCES_FAILED = "ACADEMIC_ALL_SOURCES_FAILED"

    # --- Config ---
    CONFIG_INVALID = "CONFIG_INVALID"
    CONFIG_TEST_FAILED = "CONFIG_TEST_FAILED"

    # --- Generic ---
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppError(Exception):
    """Base exception carrying a structured error code."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        retryable: bool = False,
        http_status: int = 500,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.http_status = http_status
        self.details = details or {}
