"""Timeout, retry and circuit-breaker policies per source (Section 4.8)."""

from __future__ import annotations

import enum
import threading
import time
from dataclasses import dataclass, field

from app.models.research import AcademicSource


class PolicyDecision(str, enum.Enum):
    ALLOW = "allow"
    FAIL_FAST = "fail_fast"
    CIRCUIT_OPEN = "circuit_open"


@dataclass
class Policy:
    timeout_seconds: float = 5.0
    max_attempts: int = 2
    backoff_base: float = 1.0
    jitter: float = 0.3
    retryable_errors: tuple[str, ...] = (
        "connect", "read timeout", "429", "rate_limited",
        "5xx", "timed out", "non_zero_exit",
    )
    circuit_threshold: int = 5
    circuit_cooldown_seconds: float = 60.0

    # — per‑instance, not shared across sources —
    _failure_count: int = field(default=0, init=False, repr=False)
    _last_failure_at: float = field(default=0.0, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def is_retryable(self, error_tag: str) -> bool:
        return any(tag in error_tag.lower() for tag in self.retryable_errors)

    def allow(self, attempt: int) -> PolicyDecision:
        with self._lock:
            if self._failure_count >= self.circuit_threshold:
                if time.monotonic() - self._last_failure_at < self.circuit_cooldown_seconds:
                    return PolicyDecision.CIRCUIT_OPEN
                # Cooldown expired — reset
                self._failure_count = 0
        if attempt > self.max_attempts:
            return PolicyDecision.FAIL_FAST
        return PolicyDecision.ALLOW

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_at = time.monotonic()

    def record_success(self) -> None:
        with self._lock:
            self._failure_count = 0


# Per-source defaults (Section 4.8 table)
SOURCE_POLICIES: dict[AcademicSource, Policy] = {
    AcademicSource.openalex: Policy(
        timeout_seconds=4.0, max_attempts=2, backoff_base=1.0,
        retryable_errors=("connect", "read timeout", "429", "5xx"),
    ),
    AcademicSource.crossref: Policy(
        timeout_seconds=4.0, max_attempts=2, backoff_base=1.0,
        retryable_errors=("connect", "read timeout", "429", "5xx"),
    ),
    AcademicSource.semantic: Policy(
        timeout_seconds=5.0, max_attempts=2, backoff_base=1.5,
        retryable_errors=("connect", "read timeout", "429", "rate_limited", "5xx"),
    ),
    AcademicSource.arxiv: Policy(
        timeout_seconds=6.0, max_attempts=2, backoff_base=1.5,
        retryable_errors=("connect", "read timeout", "5xx"),
    ),
}
