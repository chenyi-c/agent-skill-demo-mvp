# 智教码航 - 智能体 Skill 调用与评测演示平台 (Web Demo MVP)

本项目是“智教码航 (Code Navi)”数智化人才培养平台的科研/助研端核心技术演示原型（MVP）。

项目的核心目标是**验证 AI Agent 在对话中进行“意图智能路由分发”并“安全调用自定义技能 (Skills)”的闭环能力**。它为导师和评审专家直观展示了 AI 如何从传统的“满嘴跑火车（学术幻觉）”转变为“基于严谨工具与权威数据源执行任务”的智能体。

---

## 🌟 核心设计亮点

1.  **AI 原生对话入口**：学生无需在死板的菜单表单中跳转，只需在聊天框输入自然语言需求，Agent 自动分发任务。
2.  **前后端与业务解耦**：前端（原生极简网页）、API 接口层（FastAPI）、Agent 决策路由层、Skill 业务实现层完全物理隔离，便于多人协同开发与后期客户端复用。
3.  **双模路由与规则降级**：
    *   **大模型智能路由**：配置 API 后，使用 LLM 自主读取技能描述并输出 JSON 决策。
    *   **规则匹配降级**：无网络或未配置 Key 时，自动降级为本地高吞吐的规则解析器，**确保演示现场 100% 稳定，不崩溃**。
4.  **安全计算沙箱**：计算器技能手写了逆波兰（RPN）表达式解析器，彻底封杀危险的 `eval()` 执行，防范远程命令执行（RCE）风险。

---

## 📦 快速开始与环境安装

### 1. 运行环境要求
*   **Python 3.11 或以上版本**。
*   建议在项目根目录下安装依赖。

### 2. 安装依赖包
在项目根目录运行以下命令安装运行与测试所需的依赖：
```bash
pip install -r requirements.txt
pip install pytest-asyncio
```

### 3. 一键启动服务
在终端内运行以下命令启动本地 Web 服务器：
```bash
python run.py
```
当看到终端显示 `Uvicorn running on http://127.0.0.1:8000` 时，即表明服务启动成功。

