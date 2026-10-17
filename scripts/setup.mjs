#!/usr/bin/env node
// 智能体协作桥 · 一键装配
// 新机器克隆本仓库后执行：node scripts/setup.mjs
// 可选：--kilo-rules 接入 Kilo 会话捕获规则；--autostart 设置开机自启；--start 装配完成后立即启动；--no-tests 跳过自检
import { spawnSync, spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync, copyFileSync } from "node:fs";
import { join, resolve, dirname } from "node:path";
import { homedir } from "node:os";
import { fileURLToPath } from "node:url";
import { defaultAgentPaths, kiloRulesTemplate, kiloPermissionEdits, KILO_RULES_MARKER } from "../apps/bridge-client/lib.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), ".."); // 仓库根 = scripts 上级
const BRIDGE = join(ROOT, ".kilo-bridge");
const flags = new Set(process.argv.slice(2));
const say = (mark, msg) => console.log(`${mark} ${msg}`);

console.log("智能体协作桥 · 一键装配");
console.log(`仓库根目录：${ROOT}\n`);

// 1) Node 版本检查（node:sqlite 需要 22.5+）
const [major, minor] = process.versions.node.split(".").map(Number);
if (major < 22 || (major === 22 && minor < 5)) {
  say("✗", `Node ${process.versions.node} 过旧：需要 ≥22.5（建议 24）。请先升级 Node.js 再重试。`);
  process.exit(1);
}
say("✓", `Node ${process.versions.node} 满足要求`);

// 2) 目录结构
for (const d of ["queue", "processing", "results", "done"]) mkdirSync(join(BRIDGE, d), { recursive: true });
say("✓", "桥目录已就绪（.kilo-bridge/{queue,processing,results,done}）");

// 3) 智能体发现
const ENV_KEYS = { kilo: "KILO_BIN", claude: "CLAUDE_BIN", codex: "CODEX_BIN" };
function onPath(name) {
  const r = spawnSync(process.platform === "win32" ? "where" : "which", [name], { encoding: "utf8", windowsHide: true });
  if (r.status !== 0) return [];
  return String(r.stdout || "").split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
}
const defaults = defaultAgentPaths(homedir(), process.env.LOCALAPPDATA || "");
const found = {};
for (const id of ["kilo", "claude", "codex"]) {
  const repoLocal = id === "claude"
    ? join(ROOT, ".tools", "claude", "node_modules", "@anthropic-ai", "claude-code-win32-x64", "claude.exe") : null;
  const candidates = [process.env[ENV_KEYS[id]], ...onPath(id), repoLocal, defaults[id]].filter(Boolean);
  found[id] = candidates.find((p) => existsSync(p)) || null;
  say(found[id] ? "✓" : "·", `${id.padEnd(6)} ${found[id] ? `发现：${found[id]}` : "未发现（可选，跳过）"}`);
}

// 4) agents.json（存在则只补缺路径，不覆盖角色选择）
const AGENTS_JSON = join(BRIDGE, "agents.json");
let agents = null;
if (existsSync(AGENTS_JSON)) {
  try { agents = JSON.parse(readFileSync(AGENTS_JSON, "utf8")); } catch { agents = null; }
}
if (!agents) {
  const firstHeadless = ["kilo", "claude", "codex"].find((id) => found[id]);
  agents = {
    controller: firstHeadless || "none",
    executor: firstHeadless || "zcode-session",
    paths: Object.fromEntries(Object.entries(found).map(([id, p]) => [id, p || defaults[id]])),
  };
  writeFileSync(AGENTS_JSON, JSON.stringify(agents, null, 2), "utf8");
  say("✓", `已生成 agents.json：A=${agents.controller}，B=${agents.executor}${firstHeadless ? "" : "（未发现任何无头智能体 CLI：A 已设为 none，B 需要本机 ZCode 会话取件或安装任一智能体 CLI 后重跑 setup）"}`);
} else {
  agents.paths = agents.paths || {};
  let filled = 0;
  for (const [id, p] of Object.entries(found)) if (p && !agents.paths[id]) { agents.paths[id] = p; filled += 1; }
  if (filled) writeFileSync(AGENTS_JSON, JSON.stringify(agents, null, 2), "utf8");
  say("✓", `沿用现有 agents.json（A=${agents.controller}，B=${agents.executor}）${filled ? `，补全 ${filled} 个智能体路径` : ""}`);
}

