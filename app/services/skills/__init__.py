from app.services.skills.echo import EchoSkill
from app.services.skills.calculator import CalculatorSkill
from app.services.skills.summary import TextSummarySkill
from app.services.skills.research_clarification import ResearchClarificationSkill
from app.services.skills.academic_search import AcademicSearchSkill
from app.services.skills.paper_evidence_card import PaperEvidenceCardSkill
from app.services.registry import registry

# Instantiate and register the skills
echo_skill = EchoSkill()
calc_skill = CalculatorSkill()
summary_skill = TextSummarySkill()
research_clarification_skill = ResearchClarificationSkill()
academic_search_skill = AcademicSearchSkill()
paper_evidence_card_skill = PaperEvidenceCardSkill()

registry.register(echo_skill)
registry.register(calc_skill)
registry.register(summary_skill)
registry.register(research_clarification_skill)
registry.register(academic_search_skill)
registry.register(paper_evidence_card_skill)
