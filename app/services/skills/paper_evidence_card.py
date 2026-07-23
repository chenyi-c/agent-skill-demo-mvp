"""Metadata-first paper evidence cards; never invent unavailable paper facts."""
import time
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
from app.services.skills.base import BaseSkill, SkillResult

class PaperEvidenceInput(BaseModel):
    title: Optional[str] = None
    url: Optional[str] = None
    arxiv_id: Optional[str] = None
    abstract: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    research_plan: Optional[Dict[str, Any]] = None

class PaperEvidenceCardSkill(BaseSkill):
    name = "paper_evidence_card_skill"
    display_name = "论文证据卡片"
    description = "基于已选论文的元数据或摘要生成可追溯证据卡片，不伪造全文结论。"
    input_schema = PaperEvidenceInput

    async def execute(self, params: Dict[str, Any]) -> SkillResult:
        started = time.perf_counter()
        try:
            item = self.input_schema(**params)
            meta = item.metadata or {}
            title = item.title or meta.get("title")
            abstract = item.abstract or meta.get("abstract")
            if not title and not item.arxiv_id and not item.url:
                raise ValueError("请提供论文标题、链接、arXiv ID 或检索结果元数据。")
            if not abstract:
                reason = "未提供可读取的论文摘要/正文；未安装或未接入全文读取工具时只能生成元数据降级卡片。"
                card = {"paper_title": title or item.arxiv_id or item.url, "research_question": "未提供，不能推断", "core_method": "未提供，不能推断", "datasets_or_setup": "未提供，不能推断", "main_findings": "未提供，不能推断", "limitations": reason, "relation_to_research_plan": "需要摘要或正文后才能判断", "next_step": "粘贴摘要，或安装并配置论文全文读取工具后重试。", "source_status": "metadata_only"}
            else:
                card = {"paper_title": title or "未提供标题", "research_question": abstract, "core_method": "请依据摘要核对具体方法，系统不从缺失全文推断", "datasets_or_setup": "摘要未明确时不能推断", "main_findings": abstract, "limitations": "仅基于用户提供的摘要，未读取全文", "relation_to_research_plan": "可与研究计划关键词进行人工比对", "next_step": "阅读原文方法与实验章节后补充证据。", "source_status": "abstract_only"}
            return SkillResult(success=True, skill_name=self.name, data={"evidence_card": card, "url": item.url or meta.get("url"), "arxiv_id": item.arxiv_id, "llm_used": False}, duration_ms=(time.perf_counter()-started)*1000)
        except Exception as exc:
            return SkillResult(success=False, skill_name=self.name, data=None, error=str(exc), duration_ms=(time.perf_counter()-started)*1000)
