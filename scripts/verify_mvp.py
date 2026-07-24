"""Fast offline acceptance check. Run from the project root."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import app  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL: {message}")


def main() -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        for path in ("/", "/api/v1/health/live", "/api/v1/health/ready", "/api/v1/skills"):
            response = client.get(path, headers={"X-Request-ID": "verify-mvp"})
            require(response.status_code == 200, f"{path} returned {response.status_code}")

        health = client.get(
            "/api/v1/health/live", headers={"X-Request-ID": "verify-request-id"}
        )
        require(health.headers.get("x-request-id") == "verify-request-id", "response request ID")
        require(health.json()["request_id"] == "verify-request-id", "envelope request ID")

        first = client.post("/api/v1/chat", json={"message": "我想研究 RAG"})
        require(first.status_code == 200, "research session creation")
        first_data = first.json()["data"]
        require(first_data["skill_name"] == "research_clarification_skill", "research routing")
        session_id = first_data["outputs"]["session_id"]

        for message in ("比较", "__unknown__", "教育", "不限", "继续"):
            turn = client.post(
                "/api/v1/chat",
                json={"message": message, "session_id": session_id},
            )
            require(turn.status_code == 200, f"regression sequence at {message!r}")

        year = client.post(
            "/api/v1/chat",
            json={"message": "2021-2026", "session_id": session_id},
        )
        require(year.status_code == 200, "year range turn")
        require(
            year.json()["data"]["skill_name"] == "research_clarification_skill",
            "year range must not route to calculator",
        )

        bad_math = client.post(
            "/api/v1/skills/calculator_skill/execute",
            json={"expression": "5 / 0"},
        )
        require(bad_math.status_code == 422, "v1 validation/execution status")
        require(bad_math.json()["schema_version"] == "1.0", "v1 envelope")

    print("PASS: API、request ID、科研会话、500 回归和错误状态检查全部通过。")


if __name__ == "__main__":
    main()
