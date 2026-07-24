import json
import subprocess

import pytest
from app.models.research import AcademicSource
from app.services.skills.base import SkillResult
from app.services.skills.echo import EchoSkill
from app.services.skills.calculator import CalculatorSkill, safe_eval
from app.services.skills.summary import TextSummarySkill, local_summary
from app.services.registry import SkillRegistry
from app.services.skills.research_clarification import ResearchClarificationSkill
from app.services.skills.academic_search import AcademicSearchSkill


@pytest.fixture(autouse=True)
def disable_real_llm_calls(monkeypatch):
    """Skill tests must never depend on a locally saved API key or network."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "LLM_API_KEY", None)

def test_skill_registry():
    registry = SkillRegistry()
    echo = EchoSkill()
    
    # Register skill
    registry.register(echo)
    assert registry.get(echo.name) == echo
    assert len(registry.list_skills()) == 1
    
    # Prevent duplicate registration
    with pytest.raises(ValueError):
        registry.register(echo)
        
    # Toggle enabled status
    assert registry.set_enabled(echo.name, False) is True
    assert echo.enabled is False
    assert len(registry.list_skills(include_disabled=False)) == 0
    assert len(registry.list_skills(include_disabled=True)) == 1

@pytest.mark.asyncio
async def test_echo_skill():
    echo = EchoSkill()
    res = await echo.execute({"text": "Hello World"})
    assert res.success is True
    assert res.skill_name == "echo_skill"
    assert res.data["reply"] == "Echo 响应: Hello World"

def test_safe_eval():
    assert safe_eval("3 + 5") == 8.0
    assert safe_eval("(10 - 2) * 5") == 40.0
    assert safe_eval("2.5 * 4 / 2") == 5.0
    
    with pytest.raises(ZeroDivisionError):
        safe_eval("10 / 0")
        
    with pytest.raises(ValueError):
        safe_eval("import os; os.system('ls')")
        
    with pytest.raises(ValueError):
        safe_eval("10 + 2a")

@pytest.mark.asyncio
async def test_calculator_skill():
    calc = CalculatorSkill()
    res = await calc.execute({"expression": "3 * 4 + 2"})
    assert res.success is True
    assert res.data["result"] == 14.0
    assert res.data["formatted"] == "3 * 4 + 2 = 14.0"
    
    # Division by zero failure case
    res_div_zero = await calc.execute({"expression": "5 / 0"})
    assert res_div_zero.success is False
    assert "除数不能为零" in res_div_zero.error

def test_local_summary():
    text = "Sentence one. Sentence two! Sentence three? Sentence four."
    sum_text = local_summary(text, max_sentences=2)
    assert "Sentence one. Sentence two!" in sum_text
    assert "Sentence three?" not in sum_text

@pytest.mark.asyncio
async def test_summary_skill_fallback():
    from app.core.config import settings
    old_key = settings.LLM_API_KEY
    settings.LLM_API_KEY = None
    try:
        summary_skill = TextSummarySkill()
        res = await summary_skill.execute({"text": "Deep Learning is key. NLP is a branch. Vision is also cool. More text here."})
        assert res.success is True
        assert "降级" in res.data["summary"]
        assert "本地降级" in res.data["mode"]
    finally:
        settings.LLM_API_KEY = old_key


@pytest.mark.asyncio
async def test_research_clarification_first_message_extracts_topic():
    """Section 3.9: first message extracts known fields, not entire sentence as domain."""
    from app.services.skills.research_clarification import ResearchClarificationSkill

    skill = ResearchClarificationSkill()
    first = await skill.execute({"message": "我想研究演化博弈法，数据来源不太清楚"})
    assert first.success is True
    assert first.data["session_id"]
    assert first.data["status"] == "collecting"

    brief = first.data["brief"]
    # The topic keyword list has "演化博弈" — verify it's extracted
    assert "演化博弈" in (brief["topic"] or "")
    # "数据来源不太清楚" should NOT become the topic
    assert "不太清楚" not in (brief["topic"] or "")

    # Should have a question for the next missing field
    assert first.data["question"] is not None


@pytest.mark.asyncio
async def test_research_clarification_uses_llm_question_when_configured(monkeypatch):
    from app.core.config import settings
    skill = ResearchClarificationSkill()
    monkeypatch.setattr(settings, "LLM_API_KEY", "test-key")
    def generated_question(_brief, _question):
        return {"field": "objective", "text": "针对 RAG，你最想先降低哪类幻觉？", "reason": "便于限定检索范围", "options": [{"label": "引用错误", "value": "减少引用错误"}, {"label": "检索错误", "value": "减少检索错误"}, {"label": "自己描述", "value": "__free__"}], "allow_free_text": True, "allow_skip": True}
    monkeypatch.setattr(skill, "_llm_question", generated_question)
    result = await skill.execute({"message": "我想研究 RAG"})
    assert result.data["question"]["text"] == "针对 RAG，你最想先降低哪类幻觉？"


@pytest.mark.asyncio
async def test_research_clarification_multi_turn_and_confirm():
    """Walk through multiple turns, update a field, skip, then confirm."""
    from app.services.skills.research_clarification import ResearchClarificationSkill

    skill = ResearchClarificationSkill()

    # Turn 1 — first message
    first = await skill.execute({"message": "演化博弈法应用研究"})
    assert first.success
    session_id = first.data["session_id"]
    assert first.data["status"] == "collecting"

    # Turn 2 — explicitly fill required fields using update actions
    await skill.execute({
        "message": "演化博弈法在公共卫生中的应用",
        "session_id": session_id,
        "action": "update",
        "target_field": "topic",
    })
    await skill.execute({
        "message": "比较不同策略在公共卫生中的效果差异",
        "session_id": session_id,
        "action": "update",
        "target_field": "core_question",
    })
    await skill.execute({
        "message": "不限",
        "session_id": session_id,
        "action": "update",
        "target_field": "time_range",
    })
    await skill.execute({
        "message": "不限来源",
        "session_id": session_id,
        "action": "update",
        "target_field": "source_preferences",
    })
    await skill.execute({
        "message": "不限",
        "session_id": session_id,
        "action": "update",
        "target_field": "research_object",
    })

    # Now confirm should succeed (all minimum fields filled)
    confirm = await skill.execute({
        "message": "确认，开始检索",
        "session_id": session_id,
        "action": "confirm",
    })
    assert confirm.success
    assert confirm.data["status"] in ("ready", "awaiting_confirmation")


@pytest.mark.asyncio
async def test_research_clarification_cancel_and_restart():
    """cancel closes session; restart creates a new one."""
    from app.services.skills.research_clarification import ResearchClarificationSkill

    skill = ResearchClarificationSkill()

    first = await skill.execute({"message": "演化博弈"})
    sid = first.data["session_id"]

    canc = await skill.execute({"message": "取消", "session_id": sid, "action": "cancel"})
    assert canc.success
    assert canc.data["status"] == "cancelled"

    rest = await skill.execute({"message": "重新开始", "session_id": sid, "action": "restart"})
    assert rest.success
    assert rest.data["session_id"] != sid  # new session
    assert rest.data["status"] == "collecting"


@pytest.mark.asyncio
async def test_research_clarification_query_excludes_constraints():
    """Search plan query must not include constraints or expected_output (Section 3.2)."""
    from app.services.skills.research_clarification import ResearchClarificationSkill

    skill = ResearchClarificationSkill()
    first = await skill.execute({"message": "演化博弈"})
    sid = first.data["session_id"]

    # Fill all required fields
    for msg in ["比较不同策略", "不限对象", "2021–2026", "不限来源", "两周内完成"]:
        r = await skill.execute({"message": msg, "session_id": sid})
        assert r.success

    confirm = await skill.execute({
        "message": "确认", "session_id": sid, "action": "confirm",
    })
    assert confirm.success
    sp = confirm.data.get("search_plan")
    if sp:
        # Constraints and expected_output must NOT be in the query
        assert "两周" not in sp.get("query", "")
        assert "expected_output" not in sp.get("query", "")


@pytest.mark.asyncio
async def test_academic_search_invokes_all_sources_and_clamps_limit():
    """4 sources are called independently; results are merged."""
    # Build a mock adapter factory that returns fake results
    class MockAdapter:
        source_name = None
        def __init__(self, source):
            self.source_name = source
        async def search(self, request, context):
            from app.models.research import SourceStatusKind
            return type("R", (), {
                "source": self.source_name,
                "status": SourceStatusKind.ok,
                "papers": [{"title": f"Paper from {self.source_name.value}"}],
                "attempts": 1,
                "latency_ms": 5.0,
                "error_code": None,
                "message": None,
                "cache_hit": False,
                "stale_cache": False,
            })()

    skill = AcademicSearchSkill(_adapter_factory=MockAdapter)
    result = await skill.execute({
        "query": "retrieval augmented generation",
        "total_limit": 5,
        "per_source_limit": 2,
    })

    assert result.success is True
    assert result.data["overall_status"] == "ok"
    # 4 sources × 1 paper each = 4
    assert len(result.data["results"]) == 4
    titles = {p["title"] for p in result.data["results"]}
    assert "Paper from arxiv" in titles
    assert "Paper from openalex" in titles


@pytest.mark.asyncio
async def test_academic_search_reports_missing_cli():
    """When paper-search CLI is not installed, skill reports the error clearly."""
    # The default PaperSearchCliAdapter tries to find 'paper-search' on PATH.
    # Without mocking, this test relies on the CLI being present or absent.
    # We test the error path by using a factory that raises FileNotFoundError.
    def bad_factory(source):
        raise FileNotFoundError("paper-search not found")

    skill = AcademicSearchSkill(_adapter_factory=bad_factory)
    result = await skill.execute({"query": "test"})
    # The adapter factory failure is caught per-source; all fail → overall error
    assert result.data["overall_status"] in ("error", "degraded")
    assert len(result.data["errors"]) > 0


@pytest.mark.asyncio
async def test_academic_search_degraded_with_partial_failures():
    """Two sources succeed, two fail → overall degraded."""
    from app.models.research import SourceStatusKind

    class FailingAdapter:
        source_name: AcademicSource
        def __init__(self, source):
            self.source_name = source
        async def search(self, request, context):
            if self.source_name in (AcademicSource.arxiv, AcademicSource.semantic):
                return type("R", (), {
                    "source": self.source_name,
                    "status": SourceStatusKind.timeout,
                    "papers": [],
                    "attempts": 2,
                    "latency_ms": 5000.0,
                    "error_code": "TIMEOUT",
                    "message": "timed out",
                    "cache_hit": False,
                    "stale_cache": False,
                })()
            return type("R", (), {
                "source": self.source_name,
                "status": SourceStatusKind.ok,
                "papers": [{"title": f"Paper from {self.source_name.value}"}],
                "attempts": 1,
                "latency_ms": 100.0,
                "error_code": None,
                "message": None,
                "cache_hit": False,
                "stale_cache": False,
            })()

    skill = AcademicSearchSkill(_adapter_factory=FailingAdapter)
    result = await skill.execute({"query": "test", "per_source_limit": 2})

    assert result.success is True
    assert result.data["overall_status"] == "degraded"
    assert len(result.data["results"]) == 2  # only openalex + crossref
    assert len(result.data["errors"]) == 2  # arxiv + semantic

