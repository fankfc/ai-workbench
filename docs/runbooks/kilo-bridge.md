# Kilo 桥运行手册（Kilo → ZCode 委派）

建立日期：2026-10-16。让本机 Kilo（VS Code 插件 `kilocode.kilo-code-7.8.12` 与 `D:\Kilo\kilo` CLI 7.8.12）把任务委派给 ZCode（GLM，个人编码计划账号）执行。

## 为什么是文件桥而不是 MCP/ACP 直连

外部程序直接驱动 ZCode 的两条"正规"入口目前都被同一平台缺口挡住（见 [D004/D005 复检](../acceptance/D004-D005-recheck-20261016.md)）：

- `zcode --prompt` 无头入口没有模型选择参数，启动即报 `Select a model before continuing`；
- `zcode app-server` 协议入口可达且 `session/create` 可推进到注册表查找，但独立实例的提供方注册表中所有账号提供方 `entitled:false`（账号提供方只在桌面宿主 `desktop-continuous` 握手、经 `syncAccountProviderConfig` 推送后实体化），报 `Provider Registry 中不存在 Model`；
- ZCode 桌面宿主不监听任何本地 TCP 端口，无对外附着面。

因此 Kilo 操控 ZCode 的可行路径是：任务文件入队 → ZCode 桌面会话内的持久定时自动化取件执行 → 结果文件回写。这条路径完全使用现有编码计划账号，不需要新凭证、新登录或 API Key。

## 组成

| 部件 | 位置 | 说明 |
| --- | --- | --- |
| 队列协议 | `.kilo-bridge/BRIDGE.md` | 任务/结果文件格式、目录状态机与约定 |
| 队列目录 | `.kilo-bridge/queue/` → `processing/` → `done/` | 排队中 → 执行中 → 已归档 |
| 结果目录 | `.kilo-bridge/results/` | ZCode 回写 `<任务文件名>.result.md` |
| 入队脚本 | `scripts/kilo-bridge/enqueue.mjs` | 手动入队：`node enqueue.mjs "任务描述" [工作目录]` |
| 定时自动化 | （**当前已停用**）曾为「Kilo 桥兜底取件（每30分钟）」 | 2026-10-17 用户要求停止定时发送后已删除；executor=zcode-session 时队列任务需对 ZCode 说「处理队列」手动触发，无头直执不受影响；恢复兜底按本表重建 |

## 日常可用性（2026-10-17 增补）

- **兜底取件（已停用）**：曾为每 30 分钟轮询（automation id `automation-ef2098fc-43cb-43e8-9d0d-179c4b81cc50`）；恢复方式：重建同款自动化即可。
- **客户端守护与自启**：`scripts/kilo-bridge/watch-bridge-client.cmd` 守护循环（异常退出 5 秒自动重启），开机自启快捷方式在 `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Kilo-ZCode桥客户端.lnk`。彻底停用：删该快捷方式 + 结束 cmd/node 进程。

## 对话记忆与执行直播（2026-10-17 增补，实测通过）

- **多轮上下文**：每次委派自动把最近 3 轮（需求+结果摘要+任务文件名）注入 A 端推理提示词，支持指代（"刚才那个文件"）。实测：第二轮不提文件名只说"把刚才那个文件改成 version 2"，任务书正确写出「『刚才那个文件』按第N轮的结果推断为 mt-a.txt」并完成修改。A=none 直投不经过推理，无记忆。
- **返修按钮**：done 状态的结果气泡上有「↻ 返修这一轮」，点击自动填入"返修「任务文件」这一轮："，补充说明发送即可；上一轮需求与结果作为背景自动带入。
- **执行直播**：B 端无头直执（kilo json 事件流）时，执行中气泡实时滚动最近 12 条进度行（工具调用/步骤/文本片段），完成即替换为正式结果。zcode-session 执行端无直播（在 ZCode 会话内执行）。
| **桥客户端** | `apps/bridge-client/`（`npm run bridge-client`） | 常驻服务，见下节 |

## 桥客户端（2026-10-16 交付，端到端验证通过）

`node apps/bridge-client/server.mjs`（或 `npm run bridge-client`，或双击 `scripts/kilo-bridge/start-bridge-client.cmd`），仅绑定 `127.0.0.1:8791`。职能：

