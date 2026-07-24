"""Legacy-compatible routes plus the versioned v1 API."""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from app.core.config import settings
from app.models.api import ConfigPatch
from app.models.chat import ChatRequest, ChatResponse, SkillInfo
from app.services.agent import orchestrator
from app.services.config_store import config_view, update_runtime_config
from app.services.registry import registry
from app.services.session_store import get_session, update_session
from app.services.skills.academic_search import AcademicSearchSkill


router = APIRouter()
static_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static"
)


def _request_id(request: Request | None = None) -> str:
    return getattr(getattr(request, "state", None), "request_id", None) or str(uuid.uuid4())


def _envelope(
    request: Request,
    *,
    status: str,
    data: Any = None,
    error: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "request_id": _request_id(request),
        "status": status,
        "data": data,
        "error": error,
        "meta": meta or {},
    }


def _skill_metadata() -> list[dict[str, Any]]:
    metadata = []
    examples = {
        "research_clarification_skill": [
            "我想研究演化博弈法，但数据来源还不清楚",
            "帮我明确一个 RAG 幻觉研究方向",
        ],
        "academic_search_skill": ["检索近五年关于代码 Agent 评测的论文"],
        "calculator_skill": ["(12.5 * 4) / 5"],
        "summary_skill": ["总结：请在这里粘贴一段长文本"],
        "echo_skill": ["原样返回这段文字"],
    }
    renderers = {
        "research_clarification_skill": "research_brief",
        "academic_search_skill": "paper_list",
    }
    for skill in registry.list_skills():
        metadata.append(
            {
                "name": skill.name,
                "version": skill.version,
                "display_name": skill.display_name,
                "description": skill.description,
                "enabled": skill.enabled,
                "examples": examples.get(skill.name, []),
                "ui": {
                    "renderer": renderers.get(skill.name, "default"),
                    "supports_direct_form": True,
                },
                "input_schema": skill.input_schema.model_json_schema(),
                "output_schema": (
                    skill.output_schema.model_json_schema()
                    if getattr(skill, "output_schema", None)
                    else None
                ),
            }
        )
    return metadata


async def _execute_chat(request: ChatRequest) -> dict[str, Any]:
    return await orchestrator.execute_task(
        user_input=request.message,
        preferred_skill=request.preferred_skill,
        session_id=request.session_id,
        action=request.action,
        target_field=request.target_field,
    )


@router.get("/health")
def legacy_health():
    return {"status": "ok"}


@router.get("/api/skills", response_model=list[SkillInfo])
def legacy_skills():
    result = []
    for skill in registry.list_skills():
        fields_schema = {}
        for name, field in skill.input_schema.model_fields.items():
            fields_schema[name] = {
                "type": str(field.annotation),
                "description": field.description or "",
                "default": (
                    str(field.default) if not field.is_required() else "Required"
                ),
            }
        result.append(
            SkillInfo(
                name=skill.name,
                display_name=skill.display_name,
                description=skill.description,
                version=skill.version,
                enabled=skill.enabled,
                parameters_schema=fields_schema,
            )
        )
    return result


@router.post("/api/chat", response_model=ChatResponse)
async def legacy_chat(body: ChatRequest):
    result = await _execute_chat(body)
    outputs = result.get("outputs")
    return ChatResponse(
        request_id=str(uuid.uuid4()),
        success=result["success"],
        reply=result["reply"],
        route_mode=result["route_mode"],
        skill_name=result["skill_name"],
        reason=result["reason"],
        inputs=result["inputs"],
        outputs=outputs,
        duration_ms=result["duration_ms"],
        error=result["error"],
        session_id=outputs.get("session_id") if isinstance(outputs, dict) else body.session_id,
    )


