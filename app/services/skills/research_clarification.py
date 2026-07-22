import time
import uuid
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from app.services.skills.base import BaseSkill, SkillResult


class ResearchClarificationInput(BaseModel):
    message: str = Field(..., min_length=1, description="用户本轮补充的科研需求信息")
    session_id: Optional[str] = Field(default=None, description="科研需求澄清会话 ID")


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
            if current_field:
                state[current_field] = message

            next_field = self._next_field(state)
            duration = (time.perf_counter() - start_time) * 1000.0
            if next_field:
                prompt = self._reply_for(next_field)
                return SkillResult(
                    success=True,
                    skill_name=self.name,
                    data={
                        "session_id": session_id,
                        "completed": False,
                        "state": state.copy(),
                        "reply": prompt["next_question"],
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
