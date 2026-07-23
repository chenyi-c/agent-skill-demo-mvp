from pathlib import Path

from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings
from app.services.agent import orchestrator
from app.services.registry import registry

client = TestClient(app)


def test_evaluation_cases_expose_metadata_without_prompts():
    response = client.get("/api/evaluation/cases")

    assert response.status_code == 200
    cases = response.json()
    assert [case["id"] for case in cases] == [
        "calculator",
        "summary",
        "research_clarification",
        "fallback",
    ]
    assert all("prompt" not in case for case in cases)
    assert all("message" not in case for case in cases)
    assert {case["expected_skill"] for case in cases} == {
        "calculator_skill",
        "summary_skill",
        "research_clarification_skill",
        "echo_skill",
    }


def test_evaluation_run_returns_deterministic_metrics_and_results(monkeypatch):
    monkeypatch.setattr(settings, "LLM_API_KEY", "configured-key")
    research_skill = registry.get("research_clarification_skill")
    sessions_before = research_skill._sessions.copy()

    response = client.post("/api/evaluation/run")

    assert response.status_code == 200
    data = response.json()
    assert data["pass_rate"] == 1.0
    assert data["route_mode_counts"] == {"智能路由 (规则匹配)": 4}
    assert [result["id"] for result in data["results"]] == [
        "calculator",
        "summary",
        "research_clarification",
        "fallback",
    ]
    assert all(result["passed"] is True for result in data["results"])
    assert all("prompt" not in result for result in data["results"])
    assert all("reply" not in result for result in data["results"])
    assert research_skill._sessions == sessions_before

    repeat = client.post("/api/evaluation/run")
    assert repeat.status_code == 200
    assert repeat.json()["results"] == data["results"]


def test_static_page_includes_a_compact_evaluation_panel():
    page = Path("static/index.html").read_text(encoding="utf-8")

    assert 'id="evaluationPanel"' in page
    assert 'id="runEvaluationBtn"' in page
    assert 'id="passRate"' in page
    assert 'id="routeModeCounts"' in page
    assert 'id="evaluationResults"' in page
    assert "/api/evaluation/run" in page

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_get_skills():
    response = client.get("/api/skills")
    assert response.status_code == 200
    skills = response.json()
    assert len(skills) >= 3
    
    # Check that Calculator is registered
    calc = next((s for s in skills if s["name"] == "calculator_skill"), None)
    assert calc is not None
    assert "expression" in calc["parameters_schema"]

    assert any(skill["name"] == "research_clarification_skill" for skill in skills)
    assert any(skill["name"] == "academic_search_skill" for skill in skills)


def test_chat_routes_research_clarification_with_a_session():
    settings.LLM_API_KEY = None
    response = client.post("/api/chat", json={"message": "我想研究 RAG 幻觉"})
    assert response.status_code == 200
    first = response.json()
    assert first["success"] is True
    assert first["skill_name"] == "research_clarification_skill"
    assert first["session_id"]
    assert first["outputs"]["next_field"] == "core_problem"

    second = client.post("/api/chat", json={
        "message": "减少引用错误",
        "session_id": first["session_id"],
    })
    assert second.status_code == 200
    assert second.json()["skill_name"] == "research_clarification_skill"
    assert second.json()["outputs"]["next_field"] == "data_and_method"


def test_math_request_is_not_hijacked_by_a_research_session():
    settings.LLM_API_KEY = None
    session = client.post("/api/chat", json={"message": "我想研究 RAG"}).json()["session_id"]
    response = client.post("/api/chat", json={"message": "2 + 2", "session_id": session})
    assert response.status_code == 200
    assert response.json()["skill_name"] == "calculator_skill"


def test_research_session_continues_before_llm_routing(monkeypatch):
    async def llm_would_choose_echo(_user_input):
        return "echo_skill", {"text": "减少引用错误"}, "模型决策: 错误分流。"

    monkeypatch.setattr(settings, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(orchestrator, "_llm_route", llm_would_choose_echo)

    response = client.post("/api/chat", json={
        "message": "减少引用错误",
        "session_id": "session-from-a-previous-research-turn",
    })

    assert response.status_code == 200
    assert response.json()["skill_name"] == "research_clarification_skill"

def test_chat_rule_routing_math():
    settings.LLM_API_KEY = None
    
    response = client.post("/api/chat", json={"message": "(5 + 10) * 3"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["skill_name"] == "calculator_skill"
    assert "45.0" in data["reply"]
    assert "基于规则" in data["reason"]

def test_chat_rule_routing_summary():
    response = client.post("/api/chat", json={"message": "总结：Java is a programming language. It is object-oriented. It runs everywhere."})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["skill_name"] == "summary_skill"
    assert "降级" in data["reply"]

def test_chat_rule_routing_echo():
    response = client.post("/api/chat", json={"message": "给我讲一个笑话吧"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["skill_name"] == "echo_skill"
    assert "Echo 响应: 给我讲一个笑话吧" in data["reply"]

def test_chat_manual_preferred_skill():
    response = client.post("/api/chat", json={
        "message": "3 + 3", 
        "preferred_skill": "echo_skill"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["skill_name"] == "echo_skill"
    assert "Echo 响应: 3 + 3" in data["reply"]
    assert data["route_mode"] == "手动指定"

def test_chat_error_missing_skill():
    response = client.post("/api/chat", json={
        "message": "Hello", 
        "preferred_skill": "non_existent_skill"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "未找到或已禁用" in data["reply"]

def test_api_configuration():
    # Update config
    response = client.post("/api/config", json={
        "api_key": "test_api_key_12345",
        "base_url": "https://test.api.url/v1",
        "model": "test-model-name"
    })
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    
    # Retrieve config
    response_get = client.get("/api/config")
    assert response_get.status_code == 200
    data = response_get.json()
    assert "test****2345" in data["api_key"]
    assert data["base_url"] == "https://test.api.url/v1"
    assert data["model"] == "test-model-name"


