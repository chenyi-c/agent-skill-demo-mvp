import time
import re
import json
import httpx
from typing import Dict, Any, Tuple, Optional
from pydantic import BaseModel
from app.core.config import settings
from app.services.registry import registry
from app.services.skills.base import SkillResult

class AgentOrchestrator:
    def __init__(self):
        pass

    def _rule_route(self, user_input: str, session_id: Optional[str] = None) -> Tuple[str, Dict[str, Any], str]:
        """
        Rule-based router based on keyword and input analysis.
        Returns: (skill_name, arguments_dict, reason)
        """
        cleaned = user_input.strip()

        # 1. Check for math formulas (simple calculator heuristic)
        math_chars_only = re.sub(r'\s+', '', cleaned)
        if re.match(r'^[0-9.+\-*/()]+$', math_chars_only) and len(math_chars_only) > 1:
            return "calculator_skill", {"expression": cleaned}, "基于规则：检测到纯数学表达式字符。"
        
        # Check for keywords
        math_keywords = ["calculate", "calc", "等于", "计算", "+", "-", "*", "/"]
        if any(kw in cleaned.lower() for kw in math_keywords) and re.search(r'\d', cleaned):
            formula_match = re.search(r'[0-9.+\-*/() ]{3,}', cleaned)
            formula = formula_match.group(0).strip() if formula_match else cleaned
            return "calculator_skill", {"expression": formula}, "基于规则：检测到数学关键字与数字。"

        # 2. Check for summary keywords
        summary_keywords = ["summarize", "summary", "总结", "大纲", "概述", "摘要", "提炼"]
        if any(kw in cleaned.lower() for kw in summary_keywords):
            payload = cleaned
            for kw in summary_keywords:
                payload = re.sub(rf'(?i)\b{kw}\b|{kw}', '', payload)
            payload = payload.strip(":： \n")
            if len(payload) < 5:
                payload = cleaned
            return "summary_skill", {"text": payload, "max_sentences": 3}, "基于规则：检测到文本总结关键字。"

        literature_keywords = ["论文", "文献", "检索", "paper", "literature"]
        if any(keyword in cleaned.lower() for keyword in literature_keywords):
            return "academic_search_skill", {"query": cleaned}, "基于规则：检测到学术文献检索需求。"

        research_keywords = ["研究", "课题", "方向", "科研", "rag"]
        if session_id or any(keyword in cleaned.lower() for keyword in research_keywords):
            return "research_clarification_skill", {"message": cleaned, "session_id": session_id}, "基于规则：检测到科研需求确认。"

        # 3. Default fallback: EchoSkill
        return "echo_skill", {"text": cleaned}, "基于规则：默认缺省分发 (Echo)。"

    async def _llm_route(self, user_input: str) -> Optional[Tuple[str, Dict[str, Any], str]]:
        """
        Model-based router using LLM JSON output to select the skill.
        Returns: (skill_name, arguments_dict, reason) or None if fails.
        """
        if not settings.LLM_API_KEY:
            return None

        # Build list of active skills description
        skills_info = []
        for skill in registry.list_skills(include_disabled=False):
            param_fields = skill.input_schema.model_fields
            params_desc = {
                name: {
                    "type": str(field.annotation), 
                    "description": field.description or "No description"
                }
                for name, field in param_fields.items()
            }
            skills_info.append({
                "name": skill.name,
                "display_name": skill.display_name,
                "description": skill.description,
                "parameters_schema": params_desc
            })

        system_prompt = (
            "You are the Router core of an AI Agent system. Your job is to select the single best Skill "
            "to answer the user's prompt, extract its parameters, and provide your reasoning.\n\n"
            f"Available Skills:\n{json.dumps(skills_info, indent=2)}\n\n"
            "You MUST respond ONLY with a raw JSON object (do not wrap in markdown ```json or block code) containing:\n"
            "{\n"
            '  "skill_name": "the selected skill name",\n'
            '  "arguments": { "argument_name": "extracted_value" },\n'
            '  "reason": "short explanation of why you selected this skill in Chinese"\n'
            "}\n"
            "If no skill is highly relevant, select 'echo_skill'. Keep arguments matches exact types."
        )

        headers = {
            "Authorization": f"Bearer {settings.LLM_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": settings.LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"}
        }

        try:
            url = f"{settings.LLM_BASE_URL}/chat/completions"
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=headers, timeout=8.0)
                if response.status_code != 200:
                    return None
                
                data = response.json()
                content = data["choices"][0]["message"]["content"].strip()
                
                route_decision = json.loads(content)
                skill_name = route_decision.get("skill_name")
                arguments = route_decision.get("arguments", {})
                reason = route_decision.get("reason", "模型自主路由。")
                
                skill = registry.get(skill_name)
                if not skill or not skill.enabled:
                    return None
                
                skill.input_schema(**arguments)
                return skill_name, arguments, f"模型决策: {reason}"
        except Exception as e:
            return None

    async def execute_task(
        self,
        user_input: str,
        preferred_skill: Optional[str] = None,
        session_id: Optional[str] = None,
        force_rule_routing: bool = False,
    ) -> Dict[str, Any]:
        """
        Coordinates the entire flow.
        """
        start_time = time.perf_counter()
        
        skill_name = None
        arguments = {}
        route_reason = ""
        route_mode = "智能路由 (LLM)"
        
        # 1. Routing phase
        if preferred_skill:
            skill_name = preferred_skill
            route_mode = "手动指定"
            route_reason = f"用户手动指定强制运行 Skill: '{preferred_skill}'。"
            if skill_name == "calculator_skill":
                formula_match = re.search(r'[0-9.+\-*/() ]{3,}', user_input)
                formula = formula_match.group(0).strip() if formula_match else user_input
                arguments = {"expression": formula}
            elif skill_name == "summary_skill":
                arguments = {"text": user_input, "max_sentences": 3}
            elif skill_name == "research_clarification_skill":
                arguments = {"message": user_input, "session_id": session_id}
            elif skill_name == "academic_search_skill":
                arguments = {"query": user_input}
            else:
                arguments = {"text": user_input}
        else:
            decision = None
            if force_rule_routing:
                skill_name, arguments, route_reason = self._rule_route(user_input, session_id)
                route_mode = "智能路由 (规则匹配)"
            elif session_id:
                skill_name, arguments, route_reason = self._rule_route(user_input, session_id)
                route_mode = "智能路由 (科研会话恢复)"
            else:
                if settings.LLM_API_KEY:
                    decision = await self._llm_route(user_input)

                if decision:
                    skill_name, arguments, route_reason = decision
                else:
                    skill_name, arguments, route_reason = self._rule_route(user_input, session_id)
                    route_mode = "智能路由 (规则降级 - 开启LLM)" if settings.LLM_API_KEY else "智能路由 (规则匹配)"

        # 2. Validation & Execution phase
        skill = registry.get(skill_name)
        if not skill:
            duration = (time.perf_counter() - start_time) * 1000.0
            return {
                "success": False,
                "reply": f"系统错误: 未找到或已禁用 Skill '{skill_name}'。",
                "route_mode": route_mode,
                "skill_name": skill_name,
                "reason": route_reason,
                "inputs": arguments,
                "outputs": None,
                "duration_ms": duration,
                "error": f"Skill '{skill_name}' not found."
            }

        try:
            skill.input_schema(**arguments)
        except Exception as ve:
            duration = (time.perf_counter() - start_time) * 1000.0
            return {
                "success": False,
                "reply": f"参数校验异常 (Skill '{skill_name}'): {str(ve)}",
                "route_mode": route_mode,
                "skill_name": skill_name,
                "reason": route_reason,
                "inputs": arguments,
                "outputs": None,
                "duration_ms": duration,
                "error": f"Input validation failed: {str(ve)}"
            }

        # Execute
        result: SkillResult = await skill.execute(arguments)
        duration = (time.perf_counter() - start_time) * 1000.0
        
        reply = ""
        if result.success:
            if skill_name == "calculator_skill":
                reply = f"计算结果: {result.data.get('formatted')}"
            elif skill_name == "summary_skill":
                reply = f"智能摘要提炼:\n{result.data.get('summary')}"
            elif skill_name == "academic_search_skill":
                reply = f"已从受限学术源返回 {len(result.data.get('results', []))} 条结果。"
            else:
                reply = result.data.get("reply", str(result.data))
        else:
            reply = f"Skill 执行异常: {result.error}"

        return {
            "success": result.success,
            "reply": reply,
            "route_mode": route_mode,
            "skill_name": skill_name,
            "reason": route_reason,
            "inputs": arguments,
            "outputs": result.data,
            "duration_ms": duration,
            "error": result.error
        }

# Global Orchestrator instance
orchestrator = AgentOrchestrator()
