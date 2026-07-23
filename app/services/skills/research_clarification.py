import time
import uuid
import json
from typing import Any, Dict, Optional

import httpx
from pydantic import BaseModel, Field, field_validator

from app.core.config import settings
from app.services.skills.base import BaseSkill, SkillResult


class ResearchClarificationInput(BaseModel):
    message: str = Field(..., min_length=1, description="用户本轮补充的科研需求信息")
    session_id: Optional[str] = Field(default=None, description="科研需求澄清会话 ID")


class ClarificationLLMOutput(BaseModel):
    reply: str = Field(min_length=1)
    next_question: str = Field(min_length=1)
    options: list[str]
    suggested_value: Optional[str] = None

    @field_validator("options")
    @classmethod
    def validate_options(cls, value: list[str]) -> list[str]:
        if len(value) != 3 or any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError("options must contain exactly three non-empty strings")
        return [item.strip() for item in value]


class ResearchClarificationSkill(BaseSkill):
    name = "research_clarification_skill"
    display_name = "科研需求确认"
    description = "通过单轮单问题的方式补全研究方向、问题、方法、约束和交付物。"
    input_schema = ResearchClarificationInput

    _fields = (
        "domain",
        "core_problem",
        "data_and_method",
        "constraints",
        "expected_output",
    )
    _questions = {
        "domain": ("你希望研究哪个领域或主题？", ["RAG 与知识问答", "代码智能体", "计算机视觉"]),
        "core_problem": ("你最希望解决的具体问题是什么？", ["减少模型幻觉", "提升任务成功率", "降低推理成本"]),
        "data_and_method": ("你计划使用哪些数据、基准或方法？", ["公开基准测试集", "真实课程或项目数据", "开源模型与自建实验"]),
        "constraints": ("你的时间、算力或经费限制是什么？", ["一周验证原型", "两周完成实验", "消费级显卡或 API 预算有限"]),
        "expected_output": ("你最终希望交付什么成果？", ["研究选题简报", "可运行代码原型", "论文或实验报告"]),
    }

    def __init__(self) -> None:
        self._sessions: Dict[str, Dict[str, Optional[str]]] = {}

    def _new_state(self) -> Dict[str, Optional[str]]:
        return {field: None for field in self._fields}

    def _next_field(self, state: Dict[str, Optional[str]]) -> Optional[str]:
        return next((field for field in self._fields if not state[field]), None)

    def _reply_for(self, field: str) -> Dict[str, Any]:
        question, options = self._questions[field]
        return {"next_field": field, "next_question": question, "options": options}

    def _rule_plan(self, brief: Dict[str, str]) -> Dict[str, Any]:
        topic = f"面向{brief['domain']}的{brief['core_problem']}"
        keywords = [brief['domain'], brief['core_problem'], brief['data_and_method']]
        return {
            "research_question": topic,
            "research_goals": ["明确可验证的问题边界", "建立可复现实验对照", "产出" + brief['expected_output']],
            "candidate_methods_or_baselines": [brief['data_and_method'], "公开强基线", "消融对照实验"],
            "datasets_or_metrics": ["优先使用与问题匹配的公开基准", "任务成功率/准确率", "成本与时延"],
            "two_week_mvp": ["第 1-3 天：确定基线与数据", "第 4-9 天：实现最小实验", "第 10-14 天：复现实验、分析风险并整理报告"],
            "risks_and_mitigations": [f"约束：{brief['constraints']}；优先缩小问题范围", "数据或工具不可用时使用公开基准与可复现基线"],
            "search_keywords": [item for item in keywords if item],
            "mode": "rule_fallback",
        }

    @staticmethod
    def _needs_recommendation(message: str) -> bool:
        normalized = message.replace(" ", "").lower()
        return any(token in normalized for token in ("不知道", "不清楚", "推荐", "建议", "帮我想"))

    async def _call_llm(self, state: Dict[str, Optional[str]], message: str, next_field: str, needs_suggestion: bool) -> Optional[Dict[str, Any]]:
        if not settings.LLM_API_KEY:
            return None
        prompt = {
            "state": state,
            "latest_user_message": message,
            "next_field": next_field,
            "needs_suggestion_for_current_field": needs_suggestion,
            "rules": "Do not change next_field or workflow. Return JSON only: reply, next_question, options (exactly 3 strings), suggested_value (only when needs_suggestion is true).",
        }
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{settings.LLM_BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.LLM_API_KEY}", "Content-Type": "application/json"},
                    json={"model": settings.LLM_MODEL, "messages": [{"role": "system", "content": "Generate concise Chinese research clarification content. Obey the supplied workflow."}, {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}], "temperature": 0.3, "response_format": {"type": "json_object"}},
                    timeout=8.0,
                )
            if response.status_code != 200:
                return None
            parsed = ClarificationLLMOutput.model_validate(json.loads(response.json()["choices"][0]["message"]["content"]))
            if needs_suggestion and not parsed.suggested_value:
                return None
            return parsed.model_dump()
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    async def execute(self, params: Dict[str, Any]) -> SkillResult:
        start_time = time.perf_counter()
        try:
            validated = self.input_schema(**params)
            message = validated.message.strip()
            if not message:
                raise ValueError("请输入本轮科研需求信息。")

            session_id = validated.session_id or str(uuid.uuid4())
            state = self._sessions.setdefault(session_id, self._new_state())
            current_field = self._next_field(state)
            needs_suggestion = self._needs_recommendation(message)
            if current_field:
                if needs_suggestion:
                    suggestion = await self._call_llm(state.copy(), message, current_field, True)
                    state[current_field] = suggestion["suggested_value"] if suggestion else self._questions[current_field][1][0]
                else:
                    state[current_field] = message

            next_field = self._next_field(state)
            duration = (time.perf_counter() - start_time) * 1000.0
            if next_field:
                prompt = self._reply_for(next_field)
                generated = await self._call_llm(state.copy(), message, next_field, False)
                if generated:
                    prompt.update({key: generated[key] for key in ("next_question", "options")})
                    prompt["reply"] = generated["reply"]
                return SkillResult(
                    success=True,
                    skill_name=self.name,
                    data={
                        "session_id": session_id,
                        "completed": False,
                        "state": state.copy(),
                        "reply": prompt.get("reply", prompt["next_question"]),
                        "question": prompt["next_question"],
                        **prompt,
                    },
                    duration_ms=duration,
                )

            brief = {field: state[field] for field in self._fields}
            query = " ".join(
                value for field, value in brief.items() if field != "constraints" and value
            )
            return SkillResult(
                success=True,
                skill_name=self.name,
                data={
                    "session_id": session_id,
                    "completed": True,
                    "research_brief": brief,
                    "research_plan": self._rule_plan(brief),
                    "query": query,
                    "reply": "科研需求已确认，可以开始受限学术检索。",
                },
                duration_ms=duration,
            )
        except Exception as exc:
            return SkillResult(
                success=False,
                skill_name=self.name,
                data=None,
                error=str(exc),
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
            )
