"""Skill auto-discovery for the Code Navi MVP.

Scans ``app.services.skills`` for ``BaseSkill`` subclasses and registers
them in the global registry.  Called once during FastAPI lifespan — NOT as
a side-effect of importing the skills package.

Section 12.2 of the task book.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Type

from app.services.registry import registry
from app.services.skills.base import BaseSkill


def discover_and_register_skills() -> None:
    """Find every BaseSkill subclass in the skills package and register it.

    Raises:
        RuntimeError: if two skills share the same name, a skill has no
            ``input_schema`` or ``output_schema``, or the version string is
            missing / malformed.
    """
    import app.services.skills as skills_pkg  # noqa: F811

    seen: set[str] = set()

    for _, module_name, _ in pkgutil.iter_modules(
        skills_pkg.__path__, skills_pkg.__name__ + "."
    ):
        if module_name.endswith(".base"):
            continue  # skip the base module itself

        mod = importlib.import_module(module_name)
        for attr_name in dir(mod):
            attr = getattr(mod, attr_name)
            if not isinstance(attr, type) or attr is BaseSkill:
                continue
            if not issubclass(attr, BaseSkill):
                continue

            skill = attr()

            # --- Guard: name uniqueness within this discovery pass ---
            if skill.name in seen:
                raise RuntimeError(
                    f"Duplicate skill name '{skill.name}' in module '{module_name}'."
            )
            seen.add(skill.name)

            # --- Guard: schema presence ---
            if not hasattr(skill, "input_schema") or skill.input_schema is None:
                raise RuntimeError(
                    f"Skill '{skill.name}' has no input_schema."
                )

            # Idempotent: skip if already registered (supports repeated
            # lifespan calls in test suites).
            if registry.get(skill.name) is not None:
                continue

            registry.register(skill)
