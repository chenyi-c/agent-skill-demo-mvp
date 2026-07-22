"""Academic paper search skill backed by the paper-search CLI."""

import asyncio
import json
import subprocess
import time
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

from app.services.skills.base import BaseSkill, SkillResult


SOURCES = ("arxiv", "semantic", "openalex", "crossref")
SEARCH_TIMEOUT_SECONDS = 20


class AcademicSearchInput(BaseModel):
    query: str = Field(..., min_length=1, description="Academic paper search query")
    limit: int = Field(default=5, description="Number of papers to return (1-5)")


def _run_command(command: List[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=SEARCH_TIMEOUT_SECONDS,
    )


class AcademicSearchSkill(BaseSkill):
    name = "academic_search_skill"
    display_name = "学术论文检索"
    description = "使用 paper-search-mcp 从多个学术来源检索论文。"
    version = "1.0.0"
    enabled = True
    input_schema = AcademicSearchInput

    def __init__(self, command_runner: Optional[Callable[[List[str]], Any]] = None):
        self._command_runner = command_runner or _run_command

    async def execute(self, params: Dict[str, Any]) -> SkillResult:
        started = time.perf_counter()
        try:
            validated = self.input_schema(**params)
            limit = max(1, min(5, validated.limit))
            command = [
                "paper-search", "search", validated.query, "-n", str(limit),
                "-s", ",".join(SOURCES),
            ]
            raw_output = await asyncio.to_thread(self._command_runner, command)
            output = self._extract_output(raw_output)
            parsed = json.loads(output)
            results = self._normalise_results(parsed)
            return SkillResult(
                success=True,
                skill_name=self.name,
                data={"query": validated.query, "limit": limit, "sources": list(SOURCES), "results": results},
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        except FileNotFoundError:
            return self._failure(started, "paper-search executable not found; install paper-search-mcp to enable academic search.")
        except subprocess.TimeoutExpired:
            return self._failure(started, f"paper-search command timed out after {SEARCH_TIMEOUT_SECONDS} seconds.")
        except Exception as exc:
            return self._failure(started, str(exc))

    @staticmethod
    def _extract_output(value: Any) -> str:
        if isinstance(value, str):
            return value
        if getattr(value, "returncode", 0) != 0:
            detail = getattr(value, "stderr", "") or "paper-search command failed"
            raise RuntimeError(detail.strip())
        output = getattr(value, "stdout", None)
        if not isinstance(output, str):
            raise ValueError("paper-search command did not return JSON output")
        return output

    @staticmethod
    def _normalise_results(payload: Any) -> List[Dict[str, Any]]:
        if isinstance(payload, list):
            results = payload
        elif isinstance(payload, dict):
            results = payload.get("results", payload.get("data", []))
        else:
            raise ValueError("paper-search returned JSON that is neither a list nor an object")
        if not isinstance(results, list) or not all(isinstance(item, dict) for item in results):
            raise ValueError("paper-search results must be a list of objects")
        return results

    def _failure(self, started: float, error: str) -> SkillResult:
        return SkillResult(
            success=False,
            skill_name=self.name,
            data=None,
            error=error,
            duration_ms=(time.perf_counter() - started) * 1000,
        )
