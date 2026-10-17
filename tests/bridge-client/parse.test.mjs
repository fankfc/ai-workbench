// 桥客户端纯逻辑单元测试：node --test tests/bridge-client/
import { test } from "node:test";
import assert from "node:assert/strict";
import { writeFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { sep } from "node:path";
import {
  TRIGGER, parseFrontmatter, stripToTask,
  extractKiloReply, extractRefinedTask, validateTaskContent, taskFileName, buildTaskContent,
  agentAdapters, normalizeAgentsConfig, executionPrompt, headlessResultContent,
  buildContextDigest, summarizeKiloEvent, delegationPrompt,
} from "../../apps/bridge-client/lib.mjs";
import { parseTaskFile, parseResultFile } from "../../apps/bridge-client/agent-env.mjs";

test("触发词匹配容忍大小写与空格", () => {
  assert.ok(TRIGGER.test("交给ZCode：做X"));
  assert.ok(TRIGGER.test("请交给 zcode 处理"));
  assert.ok(!TRIGGER.test("ZCode 任务书整理"));
  assert.ok(!TRIGGER.test("交给ZCoder"));
});

test("parseFrontmatter 提取键值并忽略正文", () => {
  const fm = parseFrontmatter("---\nfrom: kilo\ncreated: 2026-10-16T00:00:00Z\n---\n# 任务：X\n");
  assert.equal(fm.from, "kilo");
  assert.equal(fm.created, "2026-10-16T00:00:00Z");
  assert.deepEqual(parseFrontmatter("无 frontmatter"), {});
});

test("parseTaskFile 提取标题与 frontmatter", () => {
  const dir = mkdtempSync(join(tmpdir(), "bridge-"));
  const p = join(dir, "t.md");
  writeFileSync(p, "---\nsource-session: ses_x\ncreated: 2026-10-16T00:00:00Z\n---\n# 任务：计算 1+1\n\n## 目标\n算出来\n", "utf8");
  const t = parseTaskFile(p);
  assert.equal(t.title, "计算 1+1");
  assert.equal(t.fm["source-session"], "ses_x");
  rmSync(dir, { recursive: true, force: true });
});

test("parseResultFile 提取状态与摘要", () => {
  const dir = mkdtempSync(join(tmpdir(), "bridge-"));
  const p = join(dir, "r.md");
  writeFileSync(p, "---\nstatus: done\ncompleted: 2026-10-16T00:00:00+08:00\n---\n\n# 结果：X\n\n## 摘要\n第一行\n第二行\n\n## 变更与产物\n- f\n", "utf8");
  const r = parseResultFile(p);
  assert.equal(r.status, "done");
  assert.equal(r.summary, "第一行 第二行");
  rmSync(dir, { recursive: true, force: true });
});

test("stripToTask 剥触发词、冒号与包裹引号", () => {
  assert.equal(stripToTask('"交给ZCode：做X"'), "做X");
  assert.equal(stripToTask("交给 zcode，做X"), "做X");
  assert.equal(stripToTask("交给ZCode"), "");
});

test("extractKiloReply 解析 json 事件流", () => {
  const lines = [
    JSON.stringify({ type: "step_start", sessionID: "ses_a", part: { id: "p1" } }),
    JSON.stringify({ type: "text", sessionID: "ses_a", part: { id: "p2", text: "你好" } }),
    "not-json",
    JSON.stringify({ type: "text", sessionID: "ses_a", part: { id: "p3", text: "，世界" } }),
  ].join("\n");
  const r = extractKiloReply(lines);
  assert.equal(r.sessionID, "ses_a");
  assert.equal(r.text, "你好，世界");
});

test("extractRefinedTask 提取标记间任务书", () => {
  const reply = `我先分析一下。\n===ZCODE-TASK===\n# 任务：X\n\n## 目标\nY\n===END-TASK===\n以上。`;
  assert.equal(extractRefinedTask(reply), "# 任务：X\n\n## 目标\nY");
  assert.equal(extractRefinedTask("没有标记"), null);
  assert.equal(extractRefinedTask("===ZCODE-TASK===\n===END-TASK==="), null);
});

test("validateTaskContent 校验协议必备项", () => {
  assert.equal(validateTaskContent("---\ncreated: t\n---\n# 任务：X\n\n## 目标\nY\n").ok, true);
  assert.equal(validateTaskContent("没有 frontmatter").ok, false);
  assert.equal(validateTaskContent("---\n---\n# 任务：X\n\n## 目标\nY\n").ok, false);
  assert.equal(validateTaskContent("---\ncreated: t\n---\n## 目标\nY\n").ok, false);
  assert.equal(validateTaskContent("---\ncreated: t\n---\n# 任务：X\n").ok, false);
});

test("taskFileName 生成规范文件名", () => {
  const now = new Date(2026, 9, 16, 18, 58, 24);
  assert.match(taskFileName("做X事情", now), /^task-20261016-185824-做X事情\.md$/);
  assert.match(taskFileName("a/b\\c * d", now), /^task-20261016-185824-a-b-c-d\.md$/);
});

test("buildTaskContent：已有任务书结构则原样保留", () => {
  const c = buildTaskContent({ taskText: "# 任务：T\n\n## 目标\nG\n\n## 约束与背景\nC", sessionId: "ses_s" });
  assert.match(c, /^---\nfrom: kilo-client\nsource-session: ses_s\nworkspace: D:\\zcode-workspace\\ai\ncreated: [^\n]+\n---\n\n# 任务：T\n\n## 目标\nG\n\n## 约束与背景\nC\n$/);
});

test("buildTaskContent：普通文本包装成目标结构", () => {
  const c = buildTaskContent({ taskText: "做X\n补充说明" });
  assert.match(c, /# 任务：做X\n\n## 目标\n补充说明\n$/);
});

test("agentAdapters 提供三个智能体及其无头 argv", () => {
  const a = agentAdapters();
  assert.deepEqual(a.kilo.argv("做X"), ["run", "--format", "json", "做X"]);
  assert.deepEqual(a.kilo.argv("做X", "ses_s"), ["run", "-s", "ses_s", "--format", "json", "做X"]);
  assert.deepEqual(a.claude.argv("做X"), ["-p", "做X", "--output-format", "json"]);
  assert.deepEqual(a.claude.argv("做X", "ses_s"), ["-p", "做X", "--output-format", "json", "--resume", "ses_s"]);
  assert.deepEqual(a.codex.argv("做X"), ["exec", "做X"]);
  assert.equal(a.kilo.canContinue, true);
  assert.equal(a.codex.canContinue, false);
});

test("agentAdapters.claude.parseText 解析 Claude Code JSON 输出", () => {
  const a = agentAdapters();
  const r = a.claude.parseText(JSON.stringify({ session_id: "ses_c", result: "答案文本" }));
  assert.equal(r.sessionID, "ses_c");
  assert.equal(r.text, "答案文本");
  assert.deepEqual(a.claude.parseText("非JSON输出"), { sessionID: null, text: "非JSON输出" });
});

test("normalizeAgentsConfig 校验与默认值", () => {
  assert.deepEqual(normalizeAgentsConfig(null), { controller: "kilo", executor: "zcode-session", paths: normalizeAgentsConfig({}).paths });
  const bad = normalizeAgentsConfig({ controller: "gpt99", executor: "whatever" });
  assert.equal(bad.controller, "kilo");
  assert.equal(bad.executor, "zcode-session");
  const good = normalizeAgentsConfig({ controller: "none", executor: "codex", paths: { kilo: "X:\k.exe" } });
  assert.equal(good.controller, "none");
  assert.equal(good.executor, "codex");
  assert.equal(good.paths.kilo, "X:\k.exe");
});

test("executionPrompt 携带任务书与工作目录", () => {
  const p = executionPrompt("---\nworkspace: D:\demo\ncreated: t\n---\n# 任务：X\n\n## 目标\nY");
  assert.ok(p.includes("工作目录：D:\demo"));
  assert.ok(p.includes("# 任务：X"));
  assert.ok(p.includes("任务书开始"));
});

test("headlessResultContent 生成协议结果文件", () => {
  const c = headlessResultContent({ ok: true, replyText: "完成了", exitCode: 0, startedAt: "2026-10-16T00:00:00Z", executorLabel: "Kilo CLI" });
  assert.match(c, /^---\nstatus: done\ncompleted: [^\n]+\nexecutor: Kilo CLI\n---/);
  assert.match(c, /## 摘要\n完成了/);
  const f = headlessResultContent({ ok: false, replyText: "", exitCode: 2, startedAt: "t", executorLabel: "Codex CLI" });
  assert.match(f, /status: failed/);
  assert.match(f, /（执行器无文本输出）/);
});

test("argv 的 auto 选项仅作用于执行器角色", () => {
  const a = agentAdapters();
  assert.deepEqual(a.kilo.argv("做X", null, { auto: true }), ["run", "--auto", "--format", "json", "做X"]);
  assert.deepEqual(a.kilo.argv("做X", "ses_s", { auto: true }), ["run", "--auto", "-s", "ses_s", "--format", "json", "做X"]);
  assert.ok(a.claude.argv("做X", null, { auto: true }).includes("--dangerously-skip-permissions"));
  assert.ok(!a.claude.argv("做X").includes("--dangerously-skip-permissions"));
});

test("buildContextDigest 生成最近轮次摘要", () => {
  assert.equal(buildContextDigest([]), null);
  assert.equal(buildContextDigest(null), null);
  const turns = [
    { file: "a.md", inputText: "建X", resultStatus: "done", resultSummary: "建好了" },
    { file: "b.md", inputText: "改X", resultStatus: "failed", resultSummary: "没改成" },
    { file: "c.md", inputText: "再试", resultStatus: null, resultSummary: null },
    { file: "d.md", inputText: "第四轮", resultStatus: "done", resultSummary: "OK" },
  ];
  const d = buildContextDigest(turns, 3);
  assert.ok(!d.includes("a.md"));
  assert.ok(d.includes("b.md") && d.includes("没改成"));
  assert.ok(d.includes("c.md") && d.includes("未完成"));
  assert.ok(d.includes("d.md"));
  assert.match(d, /第3轮 \[done\]/);
});

test("delegationPrompt 附带多轮背景", () => {
  const p = delegationPrompt("改一下", "第1轮 [done] 需求：建X｜结果：建好了（任务文件 a.md）");
  assert.ok(p.includes("多轮背景（最近轮次"));
  assert.ok(p.includes("任务文件 a.md"));
  assert.ok(p.includes("用户需求：改一下"));
  const p2 = delegationPrompt("首轮");
  assert.ok(!p2.includes("多轮背景（最近轮次"));
});

test("summarizeKiloEvent 提炼进度行", () => {
  assert.match(summarizeKiloEvent({ type: "text", part: { text: "读取文件中" } }), /^💬 读取文件中/);
  assert.equal(summarizeKiloEvent({ type: "text", part: { text: "" } }), null);
  assert.equal(summarizeKiloEvent({ type: "step_start", part: {} }), "▶ 开始一步");
  assert.match(summarizeKiloEvent({ type: "step_finish", part: { reason: "tool-calls" } }), /tool-calls/);
  assert.match(summarizeKiloEvent({ type: "tool", part: { type: "write" } }), /^🔧 write/);
  assert.equal(summarizeKiloEvent("垃圾"), null);
  assert.equal(summarizeKiloEvent(null), null);
});


test("renderMarkdown：先转义再套有限标签", async () => {
  const { renderMarkdown } = await import("../../apps/bridge-client/lib.mjs");
  const xss = renderMarkdown('<script>alert(1)</script> **加粗** `code`');
  assert.ok(!xss.includes("<script>"));
  assert.ok(xss.includes("&lt;script&gt;"));
  assert.ok(xss.includes("<b>加粗</b>"));
  assert.ok(xss.includes("<code>code</code>"));
  const fence = renderMarkdown("说明\n```js\nconst a = 1 < 2;\n```\n结束");
  assert.ok(fence.includes("<pre><code>const a = 1 &lt; 2;</code></pre>"));
  const list = renderMarkdown("- 甲\n- 乙\n\n- [ ] 待办\n- [x] 完成");
  assert.ok(list.includes('<ul class="md-ul">'));
  assert.ok(list.includes("<li>甲</li>"));
  assert.ok(list.includes("☐ 待办"));
  assert.ok(list.includes("☑ 完成"));
  const head = renderMarkdown("## 标题行\n普通行");
  assert.ok(head.includes('<div class="md-h">标题行</div>'));
  assert.ok(head.includes('<div class="md-p">普通行</div>'));
  assert.ok(renderMarkdown("").includes("md-p"));
});

test("normalizeThreads 迁移与默认线程", async () => {
  const { normalizeThreads, findThread, filterTurnsByThread, DEFAULT_THREAD_ID } = await import("../../apps/bridge-client/lib.mjs");
  const empty = normalizeThreads(null);
  assert.equal(empty.projects[0].id, "prj-default");
  assert.ok(empty.projects[0].threads.some(t => t.id === DEFAULT_THREAD_ID));
  const tree = normalizeThreads({ projects: [{ id: "prj-a", name: "甲", threads: [{ id: "thr-1", name: "T1", controllerSession: "ses_x" }] }] });
  assert.equal(tree.projects[0].threads[0].controllerSession, "ses_x");
  const f = findThread(tree, "thr-1");
  assert.equal(f.thread.name, "T1"); assert.equal(f.project.name, "甲");
  assert.equal(findThread(tree, "nope"), null);
});

test("filterTurnsByThread 线程隔离（无标记归默认）", async () => {
  const { filterTurnsByThread, DEFAULT_THREAD_ID } = await import("../../apps/bridge-client/lib.mjs");
  const turns = [
    { inputText: "a", thread: undefined },
    { inputText: "b", thread: "thr-1" },
    { inputText: "c", thread: DEFAULT_THREAD_ID },
  ];
  const def = filterTurnsByThread(turns, DEFAULT_THREAD_ID).map(t => t.inputText);
  assert.deepEqual(def, ["a", "c"]);
  const t1 = filterTurnsByThread(turns, "thr-1").map(t => t.inputText);
  assert.deepEqual(t1, ["b"]);
});

test("buildTaskContent 写入 thread 字段", async () => {
  const { buildTaskContent } = await import("../../apps/bridge-client/lib.mjs");
  const c = buildTaskContent({ taskText: "做X", threadId: "thr-9" });
  assert.match(c, /^---\nfrom: kilo-client\nthread: thr-9\n/);
  const c2 = buildTaskContent({ taskText: "做X" });
  assert.ok(!c2.includes("thread:"));
});

test("defaultAgentPaths 按环境生成路径猜测", async () => {
  const { defaultAgentPaths } = await import("../../apps/bridge-client/agent-env.mjs");
  const home = ["H:", "me"].join("\\");
  const local = [home, "AppData", "Local"].join("\\");
  const p = defaultAgentPaths(home, local);
  assert.ok(p.kilo.startsWith(local));
  assert.ok(p.claude.startsWith([home, ".claude"].join("\\")));
  assert.ok(p.codex.includes("OpenAI"));
  const p2 = defaultAgentPaths("/home/u", "");
  assert.ok(p2.kilo.startsWith(["", "home", "u"].join(sep)));
});

test("kilo 接入模板包含真实仓库路径与标记", async () => {
  const { kiloRulesTemplate, kiloPermissionEdits, KILO_RULES_MARKER } = await import("../../apps/bridge-client/agent-env.mjs");
  const repo = ["R:", "repo"].join("\\");
  const t = kiloRulesTemplate(repo);
  assert.ok(t.includes(KILO_RULES_MARKER));
  assert.ok(t.includes([repo, ".kilo-bridge"].join("\\")));
  assert.ok(t.includes("queue"));
  const e = kiloPermissionEdits(repo);
  assert.ok(e.editBlock.includes('"*": "ask"'));
  assert.ok(e.editBlock.includes(".kilo-bridge"));
  assert.ok(e.externalLines.includes(repo.replace(/\\/g, "\\\\")));
  assert.ok(!e.editBlock.includes("${"));
});