1. **控制台直接委派**：网页输入需求（Ctrl+Enter 发送）→ Kilo 无头推理整理成任务书（补默认值、可检查验收标准、约束）→ 自动入队 → ZCode 执行 → 结果与 Kilo 注回汇报都显示在控制台。全程无需打开 Kilo/ZCode 界面；
2. **Kilo 会话监听**：每 5 秒只读增量查询 `~/.local/share/kilo/kilo.db`，识别带「交给ZCode」触发词的新用户消息并自动入队（触发词有词边界，不会误匹配）；
3. **心跳防双入队**：每 5 秒写 `client-status.json`；Kilo 侧规则据此判断（60 秒阈值），客户端在线时 Kilo 只确认不写文件；
4. **格式校验拒收**：queue 中不符合协议的任务文件（缺 frontmatter/created/标题/目标小节）自动写失败 result 并归档，不进入执行；
5. **滞留告警**：排队 >15 分钟（取件周期 10 分钟）或执行 >20 分钟的任务在控制台标「⚠ 滞留」——通常是 ZCode 会话未运行或被占用；
6. **SSE 网页控制台**：任务时间线（排队中/执行中/done/failed/needs-user、摘要、注回标记与 Kilo 汇报摘要）、委派状态、事件日志；
7. **结果自动注回（`AUTO_INJECT=true`）**：结果出现后 `kilo run -s <来源会话>` 注回，`inject-log.jsonl` 记录并跨重启去重；spawn 失败有兜底日志。

代码分层：纯逻辑在 `apps/bridge-client/lib.mjs`（11 项单元测试，`npm run test:bridge-client`），服务与 IO 在 `server.mjs`，界面在 `public/index.html`。

端到端证据（2026-10-16，两轮）：① 真实 kilo 会话触发 → 心跳确认无双入队 → 自动入队 → 执行回写 → 注回，Kilo 汇报正常；② 控制台委派 → Kilo 推理出带验收清单的任务书（连编码乱码输入都能容错）→ 入队 → 执行 → 注回，Kilo 汇报「成熟化链路测试已跑通」。

运维注意：重启前先结束旧进程（`taskkill /PID <8791端口占用者> /F`，否则 EADDRINUSE）；kilo.db 为 Kilo 私有库（7.8.12 schema），只读访问，schema 变更需同步适配 `lib.mjs`/`server.mjs`。

### 成熟度现状与已知边界

已覆盖：无人值守闭环（无人工泵）、失败路径（格式拒收、滞留告警、中断恢复、注回兜底）、可观测性（时间线/状态机/事件日志/注回摘要）、单元测试。结构性边界（平台未解锁前无法消除）：取件延迟下限为调度周期（10 分钟）；任务在 ZCode 单一会话内串行执行、共享上下文，无独立执行环境；委派与注回各消耗一次 Kilo 侧模型调用。

## 双端可插拔智能体（2026-10-16 交付，两条链路实测通过）

A 端（推理控制器）与 B 端（执行器）可在网页选择器或 `POST /api/agents` 热切换（配置持久化在 `.kilo-bridge/agents.json`，对新任务生效）：

- **A 端可选**：`kilo`（默认，推理整理任务书）｜`claude`（已装 2.1.296，未登录，调用会返回认证错误）｜`codex`（已装 0.162）｜`none`（直投：需求不经推理直接入队，实测即时入队）。
- **B 端可选**：`zcode-session`（默认：队列 + ZCode 会话取件，用编码计划账号）｜`kilo` / `claude` / `codex`（**客户端无头直执**：任务入队后由客户端立即在任务工作区 spawn 对应 CLI 执行并自动写结果归档——实测入队后 1 秒开工，无轮询延迟，消耗对应智能体账号而非 ZCode 额度）。
- 执行器角色以自主模式调用（kilo `--auto`、claude `--dangerously-skip-permissions`；codex exec 本身沙箱非交互）；推理角色不带自主权限（只输出文本）。自动注回仅支持可续接会话的智能体（kilo/claude）。
- 适配器与角色配置的纯逻辑在 `apps/bridge-client/lib.mjs`（17 项单测）；新增智能体 = 在 `agentAdapters()` 加一个 `{path, argv, parseText, canContinue}` 描述即可。

实测记录（2026-10-16）：B=kilo 无头直执（含一次定位到权限 auto-reject 的失败复演与修复）；A=none 直投。

## Kilo 侧接入

