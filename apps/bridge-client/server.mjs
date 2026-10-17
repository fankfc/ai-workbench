// Kilo ↔ ZCode 桥客户端（双端可插拔版）
// A 端（推理控制器）：kilo | claude | codex | none（直投）
// B 端（执行器）：zcode-session（队列+ZCode 会话取件）| kilo | claude | codex（无头直执，免轮询）
// 角色与路径配置在 .kilo-bridge/agents.json，可经 /api/agents 或网页选择器热切换。
// 纯逻辑在 lib.mjs（有单元测试）。仅绑定 127.0.0.1。
import { DatabaseSync } from "node:sqlite";
import { createServer } from "node:http";
import {
  existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync, appendFileSync, renameSync, statSync,
} from "node:fs";
import { join } from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import {
  TRIGGER, parseFrontmatter, parseTaskFile, parseResultFile, stripToTask,
  extractKiloReply, extractRefinedTask, validateTaskContent, taskFileName, buildTaskContent,
  delegationPrompt, executionPrompt, headlessResultContent,
  buildContextDigest, summarizeKiloEvent, normalizeThreads, findThread, filterTurnsByThread, DEFAULT_THREAD_ID,
  agentAdapters, normalizeAgentsConfig, DEFAULT_AGENT_PATHS,
} from "./lib.mjs";

const ROOT = "D:\\zcode-workspace\\ai";
const BRIDGE = join(ROOT, ".kilo-bridge");
const QUEUE = join(BRIDGE, "queue");
const PROCESSING = join(BRIDGE, "processing");
const RESULTS = join(BRIDGE, "results");
const DONE = join(BRIDGE, "done");
const AGENTS_JSON = join(BRIDGE, "agents.json");
const KILO_DB = "C:\\Users\\asd15\\.local\\share\\kilo\\kilo.db";
const PORT = 8791;
const POLL_MS = 5000;
const AUTO_INJECT = true;
const QUEUE_STALE_MS = 15 * 60 * 1000;
const PROCESS_STALE_MS = 20 * 60 * 1000;
const VALIDATE_GRACE_MS = 10000;
const EXEC_TIMEOUT_MS = 10 * 60 * 1000;

for (const d of [QUEUE, PROCESSING, RESULTS, DONE]) mkdirSync(d, { recursive: true });

// ---------- 智能体配置 ----------
function loadAgentsConfig() {
  let raw = {};
  try { raw = JSON.parse(readFileSync(AGENTS_JSON, "utf8")); } catch {}
  return normalizeAgentsConfig(raw);
}
let agents = loadAgentsConfig();

// ---------- 项目 / 对话线程 ----------
const THREADS_JSON = join(BRIDGE, "threads.json");
function loadThreads() {
  let raw = {};
  try { raw = JSON.parse(readFileSync(THREADS_JSON, "utf8")); } catch {}
  return normalizeThreads(raw);
}
let threads = loadThreads();
function saveThreads() { writeFileSync(THREADS_JSON, JSON.stringify(threads, null, 2), "utf8"); }

const state = {
  startedAt: new Date().toISOString(),
  lastPoll: null,
  kiloError: null,
  autoInject: AUTO_INJECT,
  injections: 0,
  delegations: [],
  tasks: [],
  events: [],
  agents: { controller: agents.controller, executor: agents.executor },
  threads: [],
};
const enqueuedMsgs = new Set();
const injectedResults = new Set();
let dirty = true;

function logEvent(text) {
  state.events.unshift({ at: new Date().toISOString(), text });
  if (state.events.length > 200) state.events.length = 200;
  dirty = true;
}

