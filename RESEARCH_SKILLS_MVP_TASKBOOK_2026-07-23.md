# 智教码航 Code Navi 科研辅助双 Skill MVP 改造任务书

> 编写日期：2026-07-23  
> 目标仓库：`D:\agent-skill-demo-mvp`  
> 交接对象：负责在现有 FastAPI + 原生 HTML/JS + Pydantic 项目上继续开发的 Agent  
> 文档性质：可执行开发任务书，不是未来完整平台 PRD  
> 参考材料：`RESEARCH_CLIENT_BREADTH_SCAN_2026-07-15.md`，仅借鉴其中与当前双 Skill MVP 直接相关的原则，不要求照搬完整 Research Gap Desk

---

## 0. 给执行 Agent 的强制工作约束

开始修改代码前必须遵守：

1. 完整阅读当前仓库的 `README.md`、全部 Python 文件、`static/index.html`、全部 tests 和本任务书。
2. 当前工作区已有未提交修改。不得使用 `git reset --hard`、`git checkout --`、覆盖式复制或其他会丢失现有修改的操作。
3. 所有新增代码、数据库、缓存、临时文件和文档必须位于 `D:\agent-skill-demo-mvp` 内；禁止在 C 盘创建新文件。
4. 不要把本项目提前改造成最终平台，不做账号、组织、权限、微服务、复杂前端框架迁移或平台接口适配。
5. 本阶段只把现有网页做成一个可靠的 Skill 展示与验证页面，核心开发范围只有：
   - 科研需求确认 Skill；
   - 受约束的信息来源/学术论文检索 Skill；
   - 为使上述两个 Skill 正常工作所必需的路由、Schema、状态、错误处理、前端展示和测试。
6. 不允许全网搜索作为学术检索降级。指定学术源不可用时，应返回部分结果、缓存结果或清晰错误，不能偷偷改成泛网页搜索。
7. 不允许伪造论文、DOI、作者、来源、引用次数或“最新研究”。
8. 不实现自动写论文、自动投稿、自动执行实验、自动宣称研究新颖性、复杂多 Agent 或完整 Zotero 替代品。
9. 外部开源项目只能作为依赖、适配器或设计参考。不得大段复制许可证不明的代码；引入依赖前记录仓库、版本、许可证和用途。
10. 每个阶段修改后必须运行针对性测试；最终必须运行完整测试和手工 smoke test。

---

## 1. 项目目标与本期边界

### 1.1 本期一句话目标

用户先用自然语言描述一个粗略科研需求，Agent 通过多轮、可选择、可修改的追问把需求整理成结构化研究简报；用户确认后，Agent 只在用户批准的学术来源白名单中检索论文，并以可追溯的结构化来源卡片返回结果和各来源状态。

### 1.2 本期必须形成的闭环

```text
用户提出粗略需求
→ 提取已知信息
→ 找出真正缺失的信息
→ 每轮提出一个关键问题并给出选项
→ 用户补充、修改或确认
→ 生成可编辑的 Research Brief 与 Search Plan
→ 用户确认检索
→ 在批准的学术源白名单内检索
→ 标准化、去重、展示论文与来源状态
→ 明确成功、部分失败、缓存命中或完全失败
```

### 1.3 明确不做

- 不实现参考文档中的完整 Evidence、Claim、Gap、Hypothesis 工作台。
- 不解析用户 PDF，不做全文 RAG；这应作为下一阶段独立 Skill。
- 不做论文写作、综述自动生成或“研究结论”生成。
- 不做自动实验、代码执行、数据清洗和复现环境。
- 不迁移 Vue/React，不做最终平台页面。
- 不做用户登录、多租户、RBAC 和云部署。
- 不接入 Google Scholar 爬虫，也不绕过验证码或网站反爬。
- 不抓取知网、万方等未确认授权和接口条款的网站。
- 不因为某个来源失败而扩大到任意网页来源。

---

## 2. 当前代码现状与必须修复的问题

### 2.1 现有两个核心 Skill

当前已有：

- `app/services/skills/research_clarification.py`
- `app/services/skills/academic_search.py`

它们不是从零开始，但都只达到早期原型水平。

### 2.2 ResearchClarificationSkill 当前缺陷

1. 第一条消息整体被写入 `domain`，不会识别一句话中已经包含的研究对象、问题、数据和约束。
2. 后续每句话机械填写下一个字段；用户无法修正上一项。
3. 问题和选项固定，不会根据研究主题变化。
4. 未知 `session_id` 被静默当成新会话，用户不会知道上下文已经丢失。
5. 会话只存在进程内字典，服务重启、reload 或多 worker 后失效。
6. 会话无 TTL、无容量限制、无完成后清理机制。
7. 完成后的会话再次请求会忽略新消息，重复返回旧结果。
8. 生成的检索 query 混入“交付物”等非检索概念。
9. 没有“修改某字段、跳过、返回、取消、重新开始、确认开始检索”操作。
10. 输出没有独立 Pydantic Schema，前端依赖隐式字段。

### 2.3 AcademicSearchSkill 当前缺陷

