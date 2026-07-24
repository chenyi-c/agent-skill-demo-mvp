const API = "/api/v1";

const state = {
  sessionId: sessionStorage.getItem("codeNaviResearchSession"),
  skills: [],
  busy: false,
  lastPayload: null,
};

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderMarkdown(text) {
  let html = escapeHtml(text);
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(
    /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
  );
  return html.replace(/\n/g, "<br>");
}

function showToast(message, error = false) {
  const toast = $("toast");
  toast.textContent = message;
  toast.className = `toast${error ? " error" : ""}`;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.add("hidden"), 5500);
}

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`服务返回了无法解析的响应（HTTP ${response.status}）`);
  }
  payload.httpOk = response.ok;
  payload.httpStatus = response.status;
  return payload;
}

function errorMessage(payload) {
  return payload?.error?.message || `请求失败（HTTP ${payload?.httpStatus || "未知"}）`;
}

function setBusy(busy, stage = "等待输入") {
  state.busy = busy;
  $("sendBtn").disabled = busy;
  $("chatInput").disabled = busy;
  $("confirmSearchBtn").disabled = busy;
  $("stageText").textContent = stage;
  $("sendBtn").textContent = busy ? "处理中…" : "发送";
}

function appendMessage(role, text, result = null, isError = false) {
  const article = document.createElement("article");
  article.className = `message ${role}${isError ? " error" : ""}`;

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "你" : "AI";

  const content = document.createElement("div");
  content.className = "message-content";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.innerHTML = renderMarkdown(text);
  content.appendChild(bubble);

  if (result) {
    renderStructuredOutput(content, result);
    const trace = document.createElement("details");
    trace.className = "trace";
    trace.innerHTML = `
      <summary>执行轨迹</summary>
      <div>路由：${escapeHtml(result.route_mode)} · Skill：${escapeHtml(result.skill_name)}</div>
      <div>依据：${escapeHtml(result.reason)}</div>
      <div>耗时：${Number(result.duration_ms || 0).toFixed(1)} ms</div>
    `;
    content.appendChild(trace);
  }

  article.append(avatar, content);
  $("messages").appendChild(article);
  $("messages").scrollTop = $("messages").scrollHeight;
}

function renderStructuredOutput(container, result) {
  const outputs = result.outputs || {};
  if (result.skill_name === "research_clarification_skill") {
    renderResearchCard(container, outputs);
    renderOptions(container, outputs.question);
    updateWorkflow(outputs);
  }
  if (result.skill_name === "academic_search_skill") {
    renderSources(container, outputs.source_statuses || []);
    renderPapers(container, outputs.results || []);
    updateWorkflow(outputs);
  }
}

const FIELD_LABELS = {
  topic: "主题",
  objective: "目标",
  core_question: "核心问题",
  research_object: "研究对象",
  data_or_materials: "数据/材料",
  method_preferences: "方法偏好",
  time_range: "年份",
  languages: "语言",
  source_preferences: "来源",
  exclusions: "排除项",
  constraints: "约束",
  expected_output: "预期输出",
};

function displayValue(value) {
  if (Array.isArray(value)) return value.join("、");
  if (value && typeof value === "object") {
    if (value.unlimited) return "不限";
    return `${value.start || ""}–${value.end || ""}`.replace(/^–|–$/g, "");
  }
  return String(value ?? "");
}

function renderResearchCard(container, outputs) {
  const brief = outputs.brief || {};
  const card = document.createElement("section");
  card.className = "research-card";
  const title = document.createElement("strong");
  title.textContent = `Research Brief · ${outputs.status || "collecting"}`;
  card.appendChild(title);
  const grid = document.createElement("div");
  grid.className = "research-grid";
  Object.entries(brief).forEach(([field, value]) => {
    if (value === null || value === "" || (Array.isArray(value) && !value.length)) return;
    const item = document.createElement("div");
    item.className = "research-field";
    const label = document.createElement("small");
    label.textContent = FIELD_LABELS[field] || field;
    const body = document.createElement("div");
    body.textContent = displayValue(value);
    item.append(label, body);
    grid.appendChild(item);
  });
  card.appendChild(grid);
  container.appendChild(card);
}

function renderOptions(container, question) {
  if (!question?.options?.length) return;
  const options = document.createElement("div");
  options.className = "option-grid";
  question.options.forEach((option) => {
    const button = document.createElement("button");
    button.textContent = option.label || option.value;
    button.addEventListener("click", () => {
      if (option.value === "__free__") {
        $("chatInput").focus();
        $("chatInput").placeholder = `请填写：${question.text}`;
        return;
      }
      sendMessage({ message: option.value, action: "answer" });
    });
    options.appendChild(button);
  });
  container.appendChild(options);
}

