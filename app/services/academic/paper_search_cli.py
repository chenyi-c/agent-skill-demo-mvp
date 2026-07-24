"""paper-search-mcp CLI adapter — wraps the external tool as an AcademicSourceAdapter.

Section 4.3–4.4 of the task book.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import shutil
import subprocess
import time
from typing import Any

from app.models.research import AcademicSource, SourceStatusKind
from app.services.academic.base import (
    SkillContext,
    SourceSearchRequest,
    SourceSearchResult,
)
from app.services.academic.policies import (
    Policy,
    SOURCE_POLICIES,
    PolicyDecision,
)


def _cli_path() -> str:
    """Locate the paper-search executable.  Returns the absolute path or
    raises RuntimeError if not found.

    Checks known install locations first so it works even when the server
    subprocess doesn't inherit the user's PATH.
    """
    # Known uv tool install paths
    candidates = [
        os.path.expandvars(r"%USERPROFILE%\.local\bin\paper-search.exe"),
        os.path.expandvars(r"%USERPROFILE%\.local\bin\paper-search"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    exe = shutil.which("paper-search")
    if exe:
        return exe
    raise RuntimeError(
        "paper-search executable not found; install paper-search-mcp (Section 4.3)."
    )


class PaperSearchCliAdapter:
    """Adapts paper-search CLI calls to the AcademicSourceAdapter protocol."""

    source_name: AcademicSource

    def __init__(self, source: AcademicSource) -> None:
        self.source_name = source

    async def search(
        self,
        request: SourceSearchRequest,
        context: SkillContext,
    ) -> SourceSearchResult:
        t0 = time.perf_counter()
        policy: Policy = SOURCE_POLICIES.get(self.source_name, SOURCE_POLICIES[AcademicSource.openalex])
        try:
            cli = _cli_path()
        except RuntimeError:
            return SourceSearchResult(
                source=self.source_name,
                status=SourceStatusKind.unavailable,
                attempts=0,
                latency_ms=(time.perf_counter() - t0) * 1000,
                error_code="ACADEMIC_CLI_MISSING",
                message="paper-search CLI 未安装或不在 PATH 中。",
            )
        command = [
            cli, "search", request.query,
            "-n", str(request.max_results),
            "-s", self.source_name.value,
        ]
        # Start from current environment, overlay proxy vars if set
        env = os.environ.copy()
        if context.proxy_env:
            env.update(context.proxy_env)

        last_error: str | None = None
        for attempt in range(1, policy.max_attempts + 1):
            decision = policy.allow(attempt)
            if decision == PolicyDecision.FAIL_FAST:
                break
            if decision == PolicyDecision.CIRCUIT_OPEN:
                return SourceSearchResult(
                    source=self.source_name,
                    status=SourceStatusKind.circuit_open,
                    attempts=attempt,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                    error_code="CIRCUIT_OPEN",
                    message="Circuit breaker open for this source.",
                )

            try:
                remaining = context.deadline_at - time.perf_counter()
                if remaining <= 0:
                    return SourceSearchResult(
                        source=self.source_name,
                        status=SourceStatusKind.timeout,
                        attempts=attempt - 1,
                        latency_ms=(time.perf_counter() - t0) * 1000,
                        error_code="GLOBAL_DEADLINE",
                        message="已达到检索总时间预算。",
                    )
                proc = await asyncio.to_thread(
                    subprocess.run,
                    command,
                    capture_output=True,
                    text=True,
                    timeout=max(0.1, min(policy.timeout_seconds, remaining)),
                    env=env,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                last_error = f"Source '{self.source_name.value}' timed out after {policy.timeout_seconds}s."
                policy.record_failure()
                if attempt < policy.max_attempts:
                    await asyncio.sleep(
                        min(
                            policy.backoff_base * (2 ** (attempt - 1))
                            + random.uniform(0, policy.jitter),
                            max(0, context.deadline_at - time.perf_counter()),
                        )
                    )
                continue
            except Exception as exc:
                last_error = str(exc)
                policy.record_failure()
                continue

            if proc.returncode != 0:
                stderr = (proc.stderr or "").strip()
                # Classify by stderr patterns
                if "429" in stderr or "Rate limited" in stderr:
                    last_error = f"Rate limited (429)"
                    policy.record_failure()
                    if attempt < policy.max_attempts:
                        await asyncio.sleep(
                            min(
                                policy.backoff_base * (2 ** (attempt - 1))
                                + random.uniform(0, policy.jitter),
                                max(0, context.deadline_at - time.perf_counter()),
                            )
                        )
                    continue  # retry with policy backoff
                if "401" in stderr or "403" in stderr:
                    return SourceSearchResult(
                        source=self.source_name,
                        status=SourceStatusKind.unavailable,
                        attempts=attempt,
                        latency_ms=(time.perf_counter() - t0) * 1000,
                        error_code="AUTH_FAILED",
                        message="Source authentication failed.",
                    )
                last_error = stderr or f"CLI exit code {proc.returncode}"
                # Non-retryable errors
                if attempt < policy.max_attempts and policy.is_retryable("non_zero_exit"):
                    continue
                return SourceSearchResult(
                    source=self.source_name,
                    status=SourceStatusKind.error,
                    attempts=attempt,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                    error_code="CLI_ERROR",
                    message=last_error,
                )

            # Parse stdout
            try:
                data = json.loads(proc.stdout)
            except json.JSONDecodeError:
                last_error = "Invalid JSON from paper-search CLI."
                policy.record_failure()
                continue

            papers = _normalise_papers(data)
            policy.record_success()
            return SourceSearchResult(
                source=self.source_name,
                status=SourceStatusKind.empty if not papers else SourceStatusKind.ok,
                papers=papers,
                attempts=attempt,
                latency_ms=(time.perf_counter() - t0) * 1000,
            )

        # All attempts exhausted
        status = (
            SourceStatusKind.rate_limited
            if last_error and "429" in last_error
            else SourceStatusKind.timeout
            if last_error and "timed out" in last_error
            else SourceStatusKind.error
        )
        return SourceSearchResult(
            source=self.source_name,
            status=status,
            attempts=policy.max_attempts,
            latency_ms=(time.perf_counter() - t0) * 1000,
            error_code="ALL_ATTEMPTS_FAILED",
            message=last_error or "All attempts failed.",
        )


def _normalise_papers(payload: Any) -> list[dict[str, Any]]:
    """Extract the paper list from CLI output (handles {"papers": [...]}, etc.)."""
    if isinstance(payload, list):
        raw = payload
    elif isinstance(payload, dict):
        raw = payload.get("papers", payload.get("results", payload.get("data", [])))
    else:
        return []
    if not isinstance(raw, list):
        return []
    return [p for p in raw if isinstance(p, dict)]
