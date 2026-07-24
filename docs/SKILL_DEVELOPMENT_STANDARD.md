# Code Navi Skill 开发规范

## 1. 文件与发现

在 `app/services/skills/` 新建独立模块，定义一个继承 `BaseSkill` 的具体类。启动时会自动发现并注册，禁止在 `skills/__init__.py` 中实例化或注册。Skill 名称必须是稳定、唯一的小写下划线标识；版本使用语义化版本。

## 2. 输入与输出合同

- 输入和输出均定义 Pydantic 模型，设置 `ConfigDict(extra="forbid")`。
- 所有字符串、列表、数字给出合理的长度或范围限制。
- `input_schema` 和 `output_schema` 必须指向对应模型。
- 输出必须可用 `model_dump(mode="json")` 序列化。
- 不在自由文本中隐藏关键结构；列表、状态、警告、来源分别建字段。
- 修改字段含义或删除字段时升级主版本；只新增可选字段升级次版本。

最小骨架：

```python
class ExampleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=5000)

class ExampleOutput(BaseModel):
    value: str
    warnings: list[str] = Field(default_factory=list)

class ExampleSkill(BaseSkill):
    name = "example_skill"
    display_name = "示例 Skill"
    description = "一句能让 Agent 正确路由的能力说明。"
    version = "1.0.0"
    input_schema = ExampleInput
    output_schema = ExampleOutput

    async def execute(self, params: dict[str, Any]) -> SkillResult:
        started = time.perf_counter()
        try:
            request = self.input_schema.model_validate(params)
            output = ExampleOutput(value=request.text)
            return SkillResult(
                success=True,
                skill_name=self.name,
                data=output.model_dump(mode="json"),
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        except ValidationError as exc:
            return SkillResult(
                success=False,
                skill_name=self.name,
                error=f"参数校验失败: {exc}",
                duration_ms=(time.perf_counter() - started) * 1000,
            )
```

## 3. 错误规范

- 参数错误：`VALIDATION_ERROR`，不可重试。
- 缺少 CLI/依赖：`DEPENDENCY_MISSING`，不可重试，提示安装命令。
- 鉴权失败：`AUTH_FAILED`，不可自动重试。
- 网络超时：`UPSTREAM_TIMEOUT`，可重试。
- 限流：`UPSTREAM_RATE_LIMITED`，按上游提示退避。
- 上游格式异常：`UPSTREAM_INVALID_RESPONSE`，不得造成 500。
- 内部异常：由全局处理器转成带 request ID 的 `INTERNAL_ERROR`，日志保留堆栈，响应不泄露密钥。

一个来源失败时保留其他来源的结果，并在结构化状态中报告；禁止伪造数据或把错误字符串当成功结果。

## 4. 外部调用

- 明确单次超时、总截止时间、最大重试次数和可重试错误。
- 401/403、参数错误不重试；timeout、连接失败、429、部分 5xx 才重试。
- 使用并发上限；取消超时任务并等待清理。
- 支持标准 `HTTP_PROXY`、`HTTPS_PROXY`、`NO_PROXY`，日志不得输出代理凭据。
- 缓存键必须包含所有影响结果的参数；允许 stale-if-error 时必须明确标记。

## 5. 前端元数据

Skill 的 `display_name`、`description`、JSON Schema 和示例必须能从 `/api/v1/skills` 获取。需要特殊展示时在 API metadata 中声明 renderer，不能让前端靠猜测自由文本。

## 6. 必备测试

- 正常路径、边界输入、非法输入。
- 未安装依赖、timeout、非零退出、无效 JSON、字段类型漂移。
- 部分失败、全部失败、缓存命中、总截止时间。
- 路由正例和反例。
- v1 Envelope、HTTP 状态码、request ID。
- 前端对 HTML 特殊字符转义。

测试默认不得访问真实互联网。真实连接只通过页面“测试学术源”或人工验收执行。