function renderSources(container, statuses) {
  if (!statuses.length) return;
  const board = document.createElement("section");
  board.className = "source-board";
  const heading = document.createElement("strong");
  heading.textContent = "学术来源状态";
  board.appendChild(heading);
  const grid = document.createElement("div");
  grid.className = "source-grid";
  statuses.forEach((status) => {
    const item = document.createElement("div");
    item.className = `source-status ${status.status || "error"}`;
    const source = document.createElement("strong");
    source.textContent = status.source || "unknown";
    const detail = document.createElement("div");
    detail.textContent = `${status.status} · ${status.result_count || 0} 篇 · ${Number(status.latency_ms || 0).toFixed(0)} ms`;
    item.append(source, detail);
    if (status.message) {
      const message = document.createElement("small");
      message.textContent = status.message;
      item.appendChild(message);
    }
    grid.appendChild(item);
  });
  board.appendChild(grid);
  container.appendChild(board);
}

function safeUrl(value) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

function renderPapers(container, papers) {
  if (!papers.length) return;
  const list = document.createElement("section");
  list.className = "paper-list";
  papers.forEach((paper) => {
    const card = document.createElement("article");
    card.className = "paper-card";
    const heading = document.createElement("h3");
    const url = safeUrl(paper.canonical_url) || (paper.doi ? `https://doi.org/${paper.doi}` : null);
    if (url) {
      const link = document.createElement("a");
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = paper.title || "无标题";
      heading.appendChild(link);
    } else {
      heading.textContent = paper.title || "无标题";
    }
    const authors = document.createElement("p");
    authors.textContent = (paper.authors || []).slice(0, 5).join("；") || "作者未知";
    const meta = document.createElement("div");
    meta.className = "paper-meta";
    [
      paper.year,
      paper.venue,
      paper.source,
      paper.is_preprint ? "预印本" : null,
      paper.citation_count ? `引用 ${paper.citation_count}` : null,
    ].filter(Boolean).forEach((value) => {
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = value;
      meta.appendChild(tag);
    });
    card.append(heading, authors, meta);
    if (paper.abstract) {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = "查看摘要";
      const abstract = document.createElement("p");
      abstract.textContent = paper.abstract;
      details.append(summary, abstract);
      card.appendChild(details);
    }
    list.appendChild(card);
  });
  container.appendChild(list);
}

function updateWorkflow(outputs) {
  const bar = $("workflowBar");
  const status = outputs.status;
  if (!state.sessionId || status === "completed" || status === "cancelled") {
    bar.classList.add("hidden");
    $("confirmSearchBtn").classList.add("hidden");
    return;
  }
  bar.classList.remove("hidden");
  const missing = outputs.missing_fields || [];
  $("workflowSummary").textContent = missing.length
    ? `当前会话仍需确认：${missing.map((field) => FIELD_LABELS[field] || field).join("、")}`
    : "Research Brief 已达到可检索条件。";
  $("confirmSearchBtn").classList.toggle("hidden", status !== "awaiting_confirmation");
}

function updateInspector(payload, result = null) {
  state.lastPayload = payload;
  $("rawJson").textContent = JSON.stringify(payload, null, 2);
  const panel = $("inspectorStructured");
  panel.replaceChildren();
  if (!result) {
    const empty = document.createElement("p");
    empty.className = "subtle";
    empty.textContent = "暂无执行数据。";
    panel.appendChild(empty);
    return;
  }
  const cards = [
    ["请求状态", payload.status],
    ["路由模式", result.route_mode],
    ["Skill", result.skill_name],
    ["耗时", `${Number(result.duration_ms || 0).toFixed(1)} ms`],
    ["Request ID", payload.request_id],
  ];
  cards.forEach(([label, value]) => {
    const card = document.createElement("div");
    card.className = "inspect-card";
    const title = document.createElement("strong");
    title.textContent = label;
    const body = document.createElement("div");
    body.textContent = value || "—";
    card.append(title, body);
    panel.appendChild(card);
  });
}

function setSession(sessionId, status) {
  state.sessionId = sessionId || null;
  if (state.sessionId && !["completed", "cancelled"].includes(status)) {
    sessionStorage.setItem("codeNaviResearchSession", state.sessionId);
  } else {
    sessionStorage.removeItem("codeNaviResearchSession");
    state.sessionId = null;
  }
}

async function sendMessage({ message, action = null, targetField = null } = {}) {
  if (state.busy) return;
  const input = $("chatInput");
  const text = (message ?? input.value).trim();
  if (!text) return;
  const selectedSkill = $("skillSelect").value || null;
  input.value = "";
  appendMessage("user", text);
  setBusy(true, action === "confirm" ? "正在确认并执行学术检索" : "正在分析需求与选择 Skill");

  try {
    const payload = await api("/chat", {
      method: "POST",
      body: JSON.stringify({
        message: text,
        preferred_skill: selectedSkill,
        session_id: state.sessionId,
        action,
        target_field: targetField,
      }),
    });
    const result = payload.data;
    if (result) {
      const outputs = result.outputs || {};
      setSession(outputs.session_id || state.sessionId, outputs.status);
      appendMessage("assistant", result.reply || errorMessage(payload), result, !result.success);
      updateInspector(payload, result);
    }
    if (!payload.httpOk || payload.status === "error") {
      showToast(errorMessage(payload), true);
      if (!result) appendMessage("assistant", errorMessage(payload), null, true);
    }
  } catch (error) {
    appendMessage("assistant", `接口通信失败：${error.message}`, null, true);
    showToast(error.message, true);
  } finally {
    setBusy(false);
    input.focus();
  }
}

