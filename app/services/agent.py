"""Agent routing and bounded Skill orchestration."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Optional

import httpx
from pydantic import ValidationError

from app.core.config import settings
from app.services.query_extractor import extract_query
from app.services.registry import registry
from app.services.skills.base import SkillResult


def _research_action(message: str, explicit: str | None) -> str:
    if explicit in {"answer", "update", "skip", "confirm", "cancel", "restart"}:
        return explicit
    cleaned = message.strip().lower()
    if re.search(r"重新开始|重置|restart", cleaned):
        return "restart"
    if re.search(r"取消(?:会话|研究)?|退出(?:会话|研究)?|cancel", cleaned):
        return "cancel"
    if re.search(r"确认.*(?:检索|搜索)|开始(?:检索|搜索)|就按这个搜", cleaned):
        return "confirm"
    return "answer"


def _format_research(data: dict[str, Any]) -> str:
    status = data.get("status")
    brief = data.get("brief") or {}
    labels = {
        "topic": "主题",
        "objective": "目标",
        "core_question": "核心问题",
        "research_object": "研究对象",
        "data_or_materials": "数据/材料",
        "method_preferences": "方法偏好",
        "time_range": "年份",
        "languages": "语言",
        "source_preferences": "来源",
        "exclusions": "排除项",
        "constraints": "约束",
        "expected_output": "输出",
    }
    if status == "cancelled":
        return "科研需求会话已取消。需要时可以重新开始。"
    if status == "completed":
        return "本轮需求确认和检索已经完成。"

    lines: list[str] = []
    visible: list[str] = []
    for field in data.get("filled_fields", []):
        value = brief.get(field)
        if isinstance(value, dict):
            if value.get("unlimited"):
                value = "不限"
            else:
                value = f"{value.get('start') or ''}–{value.get('end') or ''}".strip("–")
        elif isinstance(value, list):
            value = "、".join(str(v) for v in value)
        if value:
            visible.append(f"{labels.get(field, field)}：{value}")
    if visible:
        lines.append("已确认：" + "；".join(visible) + "。")

    question = data.get("question")
    if question:
        lines.append(f"\n{question.get('text', '')}")
        if question.get("reason"):
            lines.append(f"原因：{question['reason']}")
        for index, option in enumerate(question.get("options", []), 1):
            lines.append(f"{index}. {option.get('label', option.get('value', ''))}")

    if status == "awaiting_confirmation":
        plan = data.get("search_plan") or {}
        lines.append("\n需求已经达到可检索条件，请检查下面的检索计划。")
        lines.append(
            "关键词："
            + "、".join(plan.get("keywords") or [plan.get("query", "")])
            + "\n来源："
            + "、".join(plan.get("sources") or [])
        )
        lines.append("确认无误后点击“确认并开始检索”，也可以继续补充或修改。")
    elif status == "ready":
        lines.append("需求已经确认，准备开始受约束学术检索。")

    for warning in data.get("warnings", []):
        lines.append(f"提示：{warning.get('message', '')}")
    return "\n".join(lines) or "请继续补充科研需求。"


def _format_academic(data: dict[str, Any]) -> str:
    papers = data.get("results") or []
    statuses = data.get("source_statuses") or []
    overall = data.get("overall_status", "error")
    status_text = []
    for item in sorted(statuses, key=lambda value: value.get("source", "")):
        source = item.get("source", "unknown")
        state = item.get("status", "error")
        count = item.get("result_count", 0)
        if state in {"ok", "cache_hit", "stale_cache"}:
            status_text.append(f"{source}: {count} 篇 ({state})")
        elif state == "empty":
            status_text.append(f"{source}: 无结果")
        else:
            status_text.append(f"{source}: {state}")

    if not papers:
        prefix = "所有学术来源均不可用。" if overall == "error" else "没有找到匹配论文。"
        return prefix + ("\n来源状态：" + " | ".join(status_text) if status_text else "")

    lines = [
        f"找到 {len(papers)} 篇去重后的候选论文"
        + ("（部分来源失败）" if overall == "degraded" else "")
        + "。",
        "来源状态：" + " | ".join(status_text),
        "",
    ]
    for index, paper in enumerate(papers, 1):
        title = paper.get("title") or "无标题"
        year = paper.get("year")
        authors = paper.get("authors") or []
        lines.append(f"**{index}. {title}**" + (f" ({year})" if year else ""))
        if authors:
            lines.append("   " + "；".join(authors[:3]) + (" 等" if len(authors) > 3 else ""))
        meta = []
        if paper.get("venue"):
            meta.append(str(paper["venue"]))
        if paper.get("doi"):
            meta.append("DOI: " + str(paper["doi"]))
        if paper.get("is_preprint"):
            meta.append("预印本")
        if meta:
            lines.append("   " + " | ".join(meta))
        lines.append("")
    return "\n".join(lines)


class AgentOrchestrator:
    def _rule_route(
        self, user_input: str
    ) -> tuple[str, dict[str, Any], str]:
        cleaned = user_input.strip()
        compact = re.sub(r"\s+", "", cleaned)

        # Calculator only wins when the complete input is a parseable-looking formula.
        if (
            re.fullmatch(r"[0-9.+\-*/()]+", compact)
            and re.search(r"[+\-*/]", compact)
            and len(re.findall(r"\d+(?:\.\d+)?", compact)) >= 2
        ):
            return "calculator_skill", {"expression": cleaned}, "基于规则：完整输入是数学表达式。"

        if any(word in cleaned.lower() for word in ("summarize", "summary", "总结", "概述", "摘要", "提炼")):
            payload = re.sub(r"^(?:请)?(?:总结|概述|摘要|提炼)\s*[:：]?\s*", "", cleaned)
            return "summary_skill", {"text": payload or cleaned, "max_sentences": 3}, "检测到摘要需求。"

        if any(word in cleaned.lower() for word in ("论文", "文献", "检索", "paper", "literature")):
            query = extract_query(cleaned)
            if query.needs_clarification:
                return (
                    "research_clarification_skill",
                    {"message": cleaned},
                    "检索主题不够明确，先进入需求确认。",
                )
            return (
                "academic_search_skill",
                {"query": query.normalized_query, "keywords": query.keywords},
                "检测到明确的学术文献检索需求。",
            )

        if any(word in cleaned.lower() for word in ("研究", "课题", "科研", "方向", "rag", "agent")):
            return "research_clarification_skill", {"message": cleaned}, "检测到科研需求，需要逐步澄清。"

        return "echo_skill", {"text": cleaned}, "没有高置信度专业意图，使用基础通道。"

    async def _llm_route(
        self, user_input: str
    ) -> tuple[str, dict[str, Any], str] | None:
        if not settings.LLM_API_KEY:
            return None
        skills = [
            {
                "name": skill.name,
                "description": skill.description,
                "schema": skill.input_schema.model_json_schema(),
            }
            for skill in registry.list_skills()
        ]
        system = (
            "选择一个最合适的 Skill，并只返回 JSON："
            '{"skill_name":"...", "arguments":{}, "reason":"简短中文原因"}。'
            "用户需求模糊时优先 research_clarification_skill；不要把整句口语当论文 query。\n"
            + json.dumps(skills, ensure_ascii=False)
        )
        payload = {
            "model": settings.LLM_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_input},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        url = f"{str(settings.LLM_BASE_URL).rstrip('/')}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
                )
                if response.status_code == 400:
                    payload.pop("response_format", None)
                    response = await client.post(
                        url,
                        json=payload,
                        headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
                    )
                response.raise_for_status()
            decision = json.loads(response.json()["choices"][0]["message"]["content"])
            skill = registry.get(decision.get("skill_name"))
            if not skill or not skill.enabled:
                return None
            validated = skill.input_schema.model_validate(decision.get("arguments") or {})
            return skill.name, validated.model_dump(mode="json"), str(decision.get("reason") or "模型路由")
        except Exception:
            return None

    async def execute_task(
        self,
        user_input: str,
        preferred_skill: Optional[str] = None,
        session_id: Optional[str] = None,
        action: Optional[str] = None,
        target_field: Optional[str] = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        cleaned = user_input.strip()

        if session_id and _research_action(cleaned, action) == "confirm" and not preferred_skill:
            return await self._confirm_and_search(session_id, cleaned, started)

        if preferred_skill:
            skill_name = preferred_skill
            route_mode = "manual"
            reason = f"用户手动指定 {preferred_skill}。"
            arguments = self._manual_arguments(
                preferred_skill, cleaned, session_id, action, target_field
            )
        elif (
            session_id
            and not re.fullmatch(r"\d{4}\s*[-–—至到]\s*\d{4}", cleaned)
            and self._rule_route(cleaned)[0] == "calculator_skill"
        ):
            skill_name, arguments, reason = self._rule_route(cleaned)
            route_mode = "rule"
        elif session_id:
            # An active workflow owns normal replies. This prevents dates such as
            # "2021-2026" from being mistaken for a calculator expression.
            skill_name = "research_clarification_skill"
            route_mode = "workflow"
            reason = "继续当前科研需求确认会话。"
            arguments = {
                "message": cleaned,
                "session_id": session_id,
                "action": _research_action(cleaned, action),
                "target_field": target_field,
            }
        else:
            decision = await self._llm_route(cleaned)
            if decision:
                skill_name, arguments, reason = decision
                route_mode = "llm"
            else:
                skill_name, arguments, reason = self._rule_route(cleaned)
                route_mode = "rule_fallback" if settings.LLM_API_KEY else "rule"

        return await self._run(
            skill_name, arguments, route_mode, reason, started
        )

    def _manual_arguments(
        self,
        skill_name: str,
        message: str,
        session_id: str | None,
        action: str | None,
        target_field: str | None,
    ) -> dict[str, Any]:
        if skill_name == "research_clarification_skill":
            return {
                "message": message,
                "session_id": session_id,
                "action": _research_action(message, action),
                "target_field": target_field,
            }
        if skill_name == "academic_search_skill":
            query = extract_query(message)
            return {
                "query": query.normalized_query or message,
                "keywords": query.keywords,
            }
        if skill_name == "calculator_skill":
            return {"expression": message}
        if skill_name == "summary_skill":
            return {"text": message, "max_sentences": 3}
        return {"text": message}

    async def _run(
        self,
        skill_name: str,
        arguments: dict[str, Any],
        route_mode: str,
        reason: str,
        started: float,
    ) -> dict[str, Any]:
        skill = registry.get(skill_name)
        if not skill:
            return self._error_result(
                started,
                skill_name,
                route_mode,
                reason,
                arguments,
                f"未找到或已禁用 Skill '{skill_name}'。",
            )
        if not skill.enabled:
            return self._error_result(
                started, skill_name, route_mode, reason, arguments, "Skill 已禁用。"
            )
        try:
            validated = skill.input_schema.model_validate(arguments)
            clean_arguments = validated.model_dump(mode="json")
        except ValidationError as exc:
            return self._error_result(
                started, skill_name, route_mode, reason, arguments, f"参数校验失败: {exc}"
            )
        try:
            result: SkillResult = await skill.execute(clean_arguments)
        except Exception as exc:
            return self._error_result(
                started, skill_name, route_mode, reason, clean_arguments, f"Skill 执行失败: {exc}"
            )
        reply = self._format_result(skill_name, result)
        return {
            "success": result.success,
            "reply": reply,
            "route_mode": route_mode,
            "skill_name": skill_name,
            "reason": reason,
            "inputs": clean_arguments,
            "outputs": result.data,
            "duration_ms": (time.perf_counter() - started) * 1000,
            "error": result.error,
        }

    async def _confirm_and_search(
        self, session_id: str, message: str, started: float
    ) -> dict[str, Any]:
        confirmation = await self._run(
            "research_clarification_skill",
            {"message": message, "session_id": session_id, "action": "confirm"},
            "workflow",
            "用户确认研究简报并开始受约束检索。",
            started,
        )
        outputs = confirmation.get("outputs") or {}
        if not confirmation["success"] or outputs.get("status") != "ready":
            return confirmation

        plan = outputs["search_plan"]
        search_arguments = {
            "query": plan["query"],
            "keywords": plan.get("keywords", []),
            "sources": plan.get("sources", []),
            "year_from": plan.get("year_from"),
            "year_to": plan.get("year_to"),
            "total_limit": plan.get("total_limit", 12),
        }
        result = await self._run(
            "academic_search_skill",
            search_arguments,
            "workflow",
            "研究简报已确认，执行来源白名单检索。",
            started,
        )
        if result["success"]:
            from app.services.skills.research_clarification import mark_session_completed

            mark_session_completed(session_id)
            result_outputs = result.get("outputs") or {}
            result_outputs.update(
                {
                    "session_id": session_id,
                    "status": "completed",
                    "research_brief": outputs.get("brief"),
                    "search_plan": plan,
                }
            )
            result["outputs"] = result_outputs
        else:
            result["error"] = result.get("error") or "检索失败，可保留当前会话后重试。"
        return result

    @staticmethod
    def _format_result(skill_name: str, result: SkillResult) -> str:
        if skill_name == "academic_search_skill" and result.data:
            return _format_academic(result.data)
        if not result.success:
            return f"执行失败：{result.error}"
        data = result.data or {}
        if skill_name == "research_clarification_skill":
            return _format_research(data)
        if skill_name == "calculator_skill":
            return f"计算结果：{data.get('formatted')}"
        if skill_name == "summary_skill":
            return f"摘要：\n{data.get('summary')}"
        return str(data.get("reply", data))

    @staticmethod
    def _error_result(
        started: float,
        skill_name: str,
        route_mode: str,
        reason: str,
        inputs: dict[str, Any],
        error: str,
    ) -> dict[str, Any]:
        return {
            "success": False,
            "reply": error,
            "route_mode": route_mode,
            "skill_name": skill_name,
            "reason": reason,
            "inputs": inputs,
            "outputs": None,
            "duration_ms": (time.perf_counter() - started) * 1000,
            "error": error,
        }


orchestrator = AgentOrchestrator()
