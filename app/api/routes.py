import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
import os

from app.models.chat import ChatRequest, ChatResponse, SkillInfo
from app.services.registry import registry
from app.services.agent import orchestrator

# Initialize the route router
router = APIRouter()

@router.get("/health")
def health():
    return {"status": "ok"}

@router.get("/api/skills", response_model=list[SkillInfo])
def get_skills():
    """
    Returns list of all active registered skills and their input schemas.
    """
    skills = registry.list_skills(include_disabled=False)
    results = []
    for skill in skills:
        # Build raw parameter fields schema
        fields_schema = {}
        for name, field in skill.input_schema.model_fields.items():
            fields_schema[name] = {
                "type": str(field.annotation),
                "description": field.description or "",
                "default": str(field.default) if not field.is_required() else "Required"
            }
        
        results.append(SkillInfo(
            name=skill.name,
            display_name=skill.display_name,
            description=skill.description,
            version=skill.version,
            enabled=skill.enabled,
            parameters_schema=fields_schema
        ))
    return results

@router.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Triggers the Agent router to select and execute a skill.
    """
    request_id = str(uuid.uuid4())
    
    # Run the orchestrator
    result = await orchestrator.execute_task(
        user_input=request.message,
        preferred_skill=request.preferred_skill
    )
    
    return ChatResponse(
        request_id=request_id,
        success=result["success"],
        reply=result["reply"],
        route_mode=result["route_mode"],
        skill_name=result["skill_name"],
        reason=result["reason"],
        inputs=result["inputs"],
        outputs=result["outputs"],
        duration_ms=result["duration_ms"],
        error=result["error"]
    )

class ConfigRequest(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None

@router.get("/api/config")
def get_config():
    """
    Returns current configuration (masking API Key for safety).
    """
    from app.core.config import settings
    masked_key = None
    if settings.LLM_API_KEY:
        masked_key = settings.LLM_API_KEY[:4] + "****" + settings.LLM_API_KEY[-4:] if len(settings.LLM_API_KEY) > 8 else "****"
    return {
        "api_key": masked_key,
        "base_url": settings.LLM_BASE_URL,
        "model": settings.LLM_MODEL
    }

@router.post("/api/config")
def update_config(config: ConfigRequest):
    """
    Dynamically updates the global LLM configurations.
    """
    from app.core.config import settings
    if config.api_key is not None:
        settings.LLM_API_KEY = config.api_key.strip() if config.api_key.strip() else None
    if config.base_url is not None:
        settings.LLM_BASE_URL = config.base_url.strip()
    if config.model is not None:
        settings.LLM_MODEL = config.model.strip()
    return {"status": "success", "message": "API 配置更新成功！"}

# Static file serving
static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static")


@router.get("/")
def read_root():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h2>Demo static/index.html is missing. Please create it.</h2>", status_code=404)
