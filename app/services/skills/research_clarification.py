"""Stateful research-requirement clarification skill.

The skill extracts information already present in a user's message, asks one
high-value follow-up at a time, and requires an explicit confirmation before a
SearchPlan can be executed. Session state is persisted in SQLite.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
import uuid
from typing import Any

import httpx
from pydantic import ValidationError

from app.core.errors import AppError
from app.core.config import settings
from app.models.api import ResearchClarificationInput
from app.models.research import (
    AcademicSource,
    ClarificationQuestion,
    ClarificationTurnOutput,
    PublicationType,
    QuestionOption,
    ResearchBrief,
    ResearchSessionStatus,
    SearchPlan,
    SkillWarning,
    YearRange,
)
from app.services.query_extractor import extract_query
from app.services.session_store import create_session, get_session, update_session
from app.services.skills.base import BaseSkill, SkillResult


ALL_SOURCES = [
    AcademicSource.openalex,
    AcademicSource.crossref,
    AcademicSource.semantic,
    AcademicSource.arxiv,
]

BRIEF_FIELDS = set(ResearchBrief.model_fields)

_QUESTIONS: dict[str, ClarificationQuestion] = {
    "topic": ClarificationQuestion(
        field="topic",
        text="你希望重点研究哪个具体主题？",
        reason="主题过宽会让检索结果偏离真正需求。",
        options=[
            QuestionOption(label="RAG / 检索增强生成", value="RAG"),
            QuestionOption(label="代码智能体", value="代码智能体"),
            QuestionOption(label="计算机视觉", value="计算机视觉"),
            QuestionOption(label="演化博弈", value="演化博弈"),
            QuestionOption(label="自己输入", value="__free__"),
        ],
    ),
    "objective": ClarificationQuestion(
        field="objective",
        text="你希望通过这次调研解决哪类问题？",
        reason="研究目标决定关键词组合和论文筛选方式。",
        options=[
            QuestionOption(label="先了解研究现状与热点", value="overview"),
            QuestionOption(label="比较不同方法的优劣", value="compare"),
            QuestionOption(label="解释某种机制或现象", value="explain"),
            QuestionOption(label="构建或改进一种方法", value="build"),
            QuestionOption(label="自己描述核心问题", value="__free__"),
        ],
    ),
    "research_object": ClarificationQuestion(
        field="research_object",
        text="研究对象或应用场景需要限定吗？",
        reason="明确对象能显著减少无关论文。",
        options=[
            QuestionOption(label="不限定，先广泛探索", value="unrestricted"),
            QuestionOption(label="教育与教学场景", value="education"),
            QuestionOption(label="医疗健康场景", value="healthcare"),
            QuestionOption(label="金融与经济场景", value="finance"),
            QuestionOption(label="自己输入", value="__free__"),
        ],
    ),
    "source_preferences": ClarificationQuestion(
        field="source_preferences",
        text="允许检索哪些学术来源？",
        reason="系统只会在你确认的来源白名单内搜索。",
        options=[
            QuestionOption(label="四个来源都使用", value="all"),
            QuestionOption(label="正式期刊/会议优先，不要预印本", value="formal_only"),
            QuestionOption(label="包含 arXiv 预印本", value="include_preprints"),
            QuestionOption(label="只用 OpenAlex 与 Crossref", value="metadata_only"),
        ],
    ),
    "time_range": ClarificationQuestion(
        field="time_range",
        text="论文时间范围如何限定？",
        reason="年份范围会影响结果的新旧与数量。",
        options=[
            QuestionOption(label="近 3 年", value="last_3_years"),
            QuestionOption(label="近 5 年", value="last_5_years"),
            QuestionOption(label="近 10 年", value="last_10_years"),
            QuestionOption(label="不限年份", value="any_year"),
        ],
    ),
    "exclusions": ClarificationQuestion(
        field="exclusions",
        text="有没有需要明确排除的内容？",
        reason="排除项可以避免把不需要的论文类型混入结果。",
        options=[
            QuestionOption(label="没有额外排除项", value="none"),
            QuestionOption(label="排除预印本", value="no_preprints"),
            QuestionOption(label="排除非英文资料", value="english_only"),
            QuestionOption(label="自己输入", value="__free__"),
        ],
    ),
}

_BLOCKING_ORDER = (
    "topic",
    "objective",
    "research_object",
    "source_preferences",
    "time_range",
    "exclusions",
)

_OBJECTIVE_VALUES = {
    "overview": "了解研究现状、主要方向与热点",
    "compare": "比较不同方法的效果、优势与局限",
    "explain": "解释相关机制、影响因素或现象",
    "build": "构建或改进一种研究方法",
    "__unknown__": "先通过文献探索进一步明确问题",
}

_OBJECT_VALUES = {
    "unrestricted": "不限定",
    "education": "教育与教学",
    "healthcare": "医疗健康",
    "finance": "金融与经济",
}


def _current_year() -> int:
    from datetime import datetime

    return datetime.now().year


def _time_value(raw: str) -> YearRange:
    value = raw.strip().lower()
    years = {"last_3_years": 3, "last_5_years": 5, "last_10_years": 10}
    if value in years:
        end = _current_year()
        return YearRange(start=end - years[value] + 1, end=end)
    if value in {"any_year", "不限", "不限年份"}:
        return YearRange(unlimited=True)
    match = re.search(r"(\d{4})\s*[-–—至到]\s*(\d{4})", value)
    if match:
        return YearRange(start=int(match.group(1)), end=int(match.group(2)))
    match = re.search(r"近\s*(\d+)\s*年", value)
    if match:
        end = _current_year()
        return YearRange(start=end - int(match.group(1)) + 1, end=end)
    match = re.search(r"(\d{4})\s*年?\s*以后", value)
    if match:
        return YearRange(start=int(match.group(1)))
    raise ValueError("请提供年份范围，例如 2021-2026、近五年或不限年份")


def _source_value(raw: str) -> list[AcademicSource]:
    value = raw.strip().lower()
    if value in {"all", "include_preprints", "不限", "不限来源", "四个来源都使用"}:
        return list(ALL_SOURCES)
    if value in {"formal_only", "metadata_only", "期刊+会议"}:
        return [AcademicSource.openalex, AcademicSource.crossref, AcademicSource.semantic]
    if value in {"semantic_only", "semantic"}:
        return [AcademicSource.semantic]

    sources: list[AcademicSource] = []
    aliases = {
        AcademicSource.openalex: "openalex",
        AcademicSource.crossref: "crossref",
        AcademicSource.semantic: "semantic",
        AcademicSource.arxiv: "arxiv",
    }
    for source, alias in aliases.items():
        if alias in value:
            sources.append(source)
    if not sources:
        raise ValueError("来源必须从 OpenAlex、Crossref、Semantic Scholar、arXiv 中选择")
    return sources


def _coerce(field: str, raw: str) -> Any:
    value = raw.strip()
    if field == "time_range":
        return _time_value(value)
    if field == "source_preferences":
        return _source_value(value)
    if field == "objective":
        return _OBJECTIVE_VALUES.get(value, value)
    if field == "research_object":
        return _OBJECT_VALUES.get(value, value)
    if field == "exclusions":
        mapping = {
            "none": ["无"],
            "no_preprints": ["预印本"],
            "english_only": ["非英文资料"],
            "无": ["无"],
            "没有": ["无"],
        }
        return mapping.get(value, [value])
    if field in {"method_preferences", "languages", "constraints"}:
        return [part.strip() for part in re.split(r"[,，、;；]", value) if part.strip()]
    if value in {"__unknown__", "__skip__"}:
        return "未指定"
    return value


def _extract_fields(message: str) -> dict[str, Any]:
    text = unicodedata.normalize("NFKC", message).strip()
    fields: dict[str, Any] = {}

    query = extract_query(text)
    if query.confidence >= 0.5 and query.keywords:
        fields["topic"] = " ".join(query.keywords[:4])

    try:
        if re.search(r"近\s*\d+\s*年|\d{4}\s*[-–—至到]\s*\d{4}|不限年份", text):
            fields["time_range"] = _time_value(text)
    except ValueError:
        pass

    if re.search(r"不要\s*(?:预印本|arxiv)|排除\s*(?:预印本|arxiv)|只要\s*(?:期刊|正式)", text, re.I):
        fields["exclusions"] = ["预印本"]
        fields["source_preferences"] = [
            AcademicSource.openalex,
            AcademicSource.crossref,
            AcademicSource.semantic,
        ]
    elif re.search(r"包含\s*(?:预印本|arxiv)|arxiv", text, re.I):
        fields["source_preferences"] = list(ALL_SOURCES)

    if re.search(r"比较|对比|优劣|差异", text):
        fields["objective"] = _OBJECTIVE_VALUES["compare"]
    elif re.search(r"现状|热点|综述|概况|进展", text):
        fields["objective"] = _OBJECTIVE_VALUES["overview"]
    elif re.search(r"构建|改进|提出.*方法", text):
        fields["objective"] = _OBJECTIVE_VALUES["build"]
    elif re.search(r"解释|机制|原因|影响因素", text):
        fields["objective"] = _OBJECTIVE_VALUES["explain"]

    for pattern, label in (
        (r"教育|教学|课程|学生", "教育与教学"),
        (r"医疗|医学|健康|临床", "医疗健康"),
        (r"金融|经济|市场", "金融与经济"),
    ):
        if re.search(pattern, text):
            fields["research_object"] = label
            break

    if re.search(r"数据.{0,8}(?:不清楚|不知道|不确定|未确定)", text):
        fields["data_or_materials"] = "尚未确定"
    elif re.search(r"公开数据|公共数据|benchmark|基准", text, re.I):
        fields["data_or_materials"] = "公开数据集或基准"

    if re.search(r"英文|english", text, re.I):
        fields["languages"] = ["en"]
    elif re.search(r"中文", text):
        fields["languages"] = ["zh"]

    return fields


def _blocking_missing(brief: ResearchBrief) -> list[str]:
    missing: list[str] = []
    for field in _BLOCKING_ORDER:
        value = getattr(brief, field)
        if field == "objective" and (brief.objective or brief.core_question):
            continue
        if value is None or value == "" or value == []:
            missing.append(field)
    return missing


def build_search_plan(brief: ResearchBrief) -> SearchPlan:
    terms = [brief.topic or ""]
    if brief.core_question and brief.core_question != "未指定":
        terms.append(brief.core_question)
    terms.extend(v for v in brief.method_preferences if v != "未指定")
    extracted = extract_query(" ".join(terms))
    keywords = extracted.keywords or [brief.topic or ""]
    sources = list(brief.source_preferences)
    exclusions = [value for value in brief.exclusions if value != "无"]
    if "预印本" in exclusions:
        sources = [source for source in sources if source != AcademicSource.arxiv]
    year = brief.time_range
    publication_types = [
        PublicationType.journal_article,
        PublicationType.conference_paper,
    ]
    if AcademicSource.arxiv in sources:
        publication_types.append(PublicationType.preprint)
    return SearchPlan(
        query=" ".join(keywords[:6]).strip() or (brief.topic or ""),
        keywords=keywords[:12],
        sources=sources,
        year_from=year.start if year and not year.unlimited else None,
        year_to=year.end if year and not year.unlimited else None,
        publication_types=publication_types,
        languages=brief.languages or ["en", "zh"],
        exclusions=exclusions,
        total_limit=12,
    )


def get_confirmed_search_plan(session_id: str) -> tuple[ResearchBrief, SearchPlan, int]:
    row = get_session(session_id)
    brief = _brief_from_row(row)
    if _blocking_missing(brief):
        raise ValueError("研究需求尚未达到可检索条件")
    return brief, build_search_plan(brief), int(row["version"])


def mark_session_completed(session_id: str) -> None:
    row = get_session(session_id)
    update_session(
        session_id,
        status=ResearchSessionStatus.completed.value,
        current_field=None,
        expected_version=int(row["version"]),
    )


def _brief_from_row(row: dict[str, Any]) -> ResearchBrief:
    raw = json.loads(row["brief_json"])
    # Repair the two corrupt shapes produced by the previous implementation.
    if isinstance(raw.get("time_range"), str):
        raw["time_range"] = _time_value(raw["time_range"]).model_dump(mode="json")
    if isinstance(raw.get("source_preferences"), str):
        raw["source_preferences"] = [s.value for s in _source_value(raw["source_preferences"])]
    return ResearchBrief.model_validate(raw)


class ResearchClarificationSkill(BaseSkill):
    name = "research_clarification_skill"
    display_name = "科研需求确认"
    description = "逐轮补全研究主题、目标、范围、来源与年份，确认后生成受约束检索计划。"
    version = "3.0.0"
    input_schema = ResearchClarificationInput
    output_schema = ClarificationTurnOutput

    async def execute(self, params: dict[str, Any]) -> SkillResult:
        started = time.perf_counter()
        try:
            request = ResearchClarificationInput.model_validate(params)
            return await self._execute(request, started)
        except ValueError as exc:
            # A natural-language answer that cannot be coerced to the active
            # field is a normal conversation event, not an API failure.
            session_id = getattr(locals().get("request"), "session_id", None)
            if session_id:
                try:
                    row = get_session(session_id)
                    brief = _brief_from_row(row)
                    return await self._result(
                        started,
                        session_id,
                        ResearchSessionStatus(row["status"]),
                        brief,
                        [],
                        [
                            SkillWarning(
                                code="INVALID_ANSWER",
                                message=f"{exc} 请点击一个选项，或换一种方式输入。",
                            )
                        ],
                    )
                except AppError:
                    pass
            return self._failure(started, str(exc))
        except (AppError, ValidationError) as exc:
            return self._failure(started, str(exc))
        except Exception as exc:
            return self._failure(started, f"科研需求会话处理失败: {exc}")

    async def _execute(self, request: ResearchClarificationInput, started: float) -> SkillResult:
        message = unicodedata.normalize("NFKC", request.message).strip()
        action = request.action
        session_id = request.session_id

        if action == "restart":
            if session_id:
                try:
                    row = get_session(session_id)
                    update_session(
                        session_id,
                        status=ResearchSessionStatus.cancelled.value,
                        current_field=None,
                        expected_version=int(row["version"]),
                    )
                except AppError:
                    pass
            session_id = None

        if not session_id:
            session_id = str(uuid.uuid4())
            brief = ResearchBrief.model_validate(_extract_fields(message))
            row = create_session(session_id, brief.model_dump(mode="json"))
            return await self._persist_and_result(
                started, row, brief, list(_extract_fields(message)), []
            )

        row = get_session(session_id)
        brief = _brief_from_row(row)
        status = ResearchSessionStatus(row["status"])
        if status in {
            ResearchSessionStatus.cancelled,
            ResearchSessionStatus.completed,
            ResearchSessionStatus.expired,
        }:
            return await self._result(
                started,
                session_id,
                status,
                brief,
                [],
                [SkillWarning(code="SESSION_CLOSED", message="该会话已结束，请重新开始。")],
            )

        if action == "cancel":
            updated = update_session(
                session_id,
                status=ResearchSessionStatus.cancelled.value,
                current_field=None,
                expected_version=int(row["version"]),
            )
            return await self._result(
                started, session_id, ResearchSessionStatus.cancelled, brief, [], []
            )

        if action == "confirm":
            missing = _blocking_missing(brief)
            if missing:
                return await self._result(
                    started,
                    session_id,
                    ResearchSessionStatus.collecting,
                    brief,
                    [],
                    [
                        SkillWarning(
                            code="INCOMPLETE",
                            message=f"还需确认：{'、'.join(missing)}",
                        )
                    ],
                )
            update_session(
                session_id,
                status=ResearchSessionStatus.ready.value,
                current_field=None,
                expected_version=int(row["version"]),
            )
            return await self._result(
                started, session_id, ResearchSessionStatus.ready, brief, [], []
            )

        current_field = request.target_field or row.get("current_field")
        if action in {"update", "skip"}:
            if current_field not in BRIEF_FIELDS:
                raise ValueError("修改或跳过时必须指定有效字段")
            value = self._skip_value(current_field) if action == "skip" else _coerce(current_field, message)
            brief = ResearchBrief.model_validate(
                {**brief.model_dump(mode="json"), current_field: value}
            )
            if (
                current_field == "source_preferences"
                and not brief.exclusions
                and set(brief.source_preferences) == set(ALL_SOURCES)
            ):
                brief.exclusions = ["无"]
            updated_fields = [current_field]
        else:
            extracted = _extract_fields(message)
            if current_field and current_field not in extracted and not extracted:
                extracted[current_field] = _coerce(current_field, message)
            merged = {**brief.model_dump(mode="json"), **extracted}
            brief = ResearchBrief.model_validate(merged)
            updated_fields = list(extracted)

        return await self._persist_and_result(started, row, brief, updated_fields, [])

    @staticmethod
    def _skip_value(field: str) -> Any:
        mapping: dict[str, Any] = {
            "objective": "先通过文献探索进一步明确问题",
            "research_object": "不限定",
            "source_preferences": [source.value for source in ALL_SOURCES],
            "time_range": YearRange(unlimited=True).model_dump(mode="json"),
            "exclusions": ["无"],
            "data_or_materials": "未指定",
            "expected_output": "论文候选清单",
            "method_preferences": ["未指定"],
            "languages": ["en", "zh"],
        }
        if field == "topic":
            raise ValueError("研究主题不能跳过")
        return mapping.get(field, "未指定")

    async def _persist_and_result(
        self,
        started: float,
        row: dict[str, Any],
        brief: ResearchBrief,
        updated_fields: list[str],
        warnings: list[SkillWarning],
    ) -> SkillResult:
        missing = _blocking_missing(brief)
        status = (
            ResearchSessionStatus.collecting
            if missing
            else ResearchSessionStatus.awaiting_confirmation
        )
        current_field = missing[0] if missing else None
        updated_row = update_session(
            row["session_id"],
            status=status.value,
            brief=brief.model_dump(mode="json"),
            current_field=current_field,
            expected_version=int(row["version"]),
        )
        return await self._result(
            started,
            row["session_id"],
            status,
            brief,
            updated_fields,
            warnings,
        )

    async def _result(
        self,
        started: float,
        session_id: str,
        status: ResearchSessionStatus,
        brief: ResearchBrief,
        updated_fields: list[str],
        warnings: list[SkillWarning],
    ) -> SkillResult:
        missing = _blocking_missing(brief)
        question = _QUESTIONS[missing[0]] if status == ResearchSessionStatus.collecting and missing else None
        if question:
            question = ClarificationQuestion.model_validate(await self._llm_question(brief, question))
        can_search = not missing and status in {
            ResearchSessionStatus.awaiting_confirmation,
            ResearchSessionStatus.ready,
        }
        output = ClarificationTurnOutput(
            session_id=session_id,
            status=status,
            brief=brief,
            filled_fields=brief.filled_fields(),
            missing_fields=missing,
            updated_fields=updated_fields,
            question=question,
            search_plan=build_search_plan(brief) if can_search else None,
            can_search=can_search,
            warnings=warnings,
        )
        return SkillResult(
            success=True,
            skill_name=self.name,
            data=output.model_dump(mode="json"),
            duration_ms=(time.perf_counter() - started) * 1000,
        )

    async def _llm_question(self, brief: ResearchBrief, question: ClarificationQuestion) -> dict[str, Any]:
        """Let the model personalise wording only; workflow field stays server-controlled."""
        if not settings.LLM_API_KEY:
            return question.model_dump(mode="json")
        payload = {"brief": brief.model_dump(mode="json"), "field": question.field, "fallback": question.model_dump(mode="json"), "rules": "Return JSON only. Keep field exactly unchanged. Return exactly 3 options. Do not fill or alter research state."}
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.post(f"{str(settings.LLM_BASE_URL).rstrip('/')}/chat/completions", headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"}, json={"model": settings.LLM_MODEL, "messages": [{"role": "system", "content": "Generate one concise Chinese research clarification question."}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}], "temperature": 0.3, "response_format": {"type": "json_object"}})
                response.raise_for_status()
            data = json.loads(response.json()["choices"][0]["message"]["content"])
            data["field"] = question.field
            data["allow_free_text"] = True
            data["allow_skip"] = question.allow_skip
            if not isinstance(data.get("options"), list) or len(data["options"]) != 3:
                raise ValueError("invalid options")
            return ClarificationQuestion.model_validate(data).model_dump(mode="json")
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError, ValidationError):
            return question.model_dump(mode="json")

    def _failure(self, started: float, error: str) -> SkillResult:
        return SkillResult(
            success=False,
            skill_name=self.name,
            data=None,
            error=error,
            duration_ms=(time.perf_counter() - started) * 1000,
        )
