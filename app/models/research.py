"""Research-domain Pydantic models for the Code Navi MVP.

Defines ResearchBrief, ClarificationTurnOutput, SearchPlan, and related
enums / sub-models.  These are the single source of truth consumed by
the research clarification Skill, the agent router, and the API layer.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AcademicSource(str, Enum):
    arxiv = "arxiv"
    semantic = "semantic"
    openalex = "openalex"
    crossref = "crossref"


class PublicationType(str, Enum):
    journal_article = "journal_article"
    conference_paper = "conference_paper"
    preprint = "preprint"
    book_chapter = "book_chapter"
    dissertation = "dissertation"
    report = "report"
    other = "other"


class ResearchSessionStatus(str, Enum):
    collecting = "collecting"
    awaiting_confirmation = "awaiting_confirmation"
    ready = "ready"
    completed = "completed"
    cancelled = "cancelled"
    expired = "expired"


class ActionType(str, Enum):
    answer = "answer"
    update = "update"
    skip = "skip"
    confirm = "confirm"
    cancel = "cancel"
    restart = "restart"


# ---------------------------------------------------------------------------
# Helper types
# ---------------------------------------------------------------------------

class YearRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: int | None = None
    end: int | None = None
    unlimited: bool = False

    @model_validator(mode="after")
    def validate_range(self) -> "YearRange":
        current_year = datetime.now().year + 1
        for value in (self.start, self.end):
            if value is not None and not 1900 <= value <= current_year:
                raise ValueError(f"年份必须在 1900–{current_year} 之间")
        if self.start and self.end and self.start > self.end:
            raise ValueError("起始年份不能晚于结束年份")
        if self.unlimited and (self.start is not None or self.end is not None):
            raise ValueError("不限年份时不能同时设置起止年份")
        return self

    def __str__(self) -> str:
        if self.unlimited:
            return "不限"
        if self.start and self.end:
            return f"{self.start}–{self.end}"
        if self.start:
            return f"{self.start} 至今"
        if self.end:
            return f"–{self.end}"
        return "不限"


class QuestionOption(BaseModel):
    label: str
    value: str
    description: str | None = None


class ClarificationQuestion(BaseModel):
    field: str
    text: str
    reason: str
    options: list[QuestionOption] = Field(default_factory=list)
    allow_free_text: bool = True
    allow_skip: bool = True


class SkillWarning(BaseModel):
    code: str
    message: str
    field: str | None = None


class SearchPlan(BaseModel):
    query: str
    keywords: list[str] = Field(default_factory=list)
    sources: list[AcademicSource] = Field(default_factory=list)
    year_from: int | None = None
    year_to: int | None = None
    publication_types: list[PublicationType] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    total_limit: int = 12


# ---------------------------------------------------------------------------
# Research Brief  (Section 3.2)
# ---------------------------------------------------------------------------

class ResearchBrief(BaseModel):
    """Structured snapshot of a user's research need."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    topic: str | None = None
    objective: str | None = None
    core_question: str | None = None
    research_object: str | None = None
    data_or_materials: str | None = None
    method_preferences: list[str] = Field(default_factory=list)
    time_range: YearRange | None = None
    languages: list[str] = Field(default_factory=list)
    source_preferences: list[AcademicSource] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    expected_output: str | None = None

    def filled_fields(self) -> list[str]:
        """Return names of non-empty / non-default fields."""
        filled: list[str] = []
        for name, value in self:
            if value is None:
                continue
            if isinstance(value, list) and len(value) == 0:
                continue
            if (
                isinstance(value, YearRange)
                and not value.unlimited
                and value.start is None
                and value.end is None
            ):
                continue
            filled.append(name)
        return filled

    def is_minimally_complete(self) -> bool:
        """Check the minimum bar before a user can confirm search (Section 3.3)."""
        if not self.topic:
            return False
        if not self.objective and not self.core_question:
            return False
        if self.time_range is None:
            return False
        if not self.research_object:
            return False
        if not self.source_preferences:
            return False
        # Empty exclusions means "not confirmed"; ["无"] means explicitly none.
        if not self.exclusions:
            return False
        return True


# ---------------------------------------------------------------------------
# Clarification turn output  (Section 3.6)
# ---------------------------------------------------------------------------

class ClarificationTurnOutput(BaseModel):
    session_id: str
    status: ResearchSessionStatus
    brief: ResearchBrief
    filled_fields: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    updated_fields: list[str] = Field(default_factory=list)
    question: ClarificationQuestion | None = None
    search_plan: SearchPlan | None = None
    can_search: bool = False
    warnings: list[SkillWarning] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Paper record  (Section 4.6)
# ---------------------------------------------------------------------------

class PaperRecord(BaseModel):
    """Normalised paper record consumed by the front-end."""

    paper_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    abstract: str | None = None
    year: int | None = None
    published_date: str | None = None
    publication_type: str | None = None
    venue: str | None = None
    doi: str | None = None
    canonical_url: str | None = None
    pdf_url: str | None = None
    citation_count: int | None = None
    source: AcademicSource
    source_id: str | None = None
    is_preprint: bool = False
    retrieved_at: datetime = Field(default_factory=datetime.now)
    raw_metadata: dict[str, Any] | None = None
    # Dedup support
    matched_sources: list[AcademicSource] = Field(default_factory=list)
    possible_duplicate_of: str | None = None


# ---------------------------------------------------------------------------
# Source status  (Section 4.9)
# ---------------------------------------------------------------------------

class SourceStatusKind(str, Enum):
    ok = "ok"
    empty = "empty"
    timeout = "timeout"
    rate_limited = "rate_limited"
    unavailable = "unavailable"
    invalid_response = "invalid_response"
    error = "error"
    cache_hit = "cache_hit"
    stale_cache = "stale_cache"
    circuit_open = "circuit_open"


class SourceStatus(BaseModel):
    source: AcademicSource
    status: SourceStatusKind
    result_count: int = 0
    attempts: int = 0
    latency_ms: float = 0.0
    error_code: str | None = None
    message: str | None = None


class OverallStatus(str, Enum):
    ok = "ok"
    degraded = "degraded"
    empty = "empty"
    error = "error"
