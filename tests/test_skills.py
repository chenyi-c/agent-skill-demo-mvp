import subprocess

import pytest
from app.services.skills.base import SkillResult
from app.services.skills.echo import EchoSkill
from app.services.skills.calculator import CalculatorSkill, safe_eval
from app.services.skills.summary import TextSummarySkill, local_summary
from app.services.registry import SkillRegistry
from app.services.skills.research_clarification import ResearchClarificationSkill
from app.services.skills.academic_search import AcademicSearchSkill
from app.services.skills import academic_search

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
async def test_research_clarification_tracks_one_session_to_completion():
    skill = ResearchClarificationSkill()

    first = await skill.execute({"message": "RAG 幻觉"})
    assert first.success is True
    assert first.data["completed"] is False
    assert first.data["next_field"] == "core_problem"
    assert len(first.data["options"]) == 3

    session_id = first.data["session_id"]
    second = await skill.execute({"message": "希望减少引用错误", "session_id": session_id})
    assert second.data["completed"] is False
    assert second.data["next_field"] == "data_and_method"
    assert len(second.data["options"]) == 3

    third = await skill.execute({"message": "使用公开问答基准和开源模型", "session_id": session_id})
    assert third.data["completed"] is False
    assert third.data["next_field"] == "constraints"
    assert len(third.data["options"]) == 3

    fourth = await skill.execute({"message": "两周内完成，只有一张消费级显卡", "session_id": session_id})
    assert fourth.data["completed"] is False
    assert fourth.data["next_field"] == "expected_output"
    assert len(fourth.data["options"]) == 3

    result = await skill.execute({"message": "研究简报和可运行原型", "session_id": session_id})

    assert result.success is True
    assert result.data["completed"] is True
    assert result.data["research_brief"]["domain"] == "RAG 幻觉"
    assert result.data["research_brief"]["expected_output"] == "研究简报和可运行原型"
    assert "RAG 幻觉" in result.data["query"]


@pytest.mark.asyncio
async def test_research_clarification_collects_a_complete_brief():
    from app.services.skills.research_clarification import ResearchClarificationSkill

    skill = ResearchClarificationSkill()
    first = await skill.execute({"message": "人工智能"})
    assert first.success is True
    assert first.skill_name == "research_clarification_skill"
    assert first.data["completed"] is False
    assert first.data["session_id"]
    assert first.data["question"]
    assert first.data["options"]

    session_id = first.data["session_id"]
    for answer in ("医疗影像辅助诊断", "深度学习模型与公开数据集", "预算有限，三周内完成", "一份可执行的研究方案"):
        result = await skill.execute({"message": answer, "session_id": session_id})

    assert result.data["completed"] is True
    assert result.data["research_brief"] == {
        "domain": "人工智能",
        "core_problem": "医疗影像辅助诊断",
        "data_and_method": "深度学习模型与公开数据集",
        "constraints": "预算有限，三周内完成",
        "expected_output": "一份可执行的研究方案",
    }
    assert "人工智能" in result.data["query"]


@pytest.mark.asyncio
async def test_research_clarification_uses_valid_llm_content(monkeypatch):
    from app.core.config import settings
    skill = ResearchClarificationSkill()
    monkeypatch.setattr(settings, "LLM_API_KEY", "test-key")

    async def llm_content(*_args):
        return {"reply": "已了解你的方向。", "next_question": "你要优先解决什么问题？", "options": ["降低幻觉", "提高准确率", "减少成本"]}

    monkeypatch.setattr(skill, "_call_llm", llm_content)
    result = await skill.execute({"message": "RAG 幻觉"})

    assert result.success is True
    assert result.data["reply"] == "已了解你的方向。"
    assert result.data["options"] == ["降低幻觉", "提高准确率", "减少成本"]


@pytest.mark.asyncio
async def test_research_clarification_falls_back_when_llm_fails(monkeypatch):
    from app.core.config import settings
    skill = ResearchClarificationSkill()
    monkeypatch.setattr(settings, "LLM_API_KEY", "test-key")

    async def failed_llm(*_args):
        return None

    monkeypatch.setattr(skill, "_call_llm", failed_llm)
    result = await skill.execute({"message": "RAG 幻觉"})

    assert result.success is True
    assert result.data["next_question"] == "你最希望解决的具体问题是什么？"


@pytest.mark.asyncio
async def test_research_clarification_uses_llm_suggestion_for_unknown_answer(monkeypatch):
    from app.core.config import settings
    skill = ResearchClarificationSkill()
    monkeypatch.setattr(settings, "LLM_API_KEY", "test-key")

    async def llm_content(_state, _message, _next_field, needs_suggestion):
        if not needs_suggestion:
            return {"reply": "继续完善。", "next_question": "下一项是什么？", "options": ["A", "B", "C"]}
        return {"reply": "建议先用公开 RAG 基准。", "next_question": "你的时间或算力限制是什么？", "options": ["一周", "两周", "一个月"], "suggested_value": "公开 RAG 基准测试集与开源模型"}

    monkeypatch.setattr(skill, "_call_llm", llm_content)
    first = await skill.execute({"message": "RAG"})
    second = await skill.execute({"message": "减少幻觉", "session_id": first.data["session_id"]})
    third = await skill.execute({"message": "我不知道，有什么推荐吗", "session_id": first.data["session_id"]})

    assert second.data["next_field"] == "data_and_method"
    assert third.data["state"]["data_and_method"] == "公开 RAG 基准测试集与开源模型"


@pytest.mark.asyncio
async def test_academic_search_invokes_all_sources_and_clamps_limit():
    captured = []

    def runner(command):
        captured.append(command)
        return '[{"title": "A paper", "source": "arxiv"}]'

    skill = AcademicSearchSkill(command_runner=runner)
    result = await skill.execute({"query": "retrieval augmented generation", "limit": 99})

    assert result.success is True
    assert captured == [[
        "paper-search", "search", "retrieval augmented generation", "-n", "5",
        "-s", "arxiv,semantic,openalex,crossref",
    ]]
    assert result.data["results"] == [{"title": "A paper", "source": "arxiv"}]


@pytest.mark.asyncio
async def test_academic_search_parses_object_results_and_reports_missing_executable():
    skill = AcademicSearchSkill(command_runner=lambda _: '{"results": [{"title": "B paper"}]}')
    result = await skill.execute({"query": "agents", "limit": 0})
    assert result.success is True
    assert result.data["limit"] == 1
    assert result.data["results"] == [{"title": "B paper"}]

    unavailable = AcademicSearchSkill(command_runner=lambda _: (_ for _ in ()).throw(FileNotFoundError()))
    failure = await unavailable.execute({"query": "agents"})
    assert failure.success is False
    assert "install paper-search-mcp" in failure.error.lower()
    assert failure.data is None


@pytest.mark.asyncio
async def test_academic_search_uses_finite_timeout_and_reports_timeout(monkeypatch):
    captured = {}

    def timed_out_run(*args, **kwargs):
        captured.update(kwargs)
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(academic_search.subprocess, "run", timed_out_run)
    result = await AcademicSearchSkill().execute({"query": "slow query"})

    assert captured["timeout"] > 0
    assert result.success is False
    assert "timed out" in result.error.lower()
    assert result.data is None

