"""Unified API request / response schemas for Code Navi MVP.

Every v1 endpoint uses the same envelope shape so clients always know
where to look for data, error details, and metadata.
"""

from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field


T = TypeVar("T")


# ---------------------------------------------------------------------------
# API Error  (Section 7.2)
# ---------------------------------------------------------------------------

class ApiError(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Unified Envelope
# ---------------------------------------------------------------------------

class ApiEnvelope(BaseModel, Generic[T]):
    schema_version: Literal["1.0"] = "1.0"
    request_id: str
    status: Literal["ok", "degraded", "empty", "error"]
    data: T | None = None
    error: ApiError | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Skill metadata returned by /api/v1/skills  (Section 7.5)
# ---------------------------------------------------------------------------

class SkillUiMetadata(BaseModel):
    renderer: str = "default"
    supports_direct_form: bool = False


class SkillMetadata(BaseModel):
    name: str
    version: str
    display_name: str
    description: str
    examples: list[str] = Field(default_factory=list)
    ui: SkillUiMetadata = Field(default_factory=SkillUiMetadata)
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Config  (Section 8.2)
# ---------------------------------------------------------------------------

class ConfigView(BaseModel):
    api_key_configured: bool
    api_key_hint: str | None = None
    base_url: str | None = None
    model: str | None = None


class ConfigPatch(BaseModel):
    api_key_action: Literal["keep", "replace", "clear"] = "keep"
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


# ---------------------------------------------------------------------------
# Research clarification input  (Section 3.7)
# ---------------------------------------------------------------------------

class ResearchClarificationInput(BaseModel):
    message: str = Field(..., min_length=1, description="用户本轮补充的信息或命令")
    session_id: str | None = Field(None, description="已有的科研澄清会话 ID")
    action: Literal["answer", "update", "skip", "confirm", "cancel", "restart"] = "answer"
    target_field: str | None = Field(None, description="update/skip 时指定的字段名")