### 4. 访问系统
*   **演示网页端（推荐）**：[http://localhost:8000/](http://localhost:8000/) （使用浏览器直接打开）
*   **API 交互式文档 (Swagger UI)**：[http://localhost:8000/docs](http://localhost:8000/docs)
*   **健康检查接口**：[http://localhost:8000/health](http://localhost:8000/health)

---

## 🔑 大模型 API 配置指南（如何在网页端填入 API）

本平台完美兼容 OpenAI API 规范。你可以直接在网页左侧的**【大模型 API 配置】**面板中填入你所购买或申请的 API 服务。

### 推荐配置一：DeepSeek 官方 API（性价比最高，国内直连）
*   **接口秘钥 (API Key)**：粘贴你在 DeepSeek 开放平台申请到的密钥（以 `sk-` 开头）。
*   **接口基础路径 (Base URL)**：`https://api.deepseek.com/v1`
*   **模型名称 (Model)**：`deepseek-chat`

### 推荐配置二：硅基流动 (SiliconFlow) 平台（注册即送大量免费额度）
*   **接口秘钥 (API Key)**：粘贴你注册硅基流动后在个人控制台生成的密钥。
*   **接口基础路径 (Base URL)**：`https://api.siliconflow.cn/v1`
*   **模型名称 (Model)**：`Qwen/Qwen2.5-7B-Instruct` (推荐通义千问)

### 推荐配置三：Ollama 本地部署模型（100% 免费，断网可用）
*   **接口秘钥 (API Key)**：随便填（如 `ollama`），本地不需要鉴权。
*   **接口基础路径 (Base URL)**：`http://localhost:11434/v1`
*   **模型名称 (Model)**：`qwen2.5:7b` (根据你本地 pull 的模型填写)

*填入后点击“保存并应用配置”，后台会自动升级为“智能路由”状态，并加密脱敏显示 Key。*

---

## 🧩 如何新增一个自定义 Skill？

增加新技能采用**零侵入式设计**，你**完全不需要**修改任何 API 路由代码，也不用修改任何前端网页代码。

### 步骤 1：在 `app/services/skills/` 目录下创建技能文件
例如，创建一个翻译技能文件 `translation.py`，继承自 `BaseSkill`，并定义它的 Pydantic 输入参数 Schema：

```python
# app/services/skills/translation.py
import time
from typing import Dict, Any
from pydantic import BaseModel, Field
from app.services.skills.base import BaseSkill, SkillResult

# 1. 定义该 Skill 需要接收的输入参数（系统会自动将其转换为 schema 传给 Agent 决策）
class TranslationInput(BaseModel):
    text: str = Field(..., description="需要翻译的源文本内容")
    target_lang: str = Field(default="英文", description="目标语言，如：英文、中文、日文")

# 2. 编写技能类
class TranslationSkill(BaseSkill):
    name = "translation_skill"                          # 技能唯一ID（小写字母加下划线）
    display_name = "智能翻译器"                        # 网页上展示的名字
    description = "将输入的文本翻译成指定的目标语言。"  # 技能功能描述（Agent根据此描述决定是否调用）
    input_schema = TranslationInput

    async def execute(self, params: Dict[str, Any]) -> SkillResult:
        start_time = time.perf_counter()
        try:
            validated = self.input_schema(**params)
            
            # 这里写你技能的具体业务逻辑，比如调用翻译 API 或规则翻译
            result_text = f"已将 '{validated.text}' 翻译为 {validated.target_lang}"
            
            duration = (time.perf_counter() - start_time) * 1000.0
            return SkillResult(
                success=True,
                skill_name=self.name,
                data={"result": result_text},
                duration_ms=duration
            )
        except Exception as e:
            duration = (time.perf_counter() - start_time) * 1000.0
            return SkillResult(success=False, skill_name=self.name, data=None, error=str(e), duration_ms=duration)
```

### 步骤 2：在技能包注册表里注册该技能
打开 `app/services/skills/__init__.py`，导入你刚写好的技能，并进行实例化与注册：

```python
# app/services/skills/__init__.py
from app.services.skills.translation import TranslationSkill  # 1. 导入
from app.services.registry import registry

# ... 其他技能实例化 ...
translation_skill = TranslationSkill()                        # 2. 实例化

# ... 其他技能注册 ...
registry.register(translation_skill)                          # 3. 注册生效
```

保存文件，重启服务并刷新浏览器。新技能将自动出现在左侧技能库中，并无缝加入 Agent 的智能分发大脑中。

---

## 🧪 运行回归测试

我们提供了基于 `pytest` 的完整自动化单元测试及集成测试用例，运行以下命令即可：
```bash
python -m pytest
```
测试会自动模拟规则分发、计算器除零边界值防御、本地配置降级等 14 项完整场景，确保系统的稳定健壮。

---

## 🔬 科研 Skill 实验台

新增两个可迁移到团队 Agent Kernel 的 Skill：

1. **科研需求确认**：使用浏览器会话 ID 保存五项研究状态（领域、核心问题、数据/方法、约束、交付物），每轮只提出一个带选项的问题；信息完整后生成研究简报和检索词。
2. **受限学术检索**：仅调用 `arxiv`、`semantic`、`openalex`、`crossref` 四个来源，不执行泛网页搜索。单源故障或超时会明确返回错误，不伪造论文结果。

学术检索采用 [openags/paper-search-mcp](https://github.com/openags/paper-search-mcp) 的 CLI 适配层。首次使用前，在已安装 `uv` 的环境执行：

```bash
uv tool install paper-search-mcp
```

未安装 CLI 时，网页会显示安装提示；需求确认 Skill 仍可正常演示。执行测试：

```bash
python -m pytest
```