class LegacyConfigRequest(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None


@router.get("/api/config")
def legacy_get_config():
    view = config_view()
    key = settings.LLM_API_KEY
    masked = None
    if key:
        masked = key[:4] + "****" + key[-4:] if len(key) > 8 else "****"
    return {
        "api_key": masked,
        "api_key_configured": view["api_key_configured"],
        "api_key_hint": view["api_key_hint"],
        "base_url": view["base_url"],
        "model": view["model"],
    }


@router.post("/api/config")
def legacy_update_config(body: LegacyConfigRequest):
    # Compatibility endpoint: keep the historical in-memory semantics.
    # The new front-end uses PATCH /api/v1/config for encrypted persistence.
    if body.api_key is not None and "****" not in body.api_key and "…" not in body.api_key:
        settings.LLM_API_KEY = body.api_key.strip() or None
    if body.base_url is not None:
        from app.services.config_store import validate_base_url

        try:
            settings.LLM_BASE_URL = validate_base_url(body.base_url)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.model is not None:
        settings.LLM_MODEL = body.model.strip()
    return {"status": "success", "message": "兼容配置已应用；请使用 /api/v1/config 持久化。"}


@router.get("/api/v1/health/live")
def live(request: Request):
    return _envelope(request, status="ok", data={"status": "live"})


@router.get("/api/v1/health/ready")
def ready(request: Request):
    cli = shutil.which("paper-search")
    skills = registry.list_skills()
    ready_state = bool(skills)
    return _envelope(
        request,
        status="ok" if ready_state else "error",
        data={
            "status": "ready" if ready_state else "not_ready",
            "skill_count": len(skills),
            "paper_search_cli": cli,
            "academic_search_available": bool(cli),
        },
    )


@router.get("/api/v1/skills")
def v1_skills(request: Request):
    return _envelope(request, status="ok", data=_skill_metadata())


@router.post("/api/v1/chat")
async def v1_chat(request: Request, body: ChatRequest):
    result = await _execute_chat(body)
    outputs = result.get("outputs") or {}
    if not result["success"]:
        code = (
            "ACADEMIC_ALL_SOURCES_FAILED"
            if result["skill_name"] == "academic_search_skill"
            else "SKILL_EXECUTION_FAILED"
        )
        http_status = 503 if code == "ACADEMIC_ALL_SOURCES_FAILED" else 422
        payload = _envelope(
            request,
            status="error",
            data=result,
            error={
                "code": code,
                "message": result.get("error") or result.get("reply"),
                "retryable": code == "ACADEMIC_ALL_SOURCES_FAILED",
                "details": outputs if outputs else None,
            },
        )
        return JSONResponse(payload, status_code=http_status)
    overall = outputs.get("overall_status")
    status = overall if overall in {"degraded", "empty"} else "ok"
    return _envelope(request, status=status, data=result)


@router.post("/api/v1/skills/{skill_name}/execute")
async def execute_skill(
    request: Request, skill_name: str, params: dict[str, Any] = Body(...)
):
    skill = registry.get(skill_name)
    if not skill:
        return JSONResponse(
            _envelope(
                request,
                status="error",
                error={
                    "code": "SKILL_NOT_FOUND",
                    "message": f"Skill '{skill_name}' 不存在。",
                    "retryable": False,
                },
            ),
            status_code=404,
        )
    result = await skill.execute(params)
    payload = _envelope(
        request,
        status="ok" if result.success else "error",
        data=result.model_dump(mode="json"),
        error=(
            None
            if result.success
            else {
                "code": "SKILL_EXECUTION_FAILED",
                "message": str(result.error),
                "retryable": False,
            }
        ),
    )
    if not result.success:
        return JSONResponse(payload, status_code=422)
    return payload


@router.get("/api/v1/research/sessions/{session_id}")
def research_session(request: Request, session_id: str):
    try:
        row = get_session(session_id)
        data = dict(row)
        data["brief"] = json.loads(data.pop("brief_json"))
        return _envelope(request, status="ok", data=data)
    except Exception as exc:
        return JSONResponse(
            _envelope(
                request,
                status="error",
                error={
                    "code": "SESSION_NOT_FOUND",
                    "message": str(exc),
                    "retryable": False,
                },
            ),
            status_code=404,
        )


@router.post("/api/v1/research/sessions/{session_id}/cancel")
def cancel_session(request: Request, session_id: str):
    try:
        row = get_session(session_id)
        updated = update_session(
            session_id,
            status="cancelled",
            current_field=None,
            expected_version=int(row["version"]),
        )
        return _envelope(request, status="ok", data={"session_id": session_id, "status": updated["status"]})
    except Exception as exc:
        return JSONResponse(
            _envelope(
                request,
                status="error",
                error={"code": "SESSION_NOT_FOUND", "message": str(exc), "retryable": False},
            ),
            status_code=404,
        )


@router.get("/api/v1/config")
def v1_get_config(request: Request):
    return _envelope(request, status="ok", data=config_view())


@router.patch("/api/v1/config")
def v1_patch_config(request: Request, body: ConfigPatch):
    try:
        update_runtime_config(
            api_key_action=body.api_key_action,
            api_key=body.api_key,
            base_url=body.base_url,
            model=body.model,
        )
    except ValueError as exc:
        return JSONResponse(
            _envelope(
                request,
                status="error",
                error={"code": "CONFIG_INVALID", "message": str(exc), "retryable": False},
            ),
            status_code=422,
        )
    return _envelope(request, status="ok", data=config_view())


@router.post("/api/v1/config/test-llm")
async def test_llm(request: Request):
    if not settings.LLM_API_KEY:
        return JSONResponse(
            _envelope(
                request,
                status="error",
                error={"code": "CONFIG_TEST_FAILED", "message": "尚未配置 API Key。", "retryable": False},
            ),
            status_code=422,
        )
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{str(settings.LLM_BASE_URL).rstrip('/')}/models",
                headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
            )
        response.raise_for_status()
        return _envelope(
            request,
            status="ok",
            data={"connected": True, "latency_ms": (time.perf_counter() - started) * 1000},
        )
    except Exception as exc:
        return JSONResponse(
            _envelope(
                request,
                status="error",
                error={
                    "code": "CONFIG_TEST_FAILED",
                    "message": f"模型服务连接失败：{type(exc).__name__}",
                    "retryable": True,
                },
            ),
            status_code=502,
        )


@router.post("/api/v1/config/test-academic-sources")
async def test_academic_sources(request: Request):
    result = await AcademicSearchSkill().execute(
        {
            "query": "artificial intelligence",
            "total_limit": 4,
            "per_source_limit": 1,
            "use_cache": False,
        }
    )
    data = result.data or {}
    payload = _envelope(
        request,
        status=data.get("overall_status", "error"),
        data={
            "source_statuses": data.get("source_statuses", []),
            "duration_ms": result.duration_ms,
        },
        error=(
            None
            if result.success
            else {
                "code": "ACADEMIC_ALL_SOURCES_FAILED",
                "message": str(result.error),
                "retryable": True,
            }
        ),
    )
    if not result.success:
        return JSONResponse(payload, status_code=503)
    return payload


@router.get("/")
def read_root():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h2>static/index.html is missing.</h2>", status_code=404)
