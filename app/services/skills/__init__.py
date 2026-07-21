from app.services.skills.echo import EchoSkill
from app.services.skills.calculator import CalculatorSkill
from app.services.skills.summary import TextSummarySkill
from app.services.registry import registry

# Instantiate and register the skills
echo_skill = EchoSkill()
calc_skill = CalculatorSkill()
summary_skill = TextSummarySkill()

registry.register(echo_skill)
registry.register(calc_skill)
registry.register(summary_skill)
