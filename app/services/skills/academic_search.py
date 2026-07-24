"""Reliable, source-constrained academic search Skill."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.models.research import (
    AcademicSource,
    OverallStatus,
    PaperRecord,
    PublicationType,
    SourceStatusKind,
)
from app.services.academic.base import SkillContext, SourceSearchRequest
from app.services.academic.cache import cache_get, cache_put
from app.services.academic.deduplicator import deduplicate
from app.services.academic.normalizer import normalise_record
from app.services.academic.paper_search_cli import PaperSearchCliAdapter
from app.services.skills.base import BaseSkill, SkillResult


_SOURCE_SEMAPHORE = asyncio.Semaphore(8)
_GLOBAL_DEADLINE_SECONDS = 10.0


class AcademicSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=300)
    keywords: list[str] = Field(default_factory=list, max_length=12)
    sources: list[AcademicSource] = Field(
        default_factory=lambda: [
            AcademicSource.openalex,
            AcademicSource.crossref,
            AcademicSource.semantic,
            AcademicSource.arxiv,
        ],
        min_length=1,
        max_length=4,
    )
    year_from: int | None = Field(default=None, ge=1900, le=2100)
    year_to: int | None = Field(default=None, ge=1900, le=2100)
    publication_types: list[PublicationType] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    total_limit: int = Field(default=12, ge=1, le=30)
    per_source_limit: int = Field(default=5, ge=1, le=10)
    use_cache: bool = True


class AcademicSearchOutput(BaseModel):
    overall_status: OverallStatus
    query: str
    source_statuses: list[dict[str, Any]]
    errors: dict[str, str]
    results: list[PaperRecord]
    total: int
    sources_used: list[AcademicSource]


class AcademicSearchSkill(BaseSkill):
    name = "academic_search_skill"
    display_name = "受约束学术检索"
    description = "只在 OpenAlex、Crossref、Semantic Scholar 与 arXiv 白名单内检索，支持部分失败。"
    version = "3.1.0"
    input_schema = AcademicSearchInput
    output_schema = AcademicSearchOutput

    def __init__(self, *, _adapter_factory=None):
        self._adapter_factory = _adapter_factory

    async def execute(self, params: dict[str, Any]) -> SkillResult:
        started = time.perf_counter()
        try:
            request = AcademicSearchInput.model_validate(params)
            if request.year_from and request.year_to and request.year_from > request.year_to:
                raise ValueError("起始年份不能晚于结束年份")
        except (ValidationError, ValueError) as exc:
            return SkillResult(
                success=False,
                skill_name=self.name,
                data=None,
                error=f"参数校验失败: {exc}",
                duration_ms=(time.perf_counter() - started) * 1000,
            )

        # De-duplicate source selection while preserving order.
        sources = list(dict.fromkeys(request.sources))
        deadline = time.perf_counter() + _GLOBAL_DEADLINE_SECONDS
        context = SkillContext(deadline_at=deadline)

        async def search_one(source: AcademicSource) -> dict[str, Any]:
            cache_variant = json.dumps(
                {
                    "q": request.query,
                    "n": request.per_source_limit,
                    "yf": request.year_from,
                    "yt": request.year_to,
                    "pt": [v.value for v in request.publication_types],
                    "lang": request.languages,
                },
                sort_keys=True,
                ensure_ascii=False,
            )
            stale: dict[str, Any] | None = None
            if request.use_cache:
                cached = cache_get(source.value, cache_variant)
                if cached and not cached.get("stale_cache"):
                    cached = dict(cached)
                    cached["status"] = SourceStatusKind.cache_hit.value
                    cached["cache_hit"] = True
                    return cached
                stale = cached

            try:
                async with _SOURCE_SEMAPHORE:
                    remaining = deadline - time.perf_counter()
                    if remaining <= 0:
                        raise asyncio.TimeoutError
                    adapter = (
                        self._adapter_factory(source)
                        if self._adapter_factory
                        else PaperSearchCliAdapter(source)
                    )
                    result = await asyncio.wait_for(
                        adapter.search(
                            SourceSearchRequest(
                                query=request.query,
                                keywords=request.keywords,
                                max_results=request.per_source_limit,
                                year_from=request.year_from,
                                year_to=request.year_to,
                            ),
                            context,
                        ),
                        timeout=remaining,
                    )
            except asyncio.TimeoutError:
                result = None
                failure = {
                    "source": source.value,
                    "status": SourceStatusKind.timeout.value,
                    "result_count": 0,
                    "attempts": 0,
                    "latency_ms": max(0, (_GLOBAL_DEADLINE_SECONDS - max(0, deadline - time.perf_counter()))) * 1000,
                    "error_code": "GLOBAL_DEADLINE",
                    "message": "该来源超过本次检索总时间预算。",
                    "papers": [],
                    "cache_hit": False,
                    "stale_cache": False,
                }
            except Exception as exc:
                result = None
                failure = {
                    "source": source.value,
                    "status": SourceStatusKind.error.value,
                    "result_count": 0,
                    "attempts": 0,
                    "latency_ms": 0,
                    "error_code": "ADAPTER_ERROR",
                    "message": str(exc),
                    "papers": [],
                    "cache_hit": False,
                    "stale_cache": False,
                }

            if result is not None:
                papers: list[dict[str, Any]] = []
                for raw in result.papers:
                    try:
                        paper = PaperRecord.model_validate(
                            normalise_record(raw, source.value)
                        )
                        papers.append(paper.model_dump(mode="json"))
                    except (ValidationError, TypeError, ValueError):
                        continue
                failure = {
                    "source": source.value,
                    "status": result.status.value,
                    "result_count": len(papers),
                    "attempts": result.attempts,
                    "latency_ms": result.latency_ms,
                    "error_code": result.error_code,
                    "message": result.message,
                    "papers": papers,
                    "cache_hit": False,
                    "stale_cache": False,
                }
                if request.use_cache and result.status in {
                    SourceStatusKind.ok,
                    SourceStatusKind.empty,
                }:
                    try:
                        cache_put(
                            source.value,
                            cache_variant,
                            json.dumps(failure, ensure_ascii=False, default=str),
                            result.status.value,
                        )
                    except Exception:
                        pass

            failed_states = {
                SourceStatusKind.timeout.value,
                SourceStatusKind.rate_limited.value,
                SourceStatusKind.unavailable.value,
                SourceStatusKind.invalid_response.value,
                SourceStatusKind.error.value,
                SourceStatusKind.circuit_open.value,
            }
            if failure["status"] in failed_states and stale:
                restored = dict(stale)
                restored["status"] = SourceStatusKind.stale_cache.value
                restored["cache_hit"] = True
                restored["stale_cache"] = True
                restored["message"] = (
                    f"实时来源失败（{failure.get('error_code') or failure['status']}），"
                    "已返回过期缓存。"
                )
                return restored
            return failure

        task_map = {
            asyncio.create_task(search_one(source)): source for source in sources
        }
        done, pending = await asyncio.wait(
            task_map,
            timeout=_GLOBAL_DEADLINE_SECONDS,
            return_when=asyncio.ALL_COMPLETED,
        )
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        source_results: list[dict[str, Any]] = []
        for task in done:
            source = task_map[task]
            try:
                source_results.append(task.result())
            except Exception as exc:
                source_results.append(
                    {
                        "source": source.value,
                        "status": SourceStatusKind.error.value,
                        "result_count": 0,
                        "attempts": 0,
                        "latency_ms": 0,
                        "error_code": "INTERNAL",
                        "message": str(exc),
                        "papers": [],
                    }
                )
        for task in pending:
            source = task_map[task]
            source_results.append(
                {
                    "source": source.value,
                    "status": SourceStatusKind.timeout.value,
                    "result_count": 0,
                    "attempts": 0,
                    "latency_ms": _GLOBAL_DEADLINE_SECONDS * 1000,
                    "error_code": "GLOBAL_DEADLINE",
                    "message": "该来源超过本次检索总时间预算。",
                    "papers": [],
                }
            )

        source_results.sort(key=lambda item: sources.index(AcademicSource(item["source"])))
        papers: list[dict[str, Any]] = []
        errors: dict[str, str] = {}
        successful_states = {
            SourceStatusKind.ok.value,
            SourceStatusKind.empty.value,
            SourceStatusKind.cache_hit.value,
            SourceStatusKind.stale_cache.value,
        }
        for item in source_results:
            papers.extend(item.pop("papers", []))
            if item["status"] not in successful_states:
                errors[item["source"]] = item.get("error_code") or item["status"]

        papers = deduplicate(papers)[: request.total_limit]
        successful = sum(1 for item in source_results if item["status"] in successful_states)
        if successful == len(sources):
            overall = OverallStatus.ok if papers else OverallStatus.empty
        elif successful > 0:
            overall = OverallStatus.degraded
        else:
            overall = OverallStatus.error

        output = AcademicSearchOutput(
            overall_status=overall,
            query=request.query,
            source_statuses=source_results,
            errors=errors,
            results=[PaperRecord.model_validate(paper) for paper in papers],
            total=len(papers),
            sources_used=sources,
        )
        return SkillResult(
            success=overall != OverallStatus.error,
            skill_name=self.name,
            data=output.model_dump(mode="json"),
            error="所有已选学术来源均失败。" if overall == OverallStatus.error else None,
            duration_ms=(time.perf_counter() - started) * 1000,
        )
