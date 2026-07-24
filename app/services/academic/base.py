"""Base protocol and data types for academic source adapters (Section 4.4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from app.models.research import AcademicSource, SourceStatus, SourceStatusKind


# ---------------------------------------------------------------------------
# Request / result
# ---------------------------------------------------------------------------
@dataclass
class SourceSearchRequest:
    query: str
    keywords: list[str] = field(default_factory=list)
    max_results: int = 5
    year_from: int | None = None
    year_to: int | None = None


@dataclass
class SourceSearchResult:
    source: AcademicSource
    status: SourceStatusKind
    papers: list[dict[str, Any]] = field(default_factory=list)
    attempts: int = 0
    latency_ms: float = 0.0
    error_code: str | None = None
    message: str | None = None
    cache_hit: bool = False
    stale_cache: bool = False

    def to_source_status(self) -> SourceStatus:
        return SourceStatus(
            source=self.source,
            status=self.status,
            result_count=len(self.papers),
            attempts=self.attempts,
            latency_ms=self.latency_ms,
            error_code=self.error_code,
            message=self.message,
        )


@dataclass
class SkillContext:
    """Per-invocation context (deadline, semaphore, proxy env, etc.)."""
    request_id: str = ""
    deadline_at: float = 0.0
    proxy_env: dict[str, str] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Adapter protocol
# ---------------------------------------------------------------------------
@runtime_checkable
class AcademicSourceAdapter(Protocol):
    source_name: AcademicSource

    async def search(
        self,
        request: SourceSearchRequest,
        context: SkillContext,
    ) -> SourceSearchResult:
        ...
