import pytest
from app.services.skills.base import SkillResult
from app.services.skills.echo import EchoSkill
from app.services.skills.calculator import CalculatorSkill, safe_eval
from app.services.skills.summary import TextSummarySkill, local_summary
from app.services.registry import SkillRegistry
from app.services.skills.research_clarification import ResearchClarificationSkill

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