**已完成全局配置**（Kilo CLI 与桌面共用 `~/.config/kilo/`）：

- `~/.config/kilo/AGENTS.md`：「ZCode 执行代理（委派协议）」为心跳感知规则——客户端在线时 Kilo 只确认（"桥客户端已入队，结果会自动注回"），离线时按手动协议自己入队；
- `~/.config/kilo/kilo.jsonc`：`edit` 与 `external_directory` 对 `.kilo-bridge` 目录树放行（相对/绝对、正反斜杠模式），其余维持 `ask`。

日常使用：对 Kilo 说"交给ZCode：<任务>"即可。客户端在运行时全程自动（入队、结果注回）；客户端未运行时退化为手动模式（Kilo 自己入队，用户说"查ZCode结果"取回）。

若使用 VS Code 版 Kilo Code 插件（独立配置体系）：把 AGENTS.md 中委派协议一节粘贴进其 Settings → Custom Instructions，其余流程相同。

## 成本与限制

- 每 10 分钟一次定时触发，即使队列空闲也产生一次极小的会话轮次（编码计划额度）。嫌频繁/太慢可让 ZCode 调整间隔。
- 端到端延迟为分钟级（取件周期 + 任务执行时间），不是实时操控。
- 任务在 ZCode 会话权限规则下执行；对外发布、不可恢复删除、凭证修改类任务会被标记 `needs-user` 拒绝执行。
- 多任务按取件顺序串行处理。

## 解除方式

在 ZCode 中删除名为「Kilo 桥轮询（每10分钟）」的工作区自动化（automation id `automation-de4ac5b2-85c9-44aa-864f-e0751b1de0cb`），或让 ZCode 代删；随后 `.kilo-bridge/` 目录可整体删除。

## 升级路线（解除阻塞后）

若 ZCode CLI 未来支持无头模型选择或独立实例账号授权（复检报告路线 a），或用户决定为独立实例配置 API Key 提供方（路线 c，独立计费），可把本桥替换为正式适配器：Kilo（MCP 客户端，`kilo mcp add`）→ 自建 MCP server → `zcode app-server`。届时 `services/orchestrator/app/providers/native_rpc.py` 的受管 stdio 传输与 `zcode_protocol.py` 的入口哈希校验可直接复用。

## 前端优化（2026-10-17 第二轮）

- **性能**：SSE 推送 300ms 合流（执行直播高频输出不再打爆前端）；前端按轮次签名做差分渲染，只有变化的气泡更新 DOM（长历史/直播时不再整页重建，选中文本不被打断）。
- **可读性**：结果气泡经安全 Markdown 渲染（先全量转义再套有限标签：代码块/行内码/加粗/列表/勾选框/标题，lib.mjs `renderMarkdown`，含 XSS 单测）。
- **体验**：深色模式（跟随系统 prefers-color-scheme，含 8 色淡雅配对的暗色变体）；Enter 发送（输入法组词保护，Shift+Enter 换行，Ctrl+Enter 兼容）；「↓ 回到最新」浮动按钮（滚上去看历史时出现，带新结果计数）；结果气泡「⧉ 复制」按钮；日期分隔条与轮次编号；SSE 连接状态指示灯（已连接/重连中）；toast 提示替代弹窗；reduced-motion 适配。

## 项目与对话线程（2026-10-17 第三轮，E2E 通过）

左侧项目栏：对话按「项目 → 对话」两级组织（`POST /api/threads` 新建，持久化 `.kilo-bridge/threads.json`）。每个对话独立：

- **上下文隔离**：多轮摘要只取本对话的轮次（任务文件 frontmatter `thread:` 字段；无标记的历史任务归默认对话）；
- **智能体侧构建**：每个对话绑定 A 端推理的同一 Kilo 会话（thread 的 `controllerSession`，委派时 `-s` 续接），A 端在会话层记住整个项目脉络；实测同一对话两轮任务 source-session 一致、第二轮不提文件名也能正确修改；
- 界面：新建项目/对话、点击切换（聊天区只显示当前对话）、每对话显示任务数、活动对话存 localStorage；窄屏侧栏自动隐藏。

E2E 记录（2026-10-17）：演示项目→功能A 对话，两轮委派（第二轮仅说"把刚才那个文件改成 B"）→ 文件 A→B 修改成功，两轮 source-session 相同，24 项单测全过。