1. 当前机器未安装 `paper-search`，真实调用不可用，测试只使用了 mock。
2. 四个源虽然已并行，但每次请求会启动四个线程和四个子进程，没有总并发控制。
3. 每源固定 15 秒，无总 deadline、缓存、重试预算、熔断和取消。
4. arXiv、Semantic Scholar 在国内环境下容易超时或 429。
5. `_normalise_results()` 只取列表，不统一字段类型。
6. `authors` 为数组、`published_date` 为整数时，Agent 回复组装可能直接抛异常。
7. 没有按 DOI/标题去重。
8. `limit` 文档说总共返回 1–5 条，实际是每源最多 5 条，总共可返回 20 条。
9. 四源全失败时只保留第一个错误。
10. 部分失败仍只有布尔 `success`，不能表达 `degraded`。
11. 没有显式代理配置和“测试来源”功能。
12. CLI 的 stderr 没有映射为 timeout、rate limit、dependency missing 等错误类别。

### 2.4 Agent 路由当前缺陷

文件：`app/services/agent.py`

1. 规则路由把 `计算`、`/`、`-` 作为数学强特征，会造成以下误路由：
   - `计算机视觉 2024 年论文` → calculator；
   - `请检索 2024-2025 年 RAG 论文` → calculator；
   - `请总结 2024/2025 年的研究进展` → calculator。
2. LLM 路由不接收 `session_id`、会话状态或已缺失字段。
3. session ID 附在请求上时，LLM 可能重新创建会话或错误退出当前流程。
4. 无 LLM 时，文献检索会直接使用整句中文作为 query。
5. LLM timeout、401、429、无效 JSON 等全部静默降级，没有结构化原因。
6. 手动 Skill 参数通过 `if/elif` 硬编码，不支持未来 Skill Schema。
7. disabled Skill 可被手动调用。
8. `skill.execute()` 若意外抛异常，API 直接 500。

### 2.5 API 和前端当前缺陷

1. Skill 不存在、参数错误、依赖缺失等业务错误通常仍返回 HTTP 200。
2. `/api/skills` 返回的是手工拼装类型字符串，不是完整 JSON Schema。
3. 配置只修改进程内 Settings，重启丢失。
4. 前端会把掩码 API Key 再次提交，可能覆盖真实 Key。
5. 学术结果在后端拼为纯文本，前端无法稳定展示论文卡片。
6. loading 只有一个笼统状态。
7. 快捷输入硬编码。
8. sessionStorage 只保存一个 session ID，不保存会话内容。
9. 手机端固定三栏，不可用。
10. 当前“思考过程”实际是路由和执行元数据，应改名为“执行轨迹”，不得暗示公开模型内部思维链。

### 2.6 包结构问题

1. `app/api`、`app/core`、`app/models`、`app/services` 等缺少 `__init__.py`。
2. `skills/__init__.py` 同时承担导入和注册副作用。
3. `registry.py -> skills.base -> skills.__init__ -> registry` 存在真实循环依赖；当前只是特定导入顺序暂时掩盖。

---

## 3. 本期产品设计：Skill A——科研需求确认

### 3.1 Skill 定位

Skill 名称建议保留：

```text
research_clarification_skill
```

它不是普通问卷，也不是把用户的每句话顺序塞进固定字段。它应当是一个受控的研究需求澄清状态机：

- 尽量从当前输入中一次提取多个已知字段；
- 只针对最高价值的缺失信息提一个主要问题；
- 每个问题提供 3–5 个上下文相关选项；
- 始终允许用户自由输入；
- 允许用户修改、跳过、取消和重新开始；
- 信息达到最低完整度后先让用户确认，再进入检索。

### 3.2 Research Brief 字段

新建 `app/models/research.py`，至少定义以下模型：

```python
class ResearchBrief(BaseModel):
    topic: str | None
    objective: str | None
    core_question: str | None
    research_object: str | None
    data_or_materials: str | None
    method_preferences: list[str]
    time_range: YearRange | None
    languages: list[str]
    source_preferences: list[AcademicSource]
    exclusions: list[str]
    constraints: list[str]
    expected_output: str | None
```

字段说明：

- `topic`：研究领域/主题，例如演化博弈、RAG 幻觉。
- `objective`：为什么研究，希望比较、解释、预测还是构建方法。
- `core_question`：最终要回答的主要研究问题。
- `research_object`：研究对象、场景、任务、群体或系统。
- `data_or_materials`：已知数据、种子论文、公开数据集或尚不清楚。
- `method_preferences`：偏好的理论、算法、实验或分析方法。
- `time_range`：检索年份范围。
- `languages`：中文、英文或不限。
- `source_preferences`：允许使用的来源。
- `exclusions`：明确排除项，例如只要期刊、不含预印本。
- `constraints`：时间、算力、预算等，仅用于规划，不直接拼入检索词。
- `expected_output`：论文清单、选题简报、方法对比等；不直接拼入检索词。

### 3.3 最低完成条件

进入检索确认前至少满足：

- `topic` 已明确；
- `objective` 或 `core_question` 至少一个明确；
- `research_object` 已明确，或用户确认“不限定”；
- `time_range` 已明确，或用户确认“不限年份”；
- `source_preferences` 已确认；
- `exclusions` 已确认或显式为空；
- 用户已看过并确认 Search Plan。

`data_or_materials`、`method_preferences`、`constraints` 和 `expected_output` 可以标记为可选，但系统应当根据上下文主动询问其中最有价值的一项。

### 3.4 问题优先级

默认追问顺序不是死顺序，而是优先级：