async function loadSkills() {
  const payload = await api("/skills");
  if (!payload.httpOk) throw new Error(errorMessage(payload));
  state.skills = payload.data || [];
  $("skillCount").textContent = state.skills.length;
  const list = $("skillList");
  const select = $("skillSelect");
  list.replaceChildren();
  select.innerHTML = '<option value="">自动路由</option>';
  state.skills.forEach((skill) => {
    const card = document.createElement("button");
    card.className = "skill-card";
    card.innerHTML = `<strong>${escapeHtml(skill.display_name)}</strong><span>${escapeHtml(skill.description)}</span>`;
    card.addEventListener("click", () => {
      select.value = skill.name;
      document.querySelectorAll(".skill-card").forEach((node) => node.classList.remove("active"));
      card.classList.add("active");
    });
    list.appendChild(card);
    const option = document.createElement("option");
    option.value = skill.name;
    option.textContent = skill.display_name;
    select.appendChild(option);
  });
  renderQuickActions();
}

function renderQuickActions() {
  const target = $("quickActions");
  target.replaceChildren();
  state.skills.flatMap((skill) => (skill.examples || []).slice(0, 1).map((text) => ({ skill, text })))
    .slice(0, 5)
    .forEach(({ skill, text }) => {
      const button = document.createElement("button");
      button.textContent = skill.display_name;
      button.title = text;
      button.addEventListener("click", () => {
        $("chatInput").value = text;
        $("chatInput").focus();
      });
      target.appendChild(button);
    });
}

async function loadConfig() {
  const payload = await api("/config");
  if (!payload.httpOk) throw new Error(errorMessage(payload));
  const config = payload.data || {};
  $("cfgApiKey").value = "";
  $("keyHint").textContent = config.api_key_configured ? `（${config.api_key_hint}）` : "（未配置）";
  $("cfgBaseUrl").value = config.base_url || "";
  $("cfgModel").value = config.model || "";
}

async function saveConfig() {
  const key = $("cfgApiKey").value.trim();
  const payload = await api("/config", {
    method: "PATCH",
    body: JSON.stringify({
      api_key_action: key ? "replace" : "keep",
      api_key: key || null,
      base_url: $("cfgBaseUrl").value.trim() || null,
      model: $("cfgModel").value.trim() || null,
    }),
  });
  if (!payload.httpOk) throw new Error(errorMessage(payload));
  $("cfgApiKey").value = "";
  await loadConfig();
  $("configStatus").textContent = "配置已加密持久化。";
  showToast("配置保存成功");
}

async function testEndpoint(path, label) {
  $("configStatus").textContent = `${label}测试中…`;
  const payload = await api(path, { method: "POST", body: "{}" });
  $("rawJson").textContent = JSON.stringify(payload, null, 2);
  if (!payload.httpOk || payload.status === "error") {
    $("configStatus").textContent = errorMessage(payload);
    showToast(errorMessage(payload), true);
    return;
  }
  $("configStatus").textContent = `${label}测试完成：${payload.status}`;
  showToast(`${label}测试完成`);
}

async function checkHealth() {
  const badge = $("healthBadge");
  try {
    const payload = await api("/health/ready");
    const data = payload.data || {};
    badge.className = `health ${payload.status === "ok" ? "ok" : "error"}`;
    badge.innerHTML = `<span></span>${payload.status === "ok" ? "服务就绪" : "服务异常"}`;
    if (!data.academic_search_available) badge.title = "paper-search CLI 未安装，学术检索不可用";
  } catch {
    badge.className = "health error";
    badge.innerHTML = "<span></span>服务离线";
  }
}

$("sendBtn").addEventListener("click", () => sendMessage());
$("chatInput").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
});
$("confirmSearchBtn").addEventListener("click", () =>
  sendMessage({ message: "确认，开始检索", action: "confirm" }),
);
$("restartBtn").addEventListener("click", () =>
  sendMessage({ message: "重新开始", action: "restart" }),
);
$("cancelBtn").addEventListener("click", () =>
  sendMessage({ message: "取消会话", action: "cancel" }),
);
$("saveConfigBtn").addEventListener("click", () =>
  saveConfig().catch((error) => showToast(error.message, true)),
);
$("testLlmBtn").addEventListener("click", () => testEndpoint("/config/test-llm", "模型"));
$("testSourcesBtn").addEventListener("click", () =>
  testEndpoint("/config/test-academic-sources", "学术来源"),
);
$("toggleRawBtn").addEventListener("click", () => {
  $("rawJson").classList.toggle("hidden");
  $("inspectorStructured").classList.toggle("hidden");
});

Promise.all([loadSkills(), loadConfig(), checkHealth()]).catch((error) => {
  showToast(`初始化失败：${error.message}`, true);
});
