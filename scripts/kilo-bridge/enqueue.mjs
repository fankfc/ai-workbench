#!/usr/bin/env node
// Kilo -> ZCode 任务入队器。用法：
//   node enqueue.mjs "任务描述" [工作目录]
// Kilo 侧可用 shell 工具调用；也可被用户手动调用。
// 队列协议见同仓库 .kilo-bridge/BRIDGE.md。
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const BRIDGE_DIR = join(import.meta.dirname, "..", "..", ".kilo-bridge");

const description = process.argv[2];
if (!description) {
  console.error("用法: node enqueue.mjs \"任务描述\" [工作目录]");
  process.exit(2);
}
const workspace = process.argv[3] || "D:\\zcode-workspace\\ai";

const pad = (n) => String(n).padStart(2, "0");
const now = new Date();
const stamp =
  `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}` +
  `-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
const slug = description.trim().slice(0, 24).replace(/[^\w\u4e00-\u9fa5-]+/g, "-").replace(/^-+|-+$/g, "") || "task";
const fileName = `task-${stamp}-${slug}.md`;

const firstLine = description.trim().split(/\r?\n/)[0].replace(/^#\s*/, "");
const body = description.trim().split(/\r?\n/).slice(1).join("\n").trim();
const content = [
  "---",
  "from: kilo",
  `workspace: ${workspace}`,
  `created: ${now.toISOString()}`,
  "---",
  "",
  `# 任务：${firstLine}`,
  "",
  "## 目标",
  body || firstLine,
  "",
].join("\n");

mkdirSync(join(BRIDGE_DIR, "queue"), { recursive: true });
writeFileSync(join(BRIDGE_DIR, "queue", fileName), content, "utf8");
console.log(join(BRIDGE_DIR, "queue", fileName));