1. 主题是否明确；
2. 用户到底想回答什么；
3. 范围是否过宽；
4. 研究对象/场景；
5. 论文来源与论文类型；
6. 年份和语言；
7. 数据/方法；
8. 排除项；
9. 输出形式；
10. 最终确认。

如果一句话已经包含多项信息，跳过对应问题。

### 3.5 问题生成双模式

#### 模式 A：配置了 LLM

LLM 只负责：

- 从用户话语提取候选字段；
- 判断哪个缺失字段最值得追问；
- 为该问题生成 3–5 个候选选项；
- 生成简短、可解释的追问理由。

LLM 不负责：

- 生成 session ID；
- 决定完成状态；
- 写数据库；
- 决定是否越过用户确认开始搜索；
- 自行增加来源白名单；
- 自行声称用户需求已经完整。

LLM 输出必须经过严格 Pydantic Schema 校验；失败后降级到规则模式。

#### 模式 B：未配置 LLM

规则模式必须可用，不能把整句依次塞入字段。实现：

1. Unicode NFKC 规范化；
2. 识别年份表达：`近五年`、`2020-2025`、`2018 年以后`；
3. 识别来源词：期刊、会议、预印本、arXiv、Semantic Scholar；
4. 识别约束词：时间、预算、算力、数据不清楚；
5. 删除礼貌和请求模板；
6. 使用确定性关键词提取器得到主题；
7. 使用预定义问题模板和领域通用选项；
8. 置信度不足时明确询问，不擅自填值。

可以增加 `jieba`，但必须锁定版本，并在 `requirements.txt`/`pyproject.toml` 中声明；停用词和自定义词典必须放在 D 盘项目目录。

### 3.6 每轮响应 Schema

```python
class ClarificationTurnOutput(BaseModel):
    session_id: str
    status: Literal[
        "collecting",
        "awaiting_confirmation",
        "ready",
        "completed",
        "cancelled",
        "expired",
    ]
    brief: ResearchBrief
    filled_fields: list[str]
    missing_fields: list[str]
    updated_fields: list[str]
    question: ClarificationQuestion | None
    search_plan: SearchPlan | None
    can_search: bool
    warnings: list[SkillWarning]
```

问题结构：

```python
class ClarificationQuestion(BaseModel):
    field: str
    text: str
    reason: str
    options: list[QuestionOption]
    allow_free_text: bool = True
    allow_skip: bool = True
```

### 3.7 必须支持的控制操作

输入 Schema 增加：

```python
action: Literal[
    "answer",
    "update",
    "skip",
    "confirm",
    "cancel",
    "restart",
] = "answer"
target_field: str | None = None
```

示例：

- “把年份改为 2021 到 2025” → 更新 `time_range`。
- “不要预印本” → 加入 exclusions。
- “先不确定数据来源” → 标记该字段 unknown，而不是把这句话当数据名。
- “重新开始” → 关闭旧会话并创建新会话。
- “确认，开始检索” → 只有此时进入 Academic Search。

### 3.8 会话存储

本期使用 Python 标准库 SQLite，不引入数据库服务器。

建议位置：

```text
D:\agent-skill-demo-mvp\data\code_navi_mvp.db
```

表：

```sql
research_sessions(
    session_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    brief_json TEXT NOT NULL,
    current_field TEXT,
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
)
```

要求：

- 开启 WAL；
- 写入使用事务；
- version 做乐观锁；
- 默认 TTL 24 小时；
- 未知或过期 ID 返回明确错误，不静默创建；
- restart 创建新 ID，保留旧会话 cancelled 状态；
- 不把 API Key 或模型秘密写入会话。

### 3.9 示例对话验收

用户：

```text
我想研究演化博弈法，数据来源不太清楚
```

系统不能直接检索整句，也不能简单把整句写入 domain。合理输出：

```text
已识别：
- 主题：演化博弈法
- 数据/材料：尚未确定

为了缩小方向，你更希望研究哪类问题？
1. 演化博弈模型或求解方法
2. 演化博弈在某个实际场景中的应用
3. 不同演化策略或机制的比较
4. 先查看该领域近年的研究热点
5. 自己输入
```

后续根据用户选择继续询问应用场景、研究对象、年份、论文类型和来源范围；最终显示可编辑的 Research Brief 与 Search Plan。

---

## 4. 本期产品设计：Skill B——受约束学术信息源检索

### 4.1 Skill 定位

保留名称：

```text
academic_search_skill
```

它只负责在明确允许的学术来源中查找和整理候选论文，不负责证明论文正确、不负责自动得出研究结论。

### 4.2 本期来源白名单

默认保留四个来源：

| 来源 | 本期作用 | 注意 |
|---|---|---|
| OpenAlex | 广泛学术元数据、主题和引用关系 | 开放、适合作为主要保底源 |
| Crossref | DOI、期刊、出版元数据核验 | 更适合精确元数据，不应单独决定相关性 |
| Semantic Scholar | 相关性、引用和计算机领域覆盖 | 建议配置 API Key，匿名访问易 429 |
| arXiv | 计算机等领域预印本 | 必须明确标记 preprint，不能伪装成期刊论文 |

来源选择规则：

- 用户说“只要期刊论文”时，默认排除 arXiv-only 结果。
- 用户说“包含预印本”时，允许 arXiv。
- 用户选择来源后，后端还要与服务端 allowlist 求交集。
- 不允许 LLM输出一个未注册来源并直接执行。

