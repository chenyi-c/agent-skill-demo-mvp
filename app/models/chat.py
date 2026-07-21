from pydantic import BaseModel, Field
from typing import Any, Dict, Optional, List

class ChatRequest(BaseModel):
    message: str = Field(..., description="The user prompt or query.")
    preferred_skill: Optional[str] = Field(None, description="Manually force the use of a specific skill.")

class ChatResponse(BaseModel):
    request_id: str = Field(..., description="Unique transaction ID for this chat request.")
    success: bool = Field(..., description="Whether the skill execution succeeded.")
    reply: str = Field(..., description="The final text reply presented to the user.")
    route_mode: str = Field(..., description="The routing mode used (e.g. LLM, Rule-based, Manual).")
    skill_name: str = Field(..., description="The name of the selected skill.")
    reason: str = Field(..., description="The explanation for selecting this skill.")
    inputs: Dict[str, Any] = Field(..., description="Parameters passed to the skill.")
    outputs: Optional[Dict[str, Any]] = Field(None, description="Raw outputs returned by the skill.")
    duration_ms: float = Field(..., description="Total execution latency in milliseconds.")
    error: Optional[str] = Field(None, description="Error message, if any occurred.")

class SkillInfo(BaseModel):
    name: str
    display_name: str
    description: str
    version: str
    enabled: bool
    parameters_schema: Dict[str, Any]
