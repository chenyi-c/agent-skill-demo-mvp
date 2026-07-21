import time
from typing import Dict, Any
from pydantic import BaseModel, Field
from app.services.skills.base import BaseSkill, SkillResult

class EchoInput(BaseModel):
    text: str = Field(..., description="The message text to echo back to the user.")

class EchoSkill(BaseSkill):
    name = "echo_skill"
    display_name = "Echo 基础测试通道"
    description = "将输入的文本原样返回，用于测试 Agent 系统的基础通道是否连通。"
    version = "1.0.0"
    enabled = True
    input_schema = EchoInput

    async def execute(self, params: Dict[str, Any]) -> SkillResult:
        start_time = time.perf_counter()
        try:
            # Validate input parameters via schema
            validated = self.input_schema(**params)
            duration = (time.perf_counter() - start_time) * 1000.0
            return SkillResult(
                success=True,
                skill_name=self.name,
                data={"reply": f"Echo 响应: {validated.text}"},
                duration_ms=duration
            )
        except Exception as e:
            duration = (time.perf_counter() - start_time) * 1000.0
            return SkillResult(
                success=False,
                skill_name=self.name,
                data=None,
                error=str(e),
                duration_ms=duration
            )
