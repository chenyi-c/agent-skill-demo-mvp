import time
import re
import httpx
from typing import Dict, Any
from pydantic import BaseModel, Field
from app.services.skills.base import BaseSkill, SkillResult
from app.core.config import settings

class SummaryInput(BaseModel):
    text: str = Field(..., description="The long text document to summarize.")
    max_sentences: int = Field(default=3, description="Maximum number of sentences for the summary.")

def local_summary(text: str, max_sentences: int = 3) -> str:
    # Simple sentence splitting using regex
    sentences = re.split(r'(?<=[。！？.!?])\s*', text.strip())
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return "[本地降级规则摘要] 文本内容为空。"
    
    selected = sentences[:max_sentences]
    summary_text = " ".join(selected)
    return f"[本地降级规则摘要] {summary_text}..."

class TextSummarySkill(BaseSkill):
    name = "summary_skill"
    display_name = "文本智能摘要器"
    description = "对输入的长文本进行关键提炼总结。如果配置了大模型接口则进行智能提炼，否则自动降级为本地句法规则提炼。"
    version = "1.0.0"
    enabled = True
    input_schema = SummaryInput

    async def execute(self, params: Dict[str, Any]) -> SkillResult:
        start_time = time.perf_counter()
        try:
            validated = self.input_schema(**params)
            
            # Check if LLM API Key is configured
            if settings.LLM_API_KEY:
                # Call OpenAI-compatible endpoint using httpx
                headers = {
                    "Authorization": f"Bearer {settings.LLM_API_KEY}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": settings.LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": f"You are a summarization assistant. Summarize the text provided in at most {validated.max_sentences} sentences. Keep it highly relevant and objective."},
                        {"role": "user", "content": validated.text}
                    ],
                    "temperature": 0.3
                }
                url = f"{settings.LLM_BASE_URL}/chat/completions"
                
                async with httpx.AsyncClient() as client:
                    response = await client.post(url, json=payload, headers=headers, timeout=10.0)
                    if response.status_code == 200:
                        data = response.json()
                        summary = data["choices"][0]["message"]["content"].strip()
                        duration = (time.perf_counter() - start_time) * 1000.0
                        return SkillResult(
                            success=True,
                            skill_name=self.name,
                            data={"summary": summary, "mode": "大模型 (LLM API)"},
                            duration_ms=duration
                        )
                    else:
                        # Fallback if API fails
                        fallback = local_summary(validated.text, validated.max_sentences)
                        duration = (time.perf_counter() - start_time) * 1000.0
                        return SkillResult(
                            success=True,
                            skill_name=self.name,
                            data={"summary": fallback, "mode": "本地降级 (模型请求失败)"},
                            duration_ms=duration
                        )
            else:
                # No API key configured, use local fallback
                fallback = local_summary(validated.text, validated.max_sentences)
                duration = (time.perf_counter() - start_time) * 1000.0
                return SkillResult(
                    success=True,
                    skill_name=self.name,
                    data={"summary": fallback, "mode": "本地降级 (未配置 Key)"},
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