// 5) Kilo 接入（可选）
if (flags.has("--kilo-rules")) {
  const cfgDir = join(homedir(), ".config", "kilo");
  const agentsMd = join(cfgDir, "AGENTS.md");
  const kiloJsonc = join(cfgDir, "kilo.jsonc");
  try {
    mkdirSync(cfgDir, { recursive: true });
    if (existsSync(agentsMd)) {
      const cur = readFileSync(agentsMd, "utf8");
      if (cur.includes(KILO_RULES_MARKER)) say("✓", "Kilo AGENTS.md 已含桥接规则，跳过");
      else {
        if (!existsSync(agentsMd + ".bridge-bak")) copyFileSync(agentsMd, agentsMd + ".bridge-bak");
        writeFileSync(agentsMd, cur + kiloRulesTemplate(ROOT), "utf8");
        say("✓", "Kilo AGENTS.md 已追加桥接规则（备份为 .bridge-bak）");
      }
    } else {
      writeFileSync(agentsMd, kiloRulesTemplate(ROOT), "utf8");
      say("✓", "Kilo AGENTS.md 已创建并写入桥接规则");
    }
    if (existsSync(kiloJsonc)) {
      let cfg = readFileSync(kiloJsonc, "utf8");
      if (cfg.includes(".kilo-bridge")) say("✓", "kilo.jsonc 已含桥目录放行规则，跳过");
      else {
        if (!existsSync(kiloJsonc + ".bridge-bak")) copyFileSync(kiloJsonc, kiloJsonc + ".bridge-bak");
        const { editBlock, externalLines } = kiloPermissionEdits(ROOT);
        let ok = 0;
        const editRe = /"edit"\s*:\s*"ask"\s*,?/;
        if (editRe.test(cfg)) { cfg = cfg.replace(editRe, `"edit": ${editBlock},`); ok += 1; }
        const extRe = /("external_directory"\s*:\s*\{\s*\r?\n(?:\s*"[^"]+"\s*:\s*"[^"]+"\s*,\s*\r?\n)?)/;
        if (extRe.test(cfg)) { cfg = cfg.replace(extRe, `$1${externalLines}\n`); ok += 1; }
        if (ok === 2) { writeFileSync(kiloJsonc, cfg, "utf8"); say("✓", `kilo.jsonc 已放行桥目录（edit + external_directory，备份为 .bridge-bak）`); }
        else { say("!", `kilo.jsonc 结构与预期不符（仅匹配 ${ok}/2 处）：请参考 docs/runbooks/kilo-bridge.md 手动为 .kilo-bridge 目录树放行 edit 与 external_directory`); }
      }
    } else say("·", "kilo.jsonc 不存在（Kilo 首次运行后生成），权限放行规则请之后重跑 setup 或参考手册手动添加");
  } catch (e) { say("!", `Kilo 接入出错：${e.message}（不影响其余装配）`); }
}

// 6) 自检
if (!flags.has("--no-tests")) {
  say("·", "运行单元测试自检…");
  const r = spawnSync("npm", ["run", "test:bridge-client"], { cwd: ROOT, encoding: "utf8", shell: true, windowsHide: true });
  const tail = String(r.stdout || "").trim().split(/\r?\n/).filter((l) => /^ℹ (tests|pass|fail)/.test(l.trim()));
  if (r.status === 0) say("✓", `自检通过（${tail.join("，").replace(/[ℹ]/g, "").trim()}）`);
  else { say("✗", `自检失败：\n${tail.join("\n")}\n${String(r.stderr || "").slice(-400)}`); process.exit(1); }
}

// 7) 开机自启（可选）
if (flags.has("--autostart") && process.platform === "win32") {
  const target = join(ROOT, "scripts", "kilo-bridge", "watch-bridge-client.cmd");
  const ps = `$ws=(New-Object -ComObject WScript.Shell); $l=$ws.CreateShortcut(join($env:APPDATA,'Microsoft\\Windows\\Start Menu\\Programs\\Startup\\智能体协作桥.lnk')); $l.TargetPath='${target}'; $l.WorkingDirectory='${ROOT}'; $l.WindowStyle=7; $l.Save(); 'ok'`;
  const r = spawnSync("powershell", ["-NoProfile", "-Command", ps], { encoding: "utf8", windowsHide: true });
  say(String(r.stdout || "").includes("ok") ? "✓" : "!", String(r.stdout || "").includes("ok") ? "开机自启快捷方式已创建（删除 Startup 里的「智能体协作桥」即可取消）" : `自启设置失败：${String(r.stderr || "").slice(0, 120)}`);
}

console.log("\n装配完成。启动方式：");
console.log("  双击 scripts/kilo-bridge/start-bridge-client.cmd");
console.log("  或 npm run bridge-client");
console.log("  然后打开 http://127.0.0.1:8791");

// 8) 立即启动（可选）
if (flags.has("--start")) {
  spawn(process.execPath, [join(ROOT, "apps", "bridge-client", "server.mjs")], {
    detached: true, stdio: "ignore", windowsHide: true, cwd: ROOT,
  }).unref();
  say("✓", "桥客户端已启动（后台）");
}