// ---------- 桥目录扫描 + 滞留标记 ----------
function scanBridge() {
  const now = Date.now();
  const map = new Map();
  const put = (dir, phase) => {
    for (const f of readdirSync(dir).filter((x) => x.endsWith(".md"))) {
      const p = join(dir, f);
      const { title, fm } = parseTaskFile(p);
      if (fm["source-msg"]) enqueuedMsgs.add(fm["source-msg"]);
      let stale = null;
      try {
        const age = now - statSync(p).mtimeMs;
        if (phase === "排队中" && age > QUEUE_STALE_MS) stale = "排队超时";
        if (phase === "执行中" && age > PROCESS_STALE_MS) stale = "执行超时";
      } catch {}
      map.set(f, {
        file: f, title, phase, stale, from: fm.from || "",
        hasMsg: Boolean(fm["source-msg"]),
        thread: fm.thread || DEFAULT_THREAD_ID,
        sourceSession: fm["source-session"] || null, created: fm.created || null,
      });
    }
  };
  put(QUEUE, "排队中");
  put(PROCESSING, "执行中");
  put(DONE, "已完成");
  for (const r of readdirSync(RESULTS).filter((x) => x.endsWith(".result.md"))) {
    const t = map.get(r.replace(/\.result\.md$/, ""));
    if (!t) continue;
    const res = parseResultFile(join(RESULTS, r));
    Object.assign(t, { resultStatus: res.status, resultSummary: res.summary, completed: res.completed });
    if (injectedResults.has(r)) {
      t.injected = true;
      try {
        const tail = JSON.parse(readFileSync(join(BRIDGE, "inject-log.jsonl"), "utf8")
          .split(/\r?\n/).filter((l) => l.includes(`"result":"${r}"`)).pop());
        t.injectNote = (tail.outputTail || "").replace(/\x1b\[[0-9;]*m/g, "")
          .split(/\r?\n/).filter((x) => x.trim() && !x.startsWith("→") && !x.includes("code ·")).join(" ")
          .slice(-260).trim();
      } catch {}
    }
  }
  state.tasks = [...map.values()].sort((a, b) => (a.created < b.created ? 1 : -1));
  for (const t of state.tasks) {
    const dlg = state.delegations.find((d) => d.taskFile === t.file);
    t.inputText = dlg ? dlg.text : t.title;
    t.inputKind = t.hasMsg ? "Kilo 会话触发"
      : t.sourceSession ? "控制台委派"
        : t.from === "kilo" ? "Kilo 手动入队" : "手动入队";
    if (liveProgress.has(t.file)) t.progress = liveProgress.get(t.file);
  }
  dirty = true;
}

// ---------- 格式校验拒收 ----------
function rejectMalformed() {
  if (agents.executor !== "zcode-session") return; // 无头模式下队首任务立即被执行，无需拒收等待
  for (const f of readdirSync(QUEUE).filter((x) => x.endsWith(".md"))) {
    const p = join(QUEUE, f);
    let raw = "";
    try { raw = readFileSync(p, "utf8"); } catch { continue; }
    try { if (Date.now() - statSync(p).mtimeMs < VALIDATE_GRACE_MS) continue; } catch { continue; }
    const v = validateTaskContent(raw);
    if (v.ok) continue;
    writeFileSync(join(RESULTS, `${f}.result.md`), [
      "---", "status: failed", `completed: ${new Date().toISOString()}`, "---", "",
      `# 结果：（格式拒收）${f}`, "",
      "## 摘要",
      `任务文件未通过协议校验，已被桥客户端自动拒收：${v.reason}。请按 .kilo-bridge/BRIDGE.md 的格式重新投递。`, "",
      "## 变更与产物", "无（任务未执行）。", "",
    ].join("\n"), "utf8");
    renameSync(p, join(DONE, f));
    logEvent(`格式拒收：${f}（${v.reason}）→ 已写失败 result 并归档`);
    dirty = true;
  }
}

// ---------- 心跳 ----------
function heartbeat() {
  writeFileSync(join(BRIDGE, "client-status.json"), JSON.stringify({
    updated: new Date().toISOString(), pid: process.pid, port: PORT,
    uptimeSec: Math.round((Date.now() - Date.parse(state.startedAt)) / 1000),
  }, null, 2));
}

// ---------- Kilo 会话监听（触发词捕获） ----------
let watermark = Date.now();
function pollKilo() {
  let db;
  try {
    db = new DatabaseSync(KILO_DB, { readOnly: true });
    const rows = db.prepare(`
      SELECT p.message_id AS mid, p.session_id AS sid, p.time_created AS tc, p.data AS pdata
      FROM part p JOIN message m ON m.id = p.message_id
      WHERE p.time_created > ? AND json_extract(p.data,'$.type')='text'
        AND json_extract(m.data,'$.role')='user'
      ORDER BY p.time_created ASC`).all(watermark);
    for (const r of rows) {
      if (r.tc > watermark) watermark = r.tc;
      if (enqueuedMsgs.has(r.mid)) continue;
      let text = "";
      try { text = JSON.parse(r.pdata).text || ""; } catch { continue; }
      if (!TRIGGER.test(text)) continue;
      enqueue(stripToTask(text), r.mid, r.sid, "kilo-client");
    }
    state.kiloError = null;
  } catch (e) {
    state.kiloError = String(e.message || e);
  } finally {
    try { db?.close(); } catch {}
  }
  state.lastPoll = new Date().toISOString();
  heartbeat();
}

function enqueue(taskText, msgId, sessionId, from, threadId = DEFAULT_THREAD_ID) {
  const name = taskFileName(taskText, new Date());
  writeFileSync(join(QUEUE, name), buildTaskContent({ taskText, from, msgId, sessionId, threadId }), "utf8");
  if (msgId) enqueuedMsgs.add(msgId);
  logEvent(`已入队 ${name}${sessionId ? `（来源会话 ${sessionId.slice(0, 18)}…）` : ""}`);
  scanBridge();
  return name;
}

// ---------- 结果自动注回（仅支持会话续接的智能体） ----------
const injectBusy = { value: false };
function tryInject() {
  if (!AUTO_INJECT || injectBusy.value) return;
  for (const t of state.tasks) {
    if (!t.resultStatus || t.injected || !t.sourceSession) continue;
    const resultFile = `${t.file}.result.md`;
    if (injectedResults.has(resultFile)) continue;
    const adapter = agentAdapters(agents.paths)[agents.controller];
    if (!adapter || !adapter.canContinue || !existsSync(adapter.path)) continue;
    injectedResults.add(resultFile);
    t.injected = true;
    injectBusy.value = true;
    logEvent(`结果就绪（${t.resultStatus}）→ 注回会话 ${t.sourceSession.slice(0, 18)}…：${t.file}`);
    const msg = `ZCode 已完成任务（结果文件 D:\\zcode-workspace\\ai\\.kilo-bridge\\results\\${resultFile}）。`
      + `请读取该文件，然后向用户汇报其中的 status、摘要与产物路径。`;
    const child = spawn(adapter.path, adapter.argv(msg, t.sourceSession), {
      cwd: ROOT, windowsHide: true, stdio: ["ignore", "pipe", "pipe"],
    });
    let out = "";
    child.stdout?.on("data", (d) => { out += d; });
    child.stderr?.on("data", (d) => { out += d; });
    const fail = (why) => {
      injectBusy.value = false;
      appendFileSync(join(BRIDGE, "inject-log.jsonl"), JSON.stringify({
        at: new Date().toISOString(), result: resultFile, session: t.sourceSession,
        exitCode: -1, outputTail: why.slice(-400),
      }) + "\n");
      logEvent(`注回异常（${why.slice(0, 80)}）：${t.file}`);
      scanBridge();
    };
    child.on("error", (e) => fail(`spawn 失败: ${e.message}`));
    child.on("exit", (code) => {
      if (code === null) return;
      injectBusy.value = false;
      state.injections += 1;
      appendFileSync(join(BRIDGE, "inject-log.jsonl"), JSON.stringify({
        at: new Date().toISOString(), result: resultFile, session: t.sourceSession,
        exitCode: code, outputTail: out.slice(-400).replace(/\x1b\[[0-9;]*m/g, ""),
      }) + "\n");
      logEvent(code === 0 ? `注回完成：${t.file}` : `注回异常（exit ${code}）：${t.file}`);
      scanBridge();
    });
    return;
  }
}

// ---------- 控制台委派：需求 → A 端推理 → 任务书 → 入队 ----------
const delegateBusy = { value: false };
function delegate(requirement, threadId = DEFAULT_THREAD_ID) {
  if (delegateBusy.value) return { ok: false, error: "已有一个委派在推理中，请稍候" };
  const record = { id: `dlg-${Date.now()}`, text: requirement, phase: "推理中", startedAt: new Date().toISOString(), thread: threadId };
  state.delegations.unshift(record);
  if (state.delegations.length > 30) state.delegations.length = 30;
  dirty = true;

  if (agents.controller === "none") {  // A=none：直投，不推理
    const name = enqueue(requirement.replace(TRIGGER, "").trim() || requirement, null, null, "kilo-client", threadId);
    record.phase = "已入队";
    record.taskFile = name;
    logEvent(`控制台直投（A=none）→ ${name}`);
    return { ok: true, id: record.id };
  }

  const adapter = agentAdapters(agents.paths)[agents.controller];
  if (!adapter || !existsSync(adapter.path)) {
    record.phase = "失败";
    record.error = `A 端 ${agents.controller} 不可用（未找到 ${adapter?.path || "?"}）`;
    logEvent(`控制台委派失败：${record.error}`);
    dirty = true;
    return { ok: false, error: record.error };
  }
  delegateBusy.value = true;
  const ft = findThread(threads, threadId);
  const digest = buildContextDigest(filterTurnsByThread([...state.tasks].reverse(), threadId));
  record.withContext = Boolean(digest);
  const continueSession = ft && ft.thread.controllerSession && adapter.canContinue ? ft.thread.controllerSession : null;
  record.continuedSession = Boolean(continueSession);
  logEvent(`控制台委派 → ${adapter.label} 推理中${continueSession ? "（续接该对话的智能体会话）" : digest ? "（含本对话最近多轮背景）" : "（首轮，无背景）"}`);
  const child = spawn(adapter.path, adapter.argv(delegationPrompt(requirement, digest), continueSession), {
    cwd: ROOT, windowsHide: true, stdio: ["ignore", "pipe", "pipe"],
  });
  let raw = "";
  child.stdout?.on("data", (d) => { raw += d; });
  child.stderr?.on("data", (d) => { raw += d; });
  const finish = (phase, extra) => {
    delegateBusy.value = false;
    record.phase = phase;
    Object.assign(record, extra);
    logEvent(`控制台委派 ${record.id}：${phase}${extra?.error ? `（${extra.error.slice(0, 80)}）` : ""}`);
    dirty = true;
  };
  child.on("error", (e) => finish("失败", { error: `无法启动 ${adapter.label}：${e.message}` }));
  child.on("exit", (code) => {
    if (code === null) return;
    if (code !== 0) return finish("失败", { error: `${adapter.label} 退出码 ${code}：${raw.slice(-160).replace(/\s+/g, " ")}` });
    const reply = adapter.parseText(raw);
    const task = extractRefinedTask(reply.text);
    if (!task) return finish("失败", { error: `${adapter.label} 回复中未找到任务书标记` });
    const name = enqueue(task, null, reply.sessionID, "kilo-client", threadId);
    if (ft && reply.sessionID) { ft.thread.controllerSession = reply.sessionID; saveThreads(); }
    finish("已入队", { taskFile: name });
  });
  return { ok: true, id: record.id };
}

// ---------- B 端无头直执（executor ≠ zcode-session 时由客户端直接执行） ----------
const execBusy = { value: false };
const liveProgress = new Map(); // 任务文件名 -> [进度行]，执行中实时更新
const sseClients = new Set();
let sseTimer = null;
function broadcastState() {
  const payload = `data: ${JSON.stringify(state)}\n\n`;
  for (const c of sseClients) try { c.write(payload); } catch {}
}
// 直播期间输出块很密，300ms 合流推送，避免前端被高频全量状态打爆
function pushSseNow() {
  if (sseTimer) return;
  sseTimer = setTimeout(() => { sseTimer = null; broadcastState(); }, 300);
}
function executeHeadless() {
  if (agents.executor === "zcode-session" || execBusy.value) return;
  const adapter = agentAdapters(agents.paths)[agents.executor];
  if (!adapter || !existsSync(adapter.path)) return;
  const f = readdirSync(QUEUE).filter((x) => x.endsWith(".md")).sort()[0];
  if (!f) return;
  execBusy.value = true;
  const startedAt = new Date().toISOString();
  try { renameSync(join(QUEUE, f), join(PROCESSING, f)); } catch { execBusy.value = false; return; }
  liveProgress.set(f, [`启动 ${adapter.label} 无头执行…`]);
  scanBridge();
  logEvent(`${adapter.label} 无头执行开始：${f}`);
  let raw = "";
  let buf = "";
  let ws = ROOT;
  try { const fm = parseFrontmatter(readFileSync(join(PROCESSING, f), "utf8")); if (fm.workspace && existsSync(fm.workspace)) ws = fm.workspace; } catch {}
  const child = spawn(adapter.path, adapter.argv(executionPrompt(readFileSync(join(PROCESSING, f), "utf8")), null, { auto: true }), {
    cwd: ws, windowsHide: true, stdio: ["ignore", "pipe", "pipe"],
  });
  const timer = setTimeout(() => { try { child.kill(); } catch {} }, EXEC_TIMEOUT_MS);
  child.stdout?.on("data", (d) => {
    raw += d;
    buf += d;
    const lines = buf.split(/\r?\n/);
    buf = lines.pop() ?? "";
    let changed = false;
    for (const line of lines) {
      if (!line.trim()) continue;
      let ev = null;
      try { ev = JSON.parse(line); } catch { continue; }
      const s = summarizeKiloEvent(ev);
      if (s) {
        const arr = liveProgress.get(f) || [];
        if (arr[arr.length - 1] !== s) arr.push(s);
        if (arr.length > 12) arr.splice(0, arr.length - 12);
        liveProgress.set(f, arr);
        changed = true;
      }
    }
    if (changed) { scanBridge(); pushSseNow(); }
  });
  child.stderr?.on("data", (d) => { raw += d; });
  child.on("error", (e) => {
    clearTimeout(timer);
    liveProgress.delete(f);
    writeResultAndArchive(f, false, `执行器启动失败：${e.message}`, -1);
  });
  child.on("exit", (code) => {
    if (code === null) return;
    clearTimeout(timer);
    const reply = adapter.parseText(raw);
    const ok = code === 0 && reply.text.trim().length > 0;
    liveProgress.delete(f);
    writeResultAndArchive(f, ok, ok ? reply.text : `执行器退出码 ${code}：${raw.slice(-400).replace(/\s+/g, " ")}`, code);
  });

  function writeResultAndArchive(fileName, ok, text, code) {
    try {
      writeFileSync(join(RESULTS, `${fileName}.result.md`),
        headlessResultContent({ ok, replyText: text, exitCode: code, startedAt, executorLabel: adapter.label }), "utf8");
      renameSync(join(PROCESSING, fileName), join(DONE, fileName));
      logEvent(`${adapter.label} 无头执行${ok ? "完成" : "失败"}：${fileName}（exit ${code}）`);
    } catch (e) { logEvent(`写结果失败 ${fileName}：${e.message}`); }
    execBusy.value = false;
    scanBridge();
    pushSseNow();
  }
}

// ---------- HTTP / SSE（sseClients 与 broadcastState 定义于执行直播一节） ----------
function agentsPayload() {
  const adapters = agentAdapters(agents.paths);
  const avail = {};
  for (const [id, a] of Object.entries(adapters)) avail[id] = { label: a.label, note: a.note, available: existsSync(a.path), canContinue: a.canContinue };
  return {
    current: { controller: agents.controller, executor: agents.executor },
    controllers: ["kilo", "claude", "codex", "none"],
    executors: ["zcode-session", "kilo", "claude", "codex"],
    adapters: avail,
  };
}
const server = createServer((req, res) => {
  const url = new URL(req.url, `http://127.0.0.1:${PORT}`);
  if (req.method === "GET" && (url.pathname === "/" || url.pathname === "/index.html")) {
    res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    res.end(readFileSync(join(fileURLToPath(import.meta.url), "..", "public", "index.html")));
  } else if (req.method === "GET" && url.pathname === "/lib.mjs") {
    res.writeHead(200, { "content-type": "text/javascript; charset=utf-8" });
    res.end(readFileSync(join(fileURLToPath(import.meta.url), "..", "lib.mjs")));
  } else if (req.method === "GET" && url.pathname === "/api/threads") {
    res.writeHead(200, { "content-type": "application/json; charset=utf-8" });
    res.end(JSON.stringify(threads));
  } else if (req.method === "POST" && url.pathname === "/api/threads") {
    let body = "";
    req.on("data", (c) => { body += c; if (body.length > 4096) req.destroy(); });
    req.on("end", () => {
      let b = {};
      try { b = JSON.parse(body); } catch {}
      const name = String(b.name || "").trim().slice(0, 40);
      if (!name) { res.writeHead(400); return res.end('{"ok":false,"error":"name 不能为空"}'); }
      if (b.action === "createProject") {
        threads.projects.push({ id: `prj-${Date.now()}`, name, createdAt: new Date().toISOString(), threads: [] });
      } else if (b.action === "createThread") {
        const proj = threads.projects.find((x) => x.id === b.projectId);
        if (!proj) { res.writeHead(400); return res.end('{"ok":false,"error":"projectId 不存在"}'); }
        proj.threads.push({ id: `thr-${Date.now()}`, name, controllerSession: null, createdAt: new Date().toISOString() });
      } else { res.writeHead(400); return res.end('{"ok":false,"error":"action 无效"}'); }
      saveThreads();
      state.threads = threads.projects;
      logEvent(b.action === "createProject" ? `新建项目「${name}」` : `新建对话「${name}」`);
      dirty = true;
      broadcastState();
      res.writeHead(200, { "content-type": "application/json; charset=utf-8" });
      res.end(JSON.stringify(threads));
    });
  } else if (req.method === "GET" && url.pathname === "/api/state") {
    res.writeHead(200, { "content-type": "application/json; charset=utf-8" });
    res.end(JSON.stringify(state));
  } else if (req.method === "GET" && url.pathname === "/api/agents") {
    res.writeHead(200, { "content-type": "application/json; charset=utf-8" });
    res.end(JSON.stringify(agentsPayload()));
  } else if (req.method === "POST" && url.pathname === "/api/agents") {
    let body = "";
    req.on("data", (c) => { body += c; if (body.length > 4096) req.destroy(); });
    req.on("end", () => {
      let parsed = {};
      try { parsed = JSON.parse(body); } catch {}
      const next = normalizeAgentsConfig({ ...agents, controller: parsed.controller ?? agents.controller, executor: parsed.executor ?? agents.executor });
      agents = next;
      state.agents = { controller: next.controller, executor: next.executor };
      writeFileSync(AGENTS_JSON, JSON.stringify({ controller: next.controller, executor: next.executor, paths: next.paths }, null, 2), "utf8");
      logEvent(`智能体切换：A=${next.controller}，B=${next.executor}（新任务生效）`);
      res.writeHead(200, { "content-type": "application/json; charset=utf-8" });
      res.end(JSON.stringify(agentsPayload()));
      dirty = true;
    });
  } else if (req.method === "POST" && url.pathname === "/api/delegate") {
    let body = "";
    req.on("data", (c) => { body += c; if (body.length > 8192) req.destroy(); });
    req.on("end", () => {
      let text = "";
      let threadId = DEFAULT_THREAD_ID;
      try {
        const b = JSON.parse(body);
        text = (b.text || "").trim();
        if (b.threadId && findThread(threads, String(b.threadId))) threadId = String(b.threadId);
      } catch {}
      if (!text) { res.writeHead(400); return res.end('{"ok":false,"error":"text 不能为空"}'); }
      if (text.length > 2000) { res.writeHead(400); return res.end('{"ok":false,"error":"text 超过 2000 字"}'); }
      const r = delegate(text, threadId);
      res.writeHead(r.ok ? 200 : 409, { "content-type": "application/json; charset=utf-8" });
      res.end(JSON.stringify(r));
    });
  } else if (req.method === "GET" && url.pathname === "/api/events") {
    res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache" });
    res.write(`data: ${JSON.stringify(state)}\n\n`);
    sseClients.add(res);
    req.on("close", () => sseClients.delete(res));
  } else {
    res.writeHead(404); res.end();
  }
});
server.on("error", (e) => {
  if (e.code === "EADDRINUSE") {
    console.error(`端口 ${PORT} 已被占用：先结束旧的桥客户端进程（taskkill /PID <占用者> /F）再启动。`);
    process.exit(1);
  }
  console.error(`服务器错误：${e.message}`);
});
server.listen(PORT, "127.0.0.1", () => {
  logEvent(`桥客户端已启动 http://127.0.0.1:${PORT}（A=${agents.controller}，B=${agents.executor}，注回${AUTO_INJECT ? "开" : "关"}）`);
});
process.on("SIGINT", () => { for (const c of sseClients) try { c.end(); } catch {} server.close(() => process.exit(0)); });

// ---------- 主循环 ----------
setInterval(() => {
  pollKilo();
  rejectMalformed();
  executeHeadless();
  scanBridge();
  tryInject();
  if (dirty) {
    dirty = false;
    const payload = `data: ${JSON.stringify(state)}\n\n`;
    for (const c of sseClients) try { c.write(payload); } catch {}
  }
}, POLL_MS);

// 载入历史注回记录（跨重启去重）
try {
  for (const line of readFileSync(join(BRIDGE, "inject-log.jsonl"), "utf8").split(/\r?\n/).filter(Boolean)) {
    try { injectedResults.add(JSON.parse(line).result); } catch {}
  }
} catch {}
scanBridge();
