// 桥客户端纯逻辑模块（无 Node 依赖：浏览器页面经 /lib.mjs 加载，server 与单测共用）
// 读文件的 parseTaskFile/parseResultFile 在 agent-env.mjs（仅 Node 侧使用）。

export const TRIGGER = /交给\s*z\s*c\s*o\s*d\s*e(?![a-zA-Z0-9])/i;
export const TASK_BEGIN = "===ZCODE-TASK===";
export const TASK_END = "===END-TASK===";

export function parseFrontmatter(text) {
  const out = {};
  const m = String(text).match(/^---\r?\n([\s\S]*?)\r?\n---/);
  if (m) {
    for (const line of m[1].split(/\r?\n/)) {
      const kv = line.match(/^([\w-]+):\s*(.*)$/);
      if (kv) out[kv[1]] = kv[2].trim();
    }
  }
  return out;
}

// 用户消息文本 → 任务正文（剥触发词、引导冒号与包裹引号）
export function stripToTask(text) {
  return String(text).replace(TRIGGER, "")
    .replace(/^[\s：:，,"'「『]+/, "").replace(/[\s"'」』]+$/, "").trim();
}

// kilo --format json 事件流 → { sessionID, text }
export function extractKiloReply(jsonLines) {
  let sessionID = null;
  const parts = new Map();
  for (const line of String(jsonLines).split(/\r?\n/)) {
    if (!line.trim()) continue;
    let ev;
    try { ev = JSON.parse(line); } catch { continue; }
    if (ev.sessionID) sessionID = ev.sessionID;
    if (ev.type === "text" && ev.part && typeof ev.part.text === "string") {
      parts.set(ev.part.id || parts.size, ev.part.text);
    }
  }
  return { sessionID, text: [...parts.values()].join("") };
}

// kilo 推理回复 → 标记之间的任务书全文（找不到返回 null）
export function extractRefinedTask(replyText) {
  const s = String(replyText);
  const i = s.lastIndexOf(TASK_BEGIN);
  const j = s.lastIndexOf(TASK_END);
  if (i === -1 || j === -1 || j <= i) return null;
  return s.slice(i + TASK_BEGIN.length, j).trim() || null;
}

// 任务文件内容校验：返回 {ok, reason}
export function validateTaskContent(raw) {
  if (!String(raw).startsWith("---")) return { ok: false, reason: "缺少 frontmatter（应以 --- 开头）" };
  const fm = parseFrontmatter(raw);
  if (!fm.created) return { ok: false, reason: "frontmatter 缺少 created" };
  if (!/^#\s*任务[：:]/m.test(String(raw))) return { ok: false, reason: "缺少「# 任务：」标题" };
  if (!/##\s*目标/.test(String(raw))) return { ok: false, reason: "缺少「## 目标」小节" };
  return { ok: true, reason: "" };
}

export function taskFileName(taskText, now) {
  const pad = (n) => String(n).padStart(2, "0");
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`
    + `-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  const slug = String(taskText).split(/\r?\n/)[0].slice(0, 24)
    .replace(/[^\w\u4e00-\u9fa5-]+/g, "-").replace(/^-+|-+$/g, "") || "task";
  return `task-${stamp}-${slug}.md`;
}

export function buildTaskContent({ taskText, from = "kilo-client", msgId = null, sessionId = null, workspace = "D:\\zcode-workspace\\ai", threadId = null }) {
  const now = new Date().toISOString();
  const lines = ["---", `from: ${from}`];
  if (threadId) lines.push(`thread: ${threadId}`);
  if (msgId) lines.push(`source-msg: ${msgId}`);
  if (sessionId) lines.push(`source-session: ${sessionId}`);
  lines.push(`workspace: ${workspace}`, `created: ${now}`, "---", "");
  const body = String(taskText).trim();
  if (/^#\s*任务[：:]/m.test(body)) return [...lines, body, ""].join("\n");
  const firstLine = body.split(/\r?\n/)[0];
  const rest = body.split(/\r?\n/).slice(1).join("\n").trim();
  return [...lines, `# 任务：${firstLine}`, "", "## 目标", rest || firstLine, ""].join("\n");
}

// 委派给 A 端的任务书整理提示词（注意：不得包含触发词，避免被自身监听重复入队）
// contextDigest：多轮工作流最近几轮的摘要（首轮为 null）
export function delegationPrompt(requirement, contextDigest = null) {
  const lines = [
    "你是「A 推理 → B 执行」双智能体工作流的任务编排器。请把下面的用户需求推理整理成一份可执行的任务书：",
    "- 补全模糊之处：给出合理默认值并标注「默认」；不要向用户提问。",
    "- 若提供了「多轮背景」，结合背景理解指代（如「刚才那个文件」「上一轮的结果」）。",
    "- 结构固定为：",
    "  # 任务：<一句话标题>",
    "  ## 目标",
    "  <做什么、验收标准（可检查条目）>",
    "  ## 约束与背景",
    "  <工作目录（默认 D:\\zcode-workspace\\ai）、禁改范围、相关文件>",
    "- 你只负责整理任务书，不要执行任务本身。",
    `- 回复的最后必须原样输出两行标记，标记之间放任务书全文：\n${TASK_BEGIN}\n<任务书全文>\n${TASK_END}`,
  ];
  if (contextDigest) lines.push("", "多轮背景（最近轮次，新在最后）：", contextDigest,
    "需要更多历史细节时可读取对应的 results/<任务文件名>.result.md（在工作目录内）。");
  lines.push("", `用户需求：${requirement}`);
  return lines.join("\n");
}

// ---------- 多轮上下文 ----------
export function clip(s, n) {
  s = String(s ?? "").replace(/\s+/g, " ").trim();
  return s.length > n ? s.slice(0, n) + "…" : s;
}

// turns（时间正序）：[{file, inputText, resultStatus, resultSummary}] → 摘要文本（无轮次时 null）
export function buildContextDigest(turns, maxTurns = 3) {
  const recent = (Array.isArray(turns) ? turns : []).filter((t) => t && (t.inputText || t.title)).slice(-maxTurns);
  if (!recent.length) return null;
  return recent.map((t, i) =>
    `第${i + 1}轮 [${t.resultStatus || "未完成"}] 需求：${clip(t.inputText || t.title, 120)}`
    + `｜结果：${clip(t.resultSummary || "（尚无结果）", 160)}（任务文件 ${t.file}）`).join("\n");
}

// ---------- 安全 Markdown 渲染（供聊天气泡展示结果，先全量转义再套有限标签） ----------
export function renderMarkdown(text) {
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const src = String(text ?? "").replace(/\r\n/g, "\n");
  const out = [];
  let inCode = false;
  let codeBuf = [];
  let listOpen = false;
  const closeList = () => { if (listOpen) { out.push("</ul>"); listOpen = false; } };
  for (const line of src.split("\n")) {
    const fence = line.match(/^\s*```/);
    if (fence) {
      if (inCode) { out.push(`<pre><code>${esc(codeBuf.join("\n"))}</code></pre>`); codeBuf = []; inCode = false; }
      else { closeList(); inCode = true; }
      continue;
    }
    if (inCode) { codeBuf.push(line); continue; }
    if (!line.trim()) { closeList(); continue; }
    const li = line.match(/^\s*[-*]\s+(.*)$/);
    if (li) {
      if (!listOpen) { out.push('<ul class="md-ul">'); listOpen = true; }
      out.push(`<li>${inline(esc(li[1]))}</li>`);
      continue;
    }
    closeList();
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) { out.push(`<div class="md-h">${inline(esc(h[2]))}</div>`); continue; }
    out.push(`<div class="md-p">${inline(esc(line))}</div>`);
  }
  if (inCode && codeBuf.length) out.push(`<pre><code>${esc(codeBuf.join("\n"))}</code></pre>`);
  closeList();
  function inline(s) {
    return s
      .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\[ \]/g, "☐").replace(/\[x\]/gi, "☑");
  }
  return out.join("") || `<div class="md-p">${esc(src)}</div>`;
}

// ---------- 项目 / 对话线程 ----------
export const DEFAULT_THREAD_ID = "thr-default";

// threads.json 结构：{projects:[{id,name,createdAt,threads:[{id,name,controllerSession,createdAt}]}]}
export function normalizeThreads(raw) {
  const c = raw && typeof raw === "object" ? raw : {};
  const projects = Array.isArray(c.projects) ? c.projects : [];
  const norm = projects
    .filter((p) => p && typeof p === "object" && p.id && p.name)
    .map((p) => ({
      id: String(p.id), name: String(p.name), createdAt: p.createdAt || new Date().toISOString(),
      threads: (Array.isArray(p.threads) ? p.threads : [])
        .filter((t) => t && t.id && t.name)
        .map((t) => ({
          id: String(t.id), name: String(t.name),
          controllerSession: t.controllerSession || null, createdAt: t.createdAt || new Date().toISOString(),
        })),
    }));
  if (!norm.some((p) => p.threads.length)) {
    const def = norm.find((p) => p.id === "prj-default");
    if (def) def.threads.push({ id: DEFAULT_THREAD_ID, name: "默认对话", controllerSession: null, createdAt: new Date().toISOString() });
    else norm.unshift({ id: "prj-default", name: "默认项目", createdAt: new Date().toISOString(),
      threads: [{ id: DEFAULT_THREAD_ID, name: "默认对话", controllerSession: null, createdAt: new Date().toISOString() }] });
  }
  return { projects: norm };
}

export function findThread(tree, threadId) {
  for (const p of tree.projects) {
    const t = p.threads.find((x) => x.id === threadId);
    if (t) return { project: p, thread: t };
  }
  return null;
}

// 按线程过滤后构造上下文摘要（turns 需带 thread 字段；默认线程包含无 thread 标记的任务）
export function filterTurnsByThread(turns, threadId) {
  const id = threadId || DEFAULT_THREAD_ID;
  return (Array.isArray(turns) ? turns : []).filter((t) => (t.thread || DEFAULT_THREAD_ID) === id);
}

// ---------- 执行过程直播：kilo json 事件 → 一行进度文本 ----------
export function summarizeKiloEvent(ev) {
  if (!ev || typeof ev !== "object") return null;
  const t = String(ev.type || "");
  const p = ev.part && typeof ev.part === "object" ? ev.part : {};
  if (t === "text" && typeof p.text === "string") {
    const s = clip(p.text, 90);
    return s ? `💬 ${s}` : null;
  }
  if (t === "step_start") return "▶ 开始一步";
  if (t === "step_finish") return `◾ 一步完成${p.reason ? `（${clip(p.reason, 40)}）` : ""}`;
  const pt = String(p.type || "");
  if (pt && pt !== "text" && !pt.startsWith("step")) {
    const detail = p.state ? `：${clip(typeof p.state === "string" ? p.state : JSON.stringify(p.state), 60)}` : "";
    return `🔧 ${pt}${detail}`;
  }
  if (t && t !== "text" && !t.startsWith("step")) return `· ${clip(t, 40)}`;
  return null;
}

// ---------- 可插拔智能体适配器（A=推理控制器 / B=执行器） ----------
// 约定：parseText(stdout) -> { sessionID?, text }；canContinue 表示支持会话续接（注回）。
// argv(prompt, sessionId, opts)：opts.auto=true 用于 B 端执行器角色（自主执行需自动批准权限）；
// A 端推理只输出文本，不需要 auto。
export function agentAdapters(paths = {}) {
  return {
    kilo: {
      id: "kilo", label: "Kilo CLI", path: paths.kilo,
      argv: (prompt, sessionId, opts = {}) => [
        "run",
        ...(opts.auto ? ["--auto"] : []),
        ...(sessionId ? ["-s", sessionId] : []),
        "--format", "json",
        prompt,
      ],
      parseText: extractKiloReply,
      canContinue: true,
      note: "Kilo Gateway 账号，已验证可用",
    },
    claude: {
      id: "claude", label: "Claude Code", path: paths.claude,
      argv: (prompt, sessionId, opts = {}) => [
        "-p", prompt, "--output-format", "json",
        ...(opts.auto ? ["--dangerously-skip-permissions"] : []),
        ...(sessionId ? ["--resume", sessionId] : []),
      ],
      parseText: (stdout) => {
        try { const j = JSON.parse(String(stdout)); return { sessionID: j.session_id || null, text: String(j.result || "") }; }
        catch { return { sessionID: null, text: String(stdout) }; }
      },
      canContinue: true,
      note: "已安装 2.1.296；当前未登录，调用会返回认证错误",
    },
    codex: {
      id: "codex", label: "Codex CLI", path: paths.codex,
      argv: (prompt) => ["exec", prompt],
      parseText: (stdout) => ({ sessionID: null, text: String(stdout) }),
      canContinue: false,
      note: "已安装 0.162；无会话续接，输出为纯文本",
    },
  };
}

// 角色取值：controller ∈ kilo|claude|codex|none；executor ∈ zcode-session|kilo|claude|codex
export function normalizeAgentsConfig(raw, adapters = agentAdapters()) {
  const c = raw && typeof raw === "object" ? raw : {};
  const controller = ["kilo", "claude", "codex", "none"].includes(c.controller) ? c.controller : "kilo";
  const executor = ["zcode-session", "kilo", "claude", "codex"].includes(c.executor) ? c.executor : "zcode-session";
  const base = {};
  for (const [id, a] of Object.entries(adapters)) base[id] = a.path;
  const paths = { ...base, ...(c.paths && typeof c.paths === "object" ? c.paths : {}) };
  return { controller, executor, paths };
}

// 执行器提示词：把任务书正文交给 B 端智能体在指定工作区执行
export function executionPrompt(taskRaw) {
  const fm = parseFrontmatter(taskRaw);
  const ws = fm.workspace || "D:\\zcode-workspace\\ai";
  return [
    "请在下面指定的工作目录内完成「任务书」描述的工作，遵守其中全部约束与验收标准。",
    "完成后用中文简要汇报：做了什么、结论、产物或变更的文件路径。不要输出其他内容。",
    `工作目录：${ws}`,
    "",
    "——任务书开始——",
    String(taskRaw).trim(),
    "——任务书结束——",
  ].join("\n");
}

// B 端无头直执的结果文件内容
export function headlessResultContent({ ok, replyText, exitCode, startedAt, executorLabel }) {
  const completed = new Date().toISOString();
  const summary = String(replyText || "").trim().slice(0, 2000) || "（执行器无文本输出）";
  return [
    "---",
    `status: ${ok ? "done" : "failed"}`,
    `completed: ${completed}`,
    `executor: ${executorLabel}`,
    "---",
    "",
    `# 结果：（${executorLabel} 无头执行）`,
    "",
    "## 摘要",
    summary,
    "",
    "## 变更与产物",
    `由 ${executorLabel} 于 ${startedAt} 开始执行，退出码 ${exitCode}；详见其汇报。`,
    "",
  ].join("\n");
}
