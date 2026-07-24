# Code Navi MVP 验收清单

## 自动验收

在项目根目录执行：

```powershell
python -m pip install -r requirements.txt
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest -q -p no:cacheprovider
python scripts/verify_mvp.py
node --check static/app.js
```

预期：全部命令退出码为 0；pytest 不出现失败；脚本最后输出 `PASS`。

## 浏览器验收

1. 执行 `python run.py`，打开 `http://127.0.0.1:8000/`。
2. 输入“我想研究演化博弈法，数据来源不太清楚”。
3. 验证页面逐轮只问一个主要问题，有可点选项，也接受自由输入。
4. 依次补充研究目的、对象、来源、年份和排除项；确认前不得调用学术检索。
5. 点击确认后，页面展示 Search Plan、四个来源状态和论文卡片；单源超时必须显示在对应来源，不能只显示“请求失败”。
6. 在研究会话中输入 `2021-2026`，应更新年份，不能调用计算器；输入完整算式 `2 + 2` 应调用计算器。
7. 刷新页面，当前研究 session ID 应从浏览器会话恢复；重启后端后继续输入，服务端 Brief 应从 SQLite 恢复。
8. 在配置区保存 Base URL、Model 和 API Key，刷新与重启服务；Key 只显示“已配置/提示”，不能回填掩码或明文。
9. 点击“测试模型连接”和“测试学术源”，错误信息应指出是鉴权、依赖、超时或来源失败。
10. 浏览器宽度调至 360px，完成一次需求确认；页面不应产生明显横向滚动。

## 接口抽查

- `GET /api/v1/health/live`：200，`status=ok`。
- `GET /api/v1/health/ready`：200，显示 Skill 数和 CLI 状态。
- `GET /api/v1/skills`：每个 Skill 有 input schema；核心双 Skill 有 output schema。
- 请求头传 `X-Request-ID: demo-001`：响应头和 Envelope 的 request_id 都为 `demo-001`。
- 全部学术源失败：HTTP 503；部分失败：HTTP 200 且 Envelope 状态为 `degraded`。
- 参数无效：HTTP 422；Skill 不存在：HTTP 404；响应都符合 v1 Envelope。

## 学术检索环境说明

安装 CLI：

```powershell
uv tool install paper-search-mcp
paper-search --help
```

国内网络可在启动前设置代理：

```powershell
$env:HTTP_PROXY='http://127.0.0.1:7890'
$env:HTTPS_PROXY='http://127.0.0.1:7890'
python run.py
```

四源真实网络全成功不是离线测试的通过条件；工程验收条件是 10 秒总预算内结束、每源状态清楚、部分失败仍返回可用论文。网络条件允许时，再把“四源均成功”作为部署环境连通性验收。