后续可选来源，不在本期实现：

- PubMed/Europe PMC：生物医学方向；
- DOAJ：开放获取期刊；
- Unpaywall：开放全文链接；
- Zotero：用户自己的文献库。

### 4.3 开源项目使用决策

#### 本期推荐继续使用

[openags/paper-search-mcp](https://github.com/openags/paper-search-mcp)

原因：

- 与现有 CLI 适配代码一致；
- 同时提供 MCP、CLI 和 Skills；
- 已支持多类论文来源；
- 对 Semantic Scholar API Key、部分来源限流和错误有现成经验。

使用方式：

- 只把它放在 `PaperSearchCliAdapter` 后面；
- 业务 Skill 不得直接依赖 CLI 输出的任意字段；
- 固定并校验安装版本；
- 启动时运行依赖 preflight；
- 不开启 Google Scholar；
- 不启用仓库中仍是 skeleton/未实现的 IEEE、ACM Connector；
- 不把其内部错误字符串直接暴露给最终用户。

#### 本期只借鉴、不整体接入

- [STORM/Co-STORM](https://github.com/stanford-oval/storm)：借鉴“多视角追问”和协作式需求澄清，不接入其全网研究与文章生成流水线。
- [PaperQA2](https://github.com/Future-House/paper-qa)：借鉴元数据、证据片段、重排和引用设计；本期没有 PDF 上传，不整体接入。
- [OpenScholar](https://github.com/AkariAsai/OpenScholar)：借鉴科研检索回答的引用约束；自建语料和检索服务过重，不适合当前网页 MVP。
- [zotero-mcp](https://github.com/54yyyu/zotero-mcp)：适合后续“用户文献库检索/导入导出”，本期不要求用户安装 Zotero。

### 4.4 适配器结构

不要让 `AcademicSearchSkill` 直接拼 subprocess 命令。增加：

```text
app/services/academic/
  __init__.py
  base.py
  paper_search_cli.py
  cache.py
  normalizer.py
  deduplicator.py
  policies.py
```

接口示例：

```python
class AcademicSourceAdapter(Protocol):
    source_name: AcademicSource

    async def search(
        self,
        request: SourceSearchRequest,
        context: SkillContext,
    ) -> SourceSearchResult:
        ...
```

即使本期四个来源都走同一个 CLI，也要在 Skill 层体现为四个独立 source task。

### 4.5 搜索请求 Schema

```python
class AcademicSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=300)
    keywords: list[str] = Field(default_factory=list, max_length=12)
    sources: list[AcademicSource]
    year_from: int | None
    year_to: int | None
    publication_types: list[PublicationType]
    languages: list[str]
    total_limit: int = Field(default=12, ge=1, le=30)
    per_source_limit: int = Field(default=5, ge=1, le=10)
    use_cache: bool = True
```

`query` 必须来自已确认的 Search Plan 或确定性 query extractor，不得直接使用整句聊天文本。

### 4.6 标准 Paper Schema

```python
class PaperRecord(BaseModel):
    paper_id: str
    title: str
    authors: list[str]
    abstract: str | None
    year: int | None
    published_date: str | None
    publication_type: str | None
    venue: str | None
    doi: str | None
    canonical_url: str | None
    pdf_url: str | None
    citation_count: int | None
    source: AcademicSource
    source_id: str | None
    is_preprint: bool
    retrieved_at: str
    raw_metadata: dict[str, Any] | None = None
```

要求：

- 作者无论上游给字符串、列表还是对象，都标准化为 `list[str]`；
- 日期无论为整数、字符串、数组，都转为安全字段；
- URL 只允许 http/https；
- DOI 转小写、去除 `https://doi.org/` 前缀；
- 前端只消费 `PaperRecord`，不消费上游原始字典。

### 4.7 去重规则

按顺序：

1. DOI 相同；
2. source ID 相同；
3. 标准化标题 + 年份相同；
4. 标题高度相似且第一作者一致。

合并时：

- 保存 `matched_sources`；
- 优先保留更完整元数据；
- 不把预印本和正式期刊版本简单当成两个无关结果；
- 若无法确定二者关系，保留两条并标记 `possible_duplicate`。

### 4.8 Timeout、重试、缓存、代理和熔断

整个搜索设置 10 秒总 deadline。每个来源的重试必须受总 deadline 限制。

建议默认策略：

| 来源 | 单次 timeout | 最大尝试次数 | 可重试错误 |
|---|---:|---:|---|
| OpenAlex | 4s | 2 | connect/read timeout、429、5xx |
| Crossref | 4s | 2 | connect/read timeout、429、5xx |
| Semantic Scholar | 5s | 2 | connect/read timeout、429、5xx |
| arXiv | 6s | 2 | connect/read timeout、临时 5xx |

要求：

- 指数退避加 jitter；
- 401、403、参数错误、CLI 不存在不重试；
- 429 优先遵守 Retry-After，但不得突破总 deadline；
- 连续失败达到阈值后短时熔断；
- 总任务超时后取消未完成协程；
- 全局 semaphore 限制同时运行的源任务/子进程；
- 不以“无限重试”解决国内网络问题。

SQLite 缓存表：

```sql
academic_search_cache(
    cache_key TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    query_hash TEXT NOT NULL,
    result_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    adapter_version TEXT NOT NULL
)
```

缓存策略：

- 成功结果 TTL 默认 12 小时；
- 空结果 TTL 5 分钟；
- 失败不做长期缓存；
- 上游失败时允许返回未超过 7 天的 stale cache，并明确标记；
- 相同 query 使用 single-flight，避免重复启动四组子进程；
- 缓存命中目标低于 200ms。

代理配置：

```text
HTTP_PROXY
HTTPS_PROXY
NO_PROXY
ACADEMIC_SEARCH_PROXY
```

子进程使用显式环境变量字典，代理凭据必须脱敏。增加来源连接测试，不能只测试 LLM。

### 4.9 来源状态和整体状态

```python
class SourceStatus(BaseModel):
    source: AcademicSource
    status: Literal[
        "ok",
        "empty",
        "timeout",
        "rate_limited",
        "unavailable",
        "invalid_response",
        "error",
        "cache_hit",
        "stale_cache",
        "circuit_open",
    ]
    result_count: int
    attempts: int
    latency_ms: float
    error_code: str | None
    message: str | None
```

整体状态：

- 所有已选来源成功：`ok`；
- 至少一个来源失败且仍有结果：`degraded`；
- 来源均正常但无结果：`empty`；
- 全部失败且没有缓存：`error`。

外部互联网不可控，因此不得把“四个源永远 10 秒内全部成功”作为验收。应验收“10 秒内明确结束并正确表达部分失败”。

---

## 5. 不依赖 LLM 的检索 Query 提取

新增：

```text
app/services/query_extractor.py
```

输出：

```python
class QueryExtractionResult(BaseModel):
    original_text: str
    normalized_query: str
    keywords: list[str]
    removed_phrases: list[str]
    confidence: float
    needs_clarification: bool
```

处理流程：

1. NFKC 规范化；
2. 提取引号、书名号中的主题；
3. 识别英文缩写、模型名和带连字符技术词；
4. 删除“我想研究、请帮我查、有没有论文、数据来源不太清楚”等请求模板；
5. 中文分词和停用词过滤；
6. 保留 3–8 个高价值术语；
7. 根据领域词典进行有限 query expansion；
8. query 过短、过泛或只有“论文/研究/方法”时返回 `needs_clarification=True`；
9. 禁止在低置信度时退回整句搜索。

必须建立回归语料：

- 普通科研口语；
- 计算机视觉、计算机网络等包含“计算”的词；
- 年份范围；
- 中文/英文混合；
- 不确定表达；
- 真正数学表达式；
- “总结”和“检索”冲突；
- 当前已有科研 session 时的临时其他任务。

---

## 6. Agent 路由与会话协作

### 6.1 路由上下文

新增：

```python
class RouteContext(BaseModel):
    session_id: str | None
    active_workflow: str | None
    workflow_status: str | None
    brief_summary: dict[str, Any] | None
    missing_fields: list[str]
```

LLM 路由必须接收 `RouteContext`，但 session ID 由服务端注入到 Skill 参数，不能相信 LLM 自己生成或回传的 ID。

### 6.2 路由优先级

```text
显式手动指定
→ 显式控制命令（取消/重启/确认）
→ 高置信度完整数学表达式
→ 活动科研工作流的继续/修改
→ LLM 路由（带会话上下文）
→ 评分式规则路由
→ Echo
```

说明：

- “session 永远优先”会劫持真正的临时任务；
- “LLM 永远优先”会丢失状态；
- 正确方式是状态感知路由和显式控制命令。

### 6.3 修复数学误路由

只有当输入整体或明确提取出的片段可以被计算器 parser 完整解析时，才能路由到 calculator。

以下必须不再路由到 calculator：

- `计算机视觉 2024 年论文`
- `请检索 2024-2025 年 RAG 论文`
- `请总结 2024/2025 年的研究进展`
- `2024 年有哪些 Agent 论文`

### 6.4 路由降级可见性

记录但不暴露敏感细节：

```text
LLM_ROUTE_TIMEOUT
LLM_ROUTE_AUTH_FAILED
LLM_ROUTE_INVALID_JSON
LLM_ROUTE_UNSUPPORTED_FORMAT
RULE_ROUTE_LOW_CONFIDENCE
```

响应中的 `route_mode` 使用稳定枚举，而不是中文展示字符串；中文由前端映射。

---

## 7. API 合同

### 7.1 版本

新增 `/api/v1`，旧 `/api/*` 可以在本期兼容保留，但前端迁移到 v1。

### 7.2 统一响应 Envelope

```python
class ApiEnvelope[T](BaseModel):
    schema_version: Literal["1.0"]
    request_id: str
    status: Literal["ok", "degraded", "empty", "error"]
    data: T | None
    error: ApiError | None
    meta: dict[str, Any]
```

错误：

```python
class ApiError(BaseModel):
    code: str
    message: str
    retryable: bool
    details: dict[str, Any] | None
```

### 7.3 本期端点

```text
GET  /api/v1/skills
POST /api/v1/chat
POST /api/v1/skills/{skill_name}/execute
GET  /api/v1/research/sessions/{session_id}
POST /api/v1/research/sessions/{session_id}/cancel
GET  /api/v1/config
PATCH /api/v1/config
POST /api/v1/config/test-llm
POST /api/v1/config/test-academic-sources
GET  /api/v1/health/live
GET  /api/v1/health/ready
```

### 7.4 HTTP 状态

- 404：Skill 或会话不存在；
- 409：Skill disabled、会话版本冲突；
- 413：输入过大；
- 422：参数 Schema 错误；
- 429：应用限流；
- 502：上游返回无效格式；
- 503：CLI/必要依赖不可用；
- 504：整体执行超时；
- 200 + degraded：部分来源失败但仍返回有效结果。

### 7.5 Skill metadata

`/skills` 使用 `input_schema.model_json_schema()` 和 `output_schema.model_json_schema()`，并返回：

```json
{
  "name": "academic_search_skill",
  "version": "3.0.0",
  "display_name": "受约束学术检索",
  "description": "...",
  "examples": [],
  "ui": {
    "renderer": "paper_list",
    "supports_direct_form": true
  }
}
```

---

## 8. 配置持久化（仅做本期需要）

配置重启丢失会直接影响两个 Skill，因此本期需要修复，但不要建设复杂配置中心。

### 8.1 存储

使用同一个 D 盘 SQLite：

```sql
runtime_config(
    config_key TEXT PRIMARY KEY,
    config_value TEXT,
    is_secret INTEGER NOT NULL,
    updated_at TEXT NOT NULL
)
```

`is_secret=1` 的值不能明文落库。可使用 `cryptography.fernet` 加密，主密钥只从 D 盘项目根目录的 `.env` 或启动环境变量读取，不得与密文一起写入数据库；若没有配置主密钥，服务应拒绝通过网页持久化 API Key，并给出明确配置提示，不能静默明文保存。

### 8.2 Key 更新语义

GET 不回传可提交的掩码值，只返回：

```json
{
  "api_key_configured": true,
  "api_key_hint": "sk-1…89ab"
}
```

PATCH 使用：

```json
{
  "api_key_action": "keep",
  "api_key": null
}
```

支持 `keep/replace/clear`，从根源上解决掩码覆盖。

### 8.3 学术源配置

至少支持：

- `PAPER_SEARCH_COMMAND` 或自动发现；
- Semantic Scholar API Key；
- HTTP/HTTPS proxy；
- 各来源 enabled；
- 每源 timeout；
- cache TTL；
- Crossref/OpenAlex polite email。

秘密不得出现在 GET、日志、Inspector 或错误详情中。

---

## 9. 前端改造要求

本期仍使用原生 HTML/JS，不迁移框架。

### 9.1 页面必须展示

1. Skill 列表；
2. 研究需求澄清卡；
3. 当前已确认字段和缺失字段；
4. 当前追问和选项按钮；
5. “自由输入、跳过、修改、取消、重新开始”；
6. Search Plan 预览和“确认检索”；
7. 各学术源实时/最终状态；
8. 论文卡片；
9. 可折叠执行轨迹；
10. Inspector 的结构化视图和“查看原始 JSON”。

### 9.2 状态区分

至少区分：

```text
正在分析需求
等待用户补充
等待用户确认
正在提取关键词
正在检索 OpenAlex
正在检索 Crossref
Semantic Scholar 超时
正在合并与去重
已完成
部分来源失败
```

如果不做 SSE，可先在请求开始/结束展示阶段；推荐实现轻量 SSE 进度，但不是阻塞本期完成的条件。

### 9.3 论文卡片字段

- 标题；
- 作者（最多显示前三位，可展开）；
- 年份；
- venue；
- 来源 badges；
- DOI；
- canonical URL；
- 引用数（若来源提供）；
- preprint 标签；
- cache/stale 标签；
- 摘要折叠；
- “保存到当前候选清单”只做前端状态或会话内状态，不做完整文献管理。

### 9.4 Markdown

使用经过安全清洗的 Markdown renderer。不得直接把未经清洗的 HTML 插入 DOM。若引入前端库：

- 固定版本；
- 优先本地静态文件；
- 配置 CSP；
- 对链接协议做 allowlist。

### 9.5 响应式

- 360px 宽度不得横向溢出；
- 左右栏在小屏变为抽屉或 tabs；
- 输入改为 textarea；
- 所有可点击 Skill/选项使用 button，支持键盘和焦点状态。

---

## 10. 错误分类

新增 `app/core/errors.py`：

```text
VALIDATION_ERROR
SKILL_NOT_FOUND
SKILL_DISABLED
SESSION_NOT_FOUND
SESSION_EXPIRED
SESSION_CONFLICT
LLM_AUTH_FAILED
LLM_TIMEOUT
LLM_INVALID_RESPONSE
ACADEMIC_CLI_MISSING
ACADEMIC_SOURCE_TIMEOUT
ACADEMIC_RATE_LIMITED
ACADEMIC_SOURCE_UNAVAILABLE
ACADEMIC_INVALID_RESPONSE
ACADEMIC_ALL_SOURCES_FAILED
CONFIG_INVALID
CONFIG_TEST_FAILED
INTERNAL_ERROR
```

每个错误至少包含：

- `code`；
- 用户可理解的 message；
- `retryable`；
- HTTP status；
- 可安全展示的 details；
- 日志中的原始异常链。

禁止把完整 stderr、API Key、代理密码、内部路径直接发给浏览器。

---

## 11. 日志和请求追踪

本期最小实现：

1. 使用标准 `logging`，配置 JSON 或稳定 key-value 格式；
2. request ID middleware；
3. `X-Request-ID` 响应头；
4. 路由、Skill、session、来源和耗时均携带 request ID；
5. 学术检索记录每源 attempts、latency、status、result_count；
6. 配置和异常日志脱敏；
7. 关闭 `except Exception: return None` 式静默吞错。

日志默认输出控制台；如果写文件，路径必须在：

```text
D:\agent-skill-demo-mvp\data\logs\
```

---

## 12. 包结构和 Skill 注册

### 12.1 补齐包文件

增加：

```text
app/__init__.py
app/api/__init__.py
app/core/__init__.py
app/models/__init__.py
app/services/__init__.py
tests/__init__.py
```

### 12.2 消除注册副作用

- `skills/__init__.py` 不再实例化并注册所有 Skill；
- 在 `app/services/discovery.py` 实现可信包内发现；
- FastAPI lifespan 中调用一次；
- 只加载 `app.services.skills` 包内、模块自身定义的 `BaseSkill` 子类；
- 重名、无 input/output schema、非法版本时启动失败；
- 测试可传入独立 registry，不依赖全局导入顺序。

不要扫描用户任意目录或执行未知 Python 文件。

---

## 13. 测试任务

### 13.1 Research Clarification

必须覆盖：

1. 首句提取多个字段；
2. 每轮只问一个主要问题；
3. 选项数量和自由输入；
4. 修改已有字段；
5. skip；
6. cancel/restart；
7. 未知 session；
8. 过期 session；
9. 完成确认；
10. query 不包含 expected_output 和 constraints；
11. 服务重启后从 SQLite 恢复；
12. 同一 session 并发更新冲突；
13. LLM 坏 JSON 后规则降级；
14. 没有 API Key 时完整走通。

### 13.2 Query Extractor 与路由

至少建立 50 条 fixture，包含：

```text
我想研究演化博弈法，数据来源不太清楚
计算机视觉 2024 年论文
请检索 2024-2025 年 RAG 论文
请总结 2024/2025 年的研究进展
帮我找近五年关于代码 Agent 评测的英文期刊论文
只要正式发表的论文，不要 arXiv
2 + 2
(12.5 * 4) / 5
```

核心误路由必须为 0。

### 13.3 Academic Search

必须覆盖：

1. 四源成功；
2. 单源 timeout；
3. 两源失败、两源成功；
4. 全部失败；
5. 429 与 Retry-After；
6. 401/403 不重试；
7. CLI missing；
8. CLI 非零退出；
9. 非 JSON stdout；
10. stdout 字段类型差异；
11. authors 为字符串、列表、对象；
12. 日期为整数、字符串、数组；
13. DOI 去重；
14. 标题+年份去重；
15. total_limit；
16. cache hit；
17. stale-if-error；
18. circuit open；
19. global deadline；
20. semaphore 并发限制；
21. proxy 环境变量传递且日志脱敏；
22. only-journal 时排除 arXiv-only。

测试不得真实访问互联网。

### 13.4 API

覆盖：

- HTTP 状态码；
- ApiEnvelope；
- request ID header；
- Skill JSON Schema；
- config keep/replace/clear；
- 连接测试结构；
- degraded response；
- disabled Skill；
- Skill 未捕获异常被统一转换；
- 旧 API 的兼容行为。

### 13.5 前端

最低限度增加：

- 页面 smoke test；
- 关键 DOM 渲染函数测试或 Playwright 测试；
- 论文标题/作者包含 HTML 特殊字符时不产生 XSS；
- 360px viewport 无明显横向溢出；
- source failure 能显示而非只写“请求失败”。

---

## 14. 分阶段实施顺序

### 阶段 0：保护基线

1. 记录 `git status --short`；
2. 运行现有测试；
3. 增加当前可复现 bug 的失败测试；
4. 不先重写前端。

完成标准：

- 能证明误路由、循环依赖、学术字段渲染等问题在修改前存在；
- 现有用户修改未丢失。

### 阶段 1：模型、错误和包结构

1. 增加 `__init__.py`；
2. 消除 registry 循环依赖；
3. 增加研究、论文、错误和统一结果 Schema；
4. SkillResult 改为泛型/结构化结果；
5. 加 request ID 和异常处理。

完成标准：

- `from app.services.registry import SkillRegistry` 可在新进程单独成功；
- 所有 Skill 都有输入输出 Schema；
- 未捕获异常不再造成无结构 500。

### 阶段 2：科研需求确认

1. SQLite session store；
2. 输入字段提取；
3. 动态缺失字段判断；
4. 问题/选项生成；
5. update/skip/confirm/cancel/restart；
6. Search Plan。

完成标准：

- 示例对话在无 LLM 下完整走通；
- 重启服务后 session 可继续；
- 用户能修改任意已填字段；
- 未确认前不能自动检索。

### 阶段 3：路由和 query

1. Query extractor；
2. 状态感知路由；
3. 修复数学误判；
4. LLM RouteContext；
5. 服务端注入 session ID。

完成标准：

- 路由 fixture 全部通过；
- 示例句不再使用整句搜索；
- LLM 失败时原因可追踪且规则模式可用。

### 阶段 4：学术检索可靠性

1. Adapter；
2. preflight；
3. timeout/retry/deadline；
4. concurrency；
5. cache/single-flight/circuit；
6. normalization/dedup；
7. source status；
8. proxy；
9. test source endpoint。

完成标准：

- 任意单源故障不阻断其他源；
- 整体在 10 秒预算内结束；
- 上游任意常见字段格式不导致 500；
- 缓存命中低于 200ms；
- CLI 不存在时明确返回 dependency error。

### 阶段 5：API 和前端

1. `/api/v1`；
2. 配置持久化；
3. 澄清卡和选项交互；
4. Search Plan 确认；
5. 论文卡片；
6. 来源状态；
7. 执行轨迹；
8. Markdown、安全和移动端。

完成标准：

- 用户无需打开 Inspector 即可理解当前缺什么、搜了哪些源、哪些源失败；
- API Key 不被掩码覆盖；
- 手机宽度可完成一次澄清和检索。

### 阶段 6：文档与最终验证

更新：

- `README.md`；
- `.env.example`；
- Skill 开发规范；
- paper-search 安装与检查说明；
- 代理/API Key 配置；
- 真实网络与 mock 测试区别；
- 已知限制。

最终执行：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest -q -p no:cacheprovider
```

同时手工验证：

```text
/
/api/v1/health/live
/api/v1/health/ready
/api/v1/skills
一轮完整科研澄清
确认后学术检索
单源故障展示
配置保存并重启验证
```

---

## 15. 总体验收标准

只有同时满足以下条件才算完成：

1. 用户的粗略需求不会被直接作为整句 query 搜索。
2. 无 LLM API Key 时，需求确认仍可完整运行。
3. Agent 能连续追问、给出选项、接受自由输入和字段修改。
4. 用户确认前不启动学术检索。
5. 检索只执行批准的来源白名单。
6. arXiv 结果明确标记预印本。
7. 各来源成功、空结果、超时、限流、缓存等状态可见。
8. 单源失败不会导致整个请求失败。
9. 总搜索在 10 秒预算内结束。
10. 论文元数据经过 Schema 标准化和去重。
11. 作者/日期等上游字段变化不造成 500。
12. CLI 缺失、网络超时、429、无效 JSON 都有稳定错误码。
13. session 和配置重启后不丢失。
14. API Key 不在前端、Inspector 或日志中泄露。
15. 路由关键 fixture 误判为 0。
16. 新旧测试全部通过，且新增真实故障测试。
17. 页面在桌面和 360px 手机宽度可完成核心流程。
18. 所有新增运行数据位于 D 盘项目目录，没有在 C 盘创建新文件。

---

## 16. 后续可选科研 Skill 排序（本期不要实现）

### 下一优先级 1：论文证据抽取 Skill

```text
paper_evidence_extraction_skill
```

输入用户提供的 PDF，输出带页码/段落定位的：

- 研究问题；
- 方法；
- 数据；
- 主要结果；
- 局限；
- 可核对摘录。

参考 PaperQA2。它比“自动总结论文”更有价值，因为输出能回到原文位置。

### 下一优先级 2：相关工作扩展 Skill

```text
related_work_expansion_skill
```

输入种子论文 DOI，调用 Semantic Scholar/OpenAlex 的 references/citations/related works，输出：

- 前置工作；
- 后续引用；
- 相似论文；
- 去重后的主题簇。

这是比继续扩大关键词源数量更自然的“扩大信息来源”方式。

### 下一优先级 3：引用与论断核验 Skill

```text
claim_citation_check_skill
```

输入一条 claim 和候选论文，检查：

- 论文是否真实存在；
- 引用是否与 claim 相关；
- 当前只能确认摘要还是有全文证据；
- 是否存在明显反证或限制。

不得自动宣称 claim 正确。

### 下一优先级 4：Zotero 文献库 Skill

```text
zotero_library_skill
```

参考 zotero-mcp，实现用户已有文献库的只读搜索、元数据获取和后续导出。首版应只读，写入/删除需要单独授权。

### 下一优先级 5：Benchmark Scout

```text
benchmark_scout_skill
```

面向计算机科研，提取论文中的数据集、指标、baseline、代码仓库和许可证，形成比较表。需要先有稳定的论文元数据和 PDF 证据抽取。

---

## 17. 参考项目与采用结论

| 项目 | 地址 | 当前采用方式 |
|---|---|---|
| paper-search-mcp | https://github.com/openags/paper-search-mcp | 本期 CLI/MCP 学术源适配参考与可固定版本依赖 |
| STORM / Co-STORM | https://github.com/stanford-oval/storm | 借鉴多视角提问、追问和人机共同澄清 |
| PaperQA2 | https://github.com/Future-House/paper-qa | 借鉴元数据、证据、重排、引用；下一阶段候选 |
| OpenScholar | https://github.com/AkariAsai/OpenScholar | 借鉴科学文献检索回答与引用约束，不整体部署 |
| zotero-mcp | https://github.com/54yyyu/zotero-mcp | 后续个人文献库 Skill 候选 |
| OpenAlex Docs | https://github.com/ourresearch/openalex-docs | 来源能力、API 礼貌池和适配参考 |
| Crossref REST API | https://github.com/CrossRef/rest-api-doc | DOI/期刊元数据与 polite User-Agent 规范 |

最终选型原则：

> 本期不追求“Skill 数量多”，而是把需求确认和受约束检索两个 Skill 做到状态清晰、结果可验证、错误可解释、以后可搬迁。下一阶段优先增加“证据抽取”和“引用关系扩展”，而不是增加自动写作或多 Agent 表演。
