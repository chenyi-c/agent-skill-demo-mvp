"""Fixed, in-memory evaluation cases for the agent demo."""

from collections import Counter
from typing import Any, Dict, List

from app.services.agent import orchestrator
from app.services.registry import registry


_EVALUATION_CASES = (
    {
        "id": "calculator",
        "title": "安全计算路由",
        "expected_skill": "calculator_skill",
        "prompt": "(12 + 3) * 2",
    },
    {
        "id": "summary",
        "title": "文本摘要路由",
        "expected_skill": "summary_skill",
        "prompt": "总结：智能体通过工具调用完成任务，并通过评测持续改进。",
    },
    {
        "id": "research_clarification",
        "title": "科研需求澄清路由",
        "expected_skill": "research_clarification_skill",
        "prompt": "我想研究 RAG 幻觉",
    },
    {
        "id": "fallback",
        "title": "默认回退路由",
        "expected_skill": "echo_skill",
        "prompt": "给我讲一个笑话吧",
    },
)


def list_evaluation_cases() -> List[Dict[str, str]]:
    """Return display metadata only; evaluation prompts remain internal."""
    return [
        {
            "id": case["id"],
            "title": case["title"],
            "expected_skill": case["expected_skill"],
        }
        for case in _EVALUATION_CASES
    ]


async def run_evaluation() -> Dict[str, Any]:
    """Run fixed cases without retaining evaluation state or user content."""
    results: List[Dict[str, Any]] = []
    route_mode_counts: Counter[str] = Counter()
    research_skill = registry.get("research_clarification_skill")

    for case in _EVALUATION_CASES:
        outcome = await orchestrator.execute_task(
            case["prompt"], force_rule_routing=True
        )
        route_mode = outcome["route_mode"]
        route_mode_counts[route_mode] += 1
        passed = outcome["success"] and outcome["skill_name"] == case["expected_skill"]
        results.append(
            {
                "id": case["id"],
                "expected_skill": case["expected_skill"],
                "actual_skill": outcome["skill_name"],
                "success": outcome["success"],
                "passed": passed,
                "route_mode": route_mode,
            }
        )

        # The research skill owns transient browser-session state. Evaluation
        # sessions are deliberately discarded so a run cannot affect chat users.
        if case["expected_skill"] == "research_clarification_skill" and research_skill:
            session_id = (outcome.get("outputs") or {}).get("session_id")
            if session_id:
                research_skill._sessions.pop(session_id, None)

    return {
        "results": results,
        "pass_rate": sum(result["passed"] for result in results) / len(results),
        "route_mode_counts": dict(route_mode_counts),
    }
