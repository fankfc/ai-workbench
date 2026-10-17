// Node 专属：文件解析、新机器接入的路径猜测与 Kilo 规则模板（浏览器页面不加载此文件）
import { join as pJoin } from "node:path";
import { readFileSync } from "node:fs";
import { parseFrontmatter } from "./lib.mjs";

export function parseTaskFile(path) {
  try {
    const raw = readFileSync(path, "utf8");
    const fm = parseFrontmatter(raw);
    const title = (raw.match(/^#\s*任务[：:](.*)$/m) || [, ""])[1].trim();
    return { title: title || "（无标题）", fm, raw, ok: true };
  } catch {
    return { title: "（读取失败）", fm: {}, raw: "", ok: false };
  }
}

export function parseResultFile(path) {
  try {
    const raw = readFileSync(path, "utf8");
    const fm = parseFrontmatter(raw);
    const summary = (raw.split(/##\s*摘要/)[1] || "").split(/\r?\n##\s/)[0]
      .replace(/^[\r\n\s：:]+/, "").split(/\r?\n/).filter(Boolean).join(" ").slice(0, 200);
    return { status: fm.status || "unknown", summary, completed: fm.completed || null };
  } catch {
    return { status: "unknown", summary: "", completed: null };
  }
}

// 按机器环境给出默认路径猜测（真实路径由 scripts/setup.mjs 探测后写入 .kilo-bridge/agents.json）
export function defaultAgentPaths(home = process.env.USERPROFILE || process.env.HOME || ".", localAppData = process.env.LOCALAPPDATA || "") {
  return {
    kilo: localAppData ? pJoin(localAppData, "Programs", "kilo", "kilo.exe") : pJoin(home, "kilo", "kilo.exe"),
    claude: pJoin(home, ".claude", "local", "claude.exe"),
    codex: localAppData ? pJoin(localAppData, "OpenAI", "Codex", "bin", "codex.exe") : pJoin(home, "codex", "codex"),
  };
}

// ---------- 新机器接入模板（scripts/setup.mjs 使用，路径按仓库实际位置生成） ----------
export const KILO_RULES_MARKER = "## 智能体协作桥（A 委派协议）";

export function kiloRulesTemplate(repoRoot) {
  const bridge = pJoin(repoRoot, ".kilo-bridge");
  return `
${KILO_RULES_MARKER}

当用户说"交给ZCode"、"让ZCode执行"或"用ZCode"时：

1. 先用读文件工具检查 \`${pJoin(bridge, "client-status.json")}\` 的 updated 时间。
   - 心跳距今 60 秒内：桥客户端正在运行，它已自动捕获这条消息并入队。你只需回复
     "桥客户端已入队，结果出来会自动注回本会话"，不要自己写任何文件。
   - 文件缺失或心跳超过 60 秒（客户端未运行）：把任务写成 UTF-8 markdown 保存到
     \`${pJoin(bridge, "queue")}\`，文件名 \`task-<YYYYMMDD-HHmmss>-<slug>.md\`，内容格式：
     ---
     from: kilo
     workspace: <任务工作目录，不填默认 ${repoRoot}>
     created: <ISO 8601 时间>
     ---
     # 任务：<一句话标题>
     ## 目标
     <要完成什么、验收标准>
     ## 约束与背景
     <可选：分支、禁改范围、相关文件>
2. 告知用户已入队，B 端执行器会取件执行。
3. 查询结果：一律用读取文件工具检查 \`${pJoin(bridge, "results")}\` 下与任务同名的 .result.md。
   禁止用 bash/sleep 循环等待（会被权限系统拒绝）。
4. 读到结果后汇报：status（done/failed/needs-user）、摘要、产物路径。
`;
}

// kilo.jsonc 权限注入片段（相对仓库根的 .kilo-bridge 目录树放行；写入文件的路径分隔符需按 JSONC 规则双反斜杠）
export function kiloPermissionEdits(repoRoot) {
  const bridgeWin = pJoin(repoRoot, ".kilo-bridge").replace(/\\/g, "\\\\");
  const rel = ".kilo-bridge";
  return {
    editBlock: [
      "{",
      `      "*": "ask",`,
      `      "${rel}\\\\*": "allow",`,
      `      "${rel}\\\\*\\\\*": "allow",`,
      `      "${rel}/*": "allow",`,
      `      "${rel}/*/*": "allow",`,
      `      "${bridgeWin}\\\\*": "allow",`,
      `      "${bridgeWin}\\\\*\\\\*": "allow"`,
      "    }",
    ].join("\n"),
    externalLines: `      "${bridgeWin}\\\\*": "allow",
      "${bridgeWin}\\\\*\\\\*": "allow",`,
  };
}

