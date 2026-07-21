import time
import re
from typing import Dict, Any
from pydantic import BaseModel, Field
from app.services.skills.base import BaseSkill, SkillResult

class CalculatorInput(BaseModel):
    expression: str = Field(..., description="The math expression to evaluate, e.g. '(3 + 5) * 2'")

def safe_eval(expr: str) -> float:
    # Remove all whitespace
    expr = re.sub(r'\s+', '', expr)
    # Check that it only contains numbers, operators +, -, *, /, and parentheses
    if not re.match(r'^[0-9.+\-*/()]+$', expr):
        raise ValueError("表达式包含非法字符。只允许数字和 +, -, *, /, 以及括弧 ()。")
    
    # Tokenize
    tokens = re.findall(r'[0-9.]+|[+\-*/()]', expr)
    
    # Shunting-yard algorithm
    precedence = {'+': 1, '-': 1, '*': 2, '/': 2}
    output = []
    operators = []
    
    for t in tokens:
        if re.match(r'^[0-9.]+$', t):
            output.append(float(t))
        elif t == '(':
            operators.append(t)
        elif t == ')':
            while operators and operators[-1] != '(':
                output.append(operators.pop())
            if not operators:
                raise ValueError("括弧左右不匹配。")
            operators.pop()  # remove '('
        else:  # Operator
            while operators and operators[-1] in precedence and precedence[operators[-1]] >= precedence[t]:
                output.append(operators.pop())
            operators.append(t)
        
    while operators:
        op = operators.pop()
        if op in '()':
            raise ValueError("括弧左右不匹配。")
        output.append(op)
        
    # Evaluate RPN
    stack = []
    for val in output:
        if isinstance(val, float):
            stack.append(val)
        else:
            if len(stack) < 2:
                raise ValueError("算术表达式结构错误。")
            b = stack.pop()
            a = stack.pop()
            if val == '+':
                stack.append(a + b)
            elif val == '-':
                stack.append(a - b)
            elif val == '*':
                stack.append(a * b)
            elif val == '/':
                if b == 0:
                    raise ZeroDivisionError("除数不能为零。")
                stack.append(a / b)
                
    if len(stack) != 1:
        raise ValueError("算术表达式结构错误。")
    return stack[0]

class CalculatorSkill(BaseSkill):
    name = "calculator_skill"
    display_name = "安全字符计算器"
    description = "使用自定义的逆波兰解析器安全解算数学公式，支持加减乘除与括号，绝对不使用危险的 eval() 执行。"
    version = "1.0.0"
    enabled = True
    input_schema = CalculatorInput

    async def execute(self, params: Dict[str, Any]) -> SkillResult:
        start_time = time.perf_counter()
        try:
            validated = self.input_schema(**params)
            result = safe_eval(validated.expression)
            duration = (time.perf_counter() - start_time) * 1000.0
            return SkillResult(
                success=True,
                skill_name=self.name,
                data={"result": result, "formatted": f"{validated.expression} = {result}"},
                duration_ms=duration
            )
        except Exception as e:
            duration = (time.perf_counter() - start_time) * 1000.0
            return SkillResult(
                success=False,
                skill_name=self.name,
                data=None,
                error=str(e),
                duration_ms=duration
            )
