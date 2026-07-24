"""Regression tests for failures seen in the browser and real upstream faults."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.research import AcademicSource, SourceStatusKind
from app.services.query_extractor import extract_query
from app.services.skills.academic_search import AcademicSearchSkill


@pytest.fixture()
def client():
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_research_option_sequence_never_returns_500(client):
    """The exact browser sequence that used to corrupt YearRange and 500."""
    response = client.post("/api/v1/chat", json={"message": "我想研究 RAG"})
    assert response.status_code == 200
    session_id = response.json()["data"]["outputs"]["session_id"]

    for message in ("比较", "__unknown__", "教育", "不限", "继续"):
        response = client.post(
            "/api/v1/chat",
            json={"message": message, "session_id": session_id},
        )
        assert response.status_code == 200, response.text
        assert response.headers["x-request-id"]
        payload = response.json()
        assert payload["schema_version"] == "1.0"
        assert payload["request_id"] == response.headers["x-request-id"]


def test_year_range_is_not_routed_to_calculator_inside_research_session(client):
    first = client.post("/api/v1/chat", json={"message": "我想研究 RAG"})
    session_id = first.json()["data"]["outputs"]["session_id"]
    response = client.post(
        "/api/v1/chat",
        json={"message": "2021-2026", "session_id": session_id},
    )
    assert response.status_code == 200
    assert response.json()["data"]["skill_name"] == "research_clarification_skill"


@pytest.mark.parametrize(
    ("message", "must_contain", "must_not_contain"),
    [
        ("我想研究演化博弈法，数据来源不太清楚", "演化博弈", "数据来源不太清楚"),
        ("请检索 2024-2025 年 RAG 论文", "RAG", "请检索"),
        ("帮我找近五年关于代码 Agent 评测的英文期刊论文", "Agent", "帮我找"),
        ("计算机视觉 2024 年论文", "计算机视觉", "论文"),
    ],
)
def test_query_extractor_does_not_use_raw_request(
    message, must_contain, must_not_contain
):
    result = extract_query(message)
    assert must_contain.lower() in result.normalized_query.lower()
    assert must_not_contain.lower() not in result.normalized_query.lower()
    assert result.normalized_query != message


def test_query_extractor_requires_topic_when_input_only_has_constraints():
    result = extract_query("只要正式发表的论文，不要 arXiv")
    assert result.needs_clarification
    assert result.normalized_query == ""


@pytest.mark.asyncio
async def test_academic_malformed_source_data_isolated():
    class Adapter:
        def __init__(self, source):
            self.source_name = source

        async def search(self, request, context):
            papers = (
                [{"title": ["invalid title"]}]
                if self.source_name == AcademicSource.arxiv
                else [{"title": f"Valid {self.source_name.value}", "authors": "<team>"}]
            )
            return type(
                "Result",
                (),
                {
                    "source": self.source_name,
                    "status": SourceStatusKind.ok,
                    "papers": papers,
                    "attempts": 1,
                    "latency_ms": 1.0,
                    "error_code": None,
                    "message": None,
                },
            )()

    result = await AcademicSearchSkill(_adapter_factory=Adapter).execute(
        {"query": "RAG evaluation", "use_cache": False}
    )
    assert result.success
    assert result.data["overall_status"] == "ok"
    assert result.data["total"] == 4


@pytest.mark.asyncio
async def test_academic_global_deadline_cancels_slow_sources(monkeypatch):
    import app.services.skills.academic_search as academic_module

    monkeypatch.setattr(academic_module, "_GLOBAL_DEADLINE_SECONDS", 0.05)

    class SlowAdapter:
        def __init__(self, source):
            self.source_name = source

        async def search(self, request, context):
            await asyncio.sleep(1)

    result = await AcademicSearchSkill(_adapter_factory=SlowAdapter).execute(
        {"query": "deadline test", "use_cache": False}
    )
    assert not result.success
    assert result.data["overall_status"] == "error"
    assert all(
        item["status"] == "timeout" for item in result.data["source_statuses"]
    )


def test_v1_skill_failure_uses_422_envelope(client):
    response = client.post(
        "/api/v1/skills/calculator_skill/execute",
        json={"expression": "5 / 0"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SKILL_EXECUTION_FAILED"


def test_frontend_uses_module_assets_and_safe_rendering_helpers(client):
    page = client.get("/")
    script = client.get("/static/app.js")
    css = client.get("/static/app.css")
    assert page.status_code == script.status_code == css.status_code == 200
    assert 'type="module"' in page.text
    assert "escapeHtml" in script.text
    assert "innerHTML = text" not in script.text
    assert "@media (max-width: 760px)" in css.text
