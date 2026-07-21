from abc import ABC, abstractmethod
from pydantic import BaseModel, Field
from typing import Any, Dict, Type

class SkillResult(BaseModel):
    success: bool
    skill_name: str
    data: Any
    error: Any = None
    duration_ms: float = 0.0

class BaseSkill(ABC):
    name: str
    display_name: str
    description: str
    version: str = "1.0.0"
    enabled: bool = True
    input_schema: Type[BaseModel]

    @abstractmethod
    async def execute(self, params: Dict[str, Any]) -> SkillResult:
        """
        Executes the skill's logic asynchronously.
        params: a dictionary corresponding to the input_schema.
        """
        pass
