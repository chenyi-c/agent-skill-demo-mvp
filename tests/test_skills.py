import pytest
from app.services.skills.base import SkillResult
from app.services.skills.echo import EchoSkill
from app.services.skills.calculator import CalculatorSkill, safe_eval
from app.services.skills.summary import TextSummarySkill, local_summary
from app.services.registry import SkillRegistry

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

