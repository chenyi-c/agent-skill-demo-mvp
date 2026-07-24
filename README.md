# 智教码航 Code Navi — 科研辅助 Skill MVP

这是一个 FastAPI + 原生 HTML/JS + Pydantic 的 AI Agent Skill 演示平台。本期核心闭环是：

1. 用户用自然语言提出粗略科研需求；
2. `research_clarification_skill` 连续追问并生成结构化 Research Brief；
3. 用户确认 Search Plan；
4. `academic_search_skill` 只在 arXiv、Semantic Scholar、OpenAlex、Crossref 四个白名单来源中检索；
5. 页面显示论文卡片、各来源状态和执行轨迹。

没有配置 LLM API Key 时，系统仍可通过确定性规则完成需求确认和 Query 提取，不会把整句聊天原样当检索词。

## 环境要求与启动

- Windows
- Python 3.11+
- 可选：Node.js（只用于检查前端 JavaScript 语法）
- 可选：`paper-search-mcp` CLI（只影响真实学术检索）

```powershell
cd D:\agent-skill-demo-mvp
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run.py
```

访问：

- Web：`http://127.0.0.1:8000/`
- Swagger：`http://127.0.0.1:8000/docs`
- 存活检查：`http://127.0.0.1:8000/api/v1/health/live`
- 就绪检查：`http://127.0.0.1:8000/api/v1/health/ready`

所有运行数据均在项目的 `data/code_navi_mvp.db`，不会主动在 C 盘创建项目文件。

## 核心 Skill

| Skill | 作用 | 当前状态 |
|---|---|---|
| `research_clarification_skill` | 多轮澄清、修改/跳过/取消/重启/确认、生成 Search Plan | 核心 |
| `academic_search_skill` | 四源并发、独立重试、10 秒总预算、缓存、熔断、标准化与去重 | 核心 |
| `summary_skill` | LLM 摘要，失败时本地摘要降级 | 可用 |
| `calculator_skill` | 不使用 `eval` 的安全四则运算 | 可用 |
| `echo_skill` | 路由和 Skill 接口演示 | 可用 |

Skill 由 `app/services/discovery.py` 自动发现。新增规范见
[`docs/SKILL_DEVELOPMENT_STANDARD.md`](docs/SKILL_DEVELOPMENT_STANDARD.md)。

## 学术检索 CLI、代理和可靠性

安装：

```powershell
uv tool install paper-search-mcp
paper-search --help
```

`paper-search` 子进程会继承标准代理变量：

```powershell
$env:HTTP_PROXY='http://127.0.0.1:7890'
$env:HTTPS_PROXY='http://127.0.0.1:7890'
python run.py
```

四个来源并行执行，并采用来源独立 timeout/retry/circuit policy。整体调用受 10 秒截止时间约束；单源失败不会取消其他来源；成功缓存默认 12 小时，空结果缓存 5 分钟，实时失败可返回明确标记的过期缓存。CLI 缺失、鉴权失败、超时、限流和无效输出都会形成结构化来源状态，不会伪造论文。

注意：国内网络下 arXiv 或 Semantic Scholar 是否可达属于部署网络条件。产品正确行为不是无限等待，而是在总预算内给出每源状态并保留其他可用来源结果。

## 模型配置与持久化

页面可设置 OpenAI-compatible Base URL、Model 和 API Key。v1 配置接口采用 `keep / replace / clear` 语义，避免把掩码误存为新 Key。API Key 使用 Fernet 加密后写入 SQLite；主密钥首次保存时生成在项目根目录 `.env`。

可参考 [`.env.example`](.env.example)。远程 Base URL 只允许 HTTPS；HTTP 只允许 `localhost`、`127.0.0.1` 或 `::1`。

不要提交真实 `.env`、数据库或 API Key。丢失 `CODE_NAVI_CONFIG_KEY` 后，已加密的 Key 无法恢复，只能清除并重新保存。

## API v1

主要端点：

- `GET /api/v1/skills`
- `POST /api/v1/chat`
- `POST /api/v1/skills/{skill_name}/execute`
- `GET /api/v1/research/sessions/{session_id}`
- `POST /api/v1/research/sessions/{session_id}/cancel`
- `GET/PATCH /api/v1/config`
- `POST /api/v1/config/test-llm`
- `POST /api/v1/config/test-academic-sources`

v1 统一返回 `schema_version`、`request_id`、`status`、`data`、`error` 和 `meta`。响应头 `X-Request-ID` 与 Envelope 一致。旧 `/api/*` 暂时保留兼容，但新开发应只使用 `/api/v1/*`。

## 测试与验收

离线自动测试不会访问真实互联网：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest -q -p no:cacheprovider
python scripts/verify_mvp.py
node --check static/app.js
```

完整人工步骤和预期结果见
[`ACCEPTANCE_CHECKLIST.md`](ACCEPTANCE_CHECKLIST.md)。

## 已知边界

- 当前前端是便于后续搬迁的原生模块化静态页面，不是最终平台前端。
- 会话保存在本机 SQLite，尚未实现账号级、多设备历史同步。
- CLI 本身对各上游 API 的能力差异仍存在；应用层负责隔离故障、规范结果和透明展示。
- 当前没有部署级鉴权与分布式限流，不能直接暴露到公网；接入最终平台时应复用平台网关、身份认证和审计能力。
