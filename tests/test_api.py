from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings

client = TestClient(app)

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


