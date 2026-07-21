from typing import Dict, List, Optional
from app.services.skills.base import BaseSkill

class SkillRegistry:
    def __init__(self):
        self._skills: Dict[str, BaseSkill] = {}

    def register(self, skill: BaseSkill) -> None:
        """
        Registers a skill. Raises ValueError if already registered.
        """
        if skill.name in self._skills:
            raise ValueError(f"Skill with name '{skill.name}' is already registered.")
        self._skills[skill.name] = skill

    def get(self, name: str) -> Optional[BaseSkill]:
        """
        Retrieves a skill by name.
        """
        return self._skills.get(name)

    def list_skills(self, include_disabled: bool = False) -> List[BaseSkill]:
        """
        Returns lists of registered skills.
        """
        return [
            skill for skill in self._skills.values()
            if include_disabled or skill.enabled
        ]

    def set_enabled(self, name: str, enabled: bool) -> bool:
        """
        Enables or disables a registered skill. Returns True if skill exists and status changed.
        """
        skill = self.get(name)
        if skill:
            skill.enabled = enabled
            return True
        return False

# Global registry instance
registry = SkillRegistry()
