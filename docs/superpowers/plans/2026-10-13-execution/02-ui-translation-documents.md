# UI、条件翻译与双语文档 Implementation Plan

阶段二冻结更新：当前未完成的验收与开发已暂停，恢复入口为[冻结说明](../../../acceptance/part-two-freeze-20261014/FREEZE.md)。下文原计划和历史测试结果保留，不能据此自行继续执行或改变完成资格。

执行更新（2026-10-14）：D021–D040 已按下文计划实施本地核心路径，最终 Python 1318、桌面单元27、实际 Electron E2E28 项通过；各卡仍依完成门槛保持 in_progress / blocked，未批量置 done。真实连接、人评及完整真实垂直验收尚未完成。实际结果与当前接口见[阶段二报告](../../../acceptance/part-two-progress.md)和[任务状态](task-board.json)；下文原始计划的日期、拟建路径及命令作为规划历史保留。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 D021–D040：让 Windows 用户在聊天界面发问，通过 Claude/ZCode 或 GPT 路径得到批准答案与真实、完整、同版本的交付文件。
**Architecture:** Electron 主进程通过隔离 preload 代理本地服务；后端先过滤公开事件，再给 renderer。翻译与文档发布位于后端强制门槛，任何模型或 UI 都不能自行绕过。
**Tech Stack:** Electron、React、TypeScript、Vite；Python/FastAPI/Pydantic/SQLite；pytest、Vitest、Playwright；文档解析/渲染器按 D001–D006 的能力实测与锁定结果装配。

日期：2026-10-13（Asia/Shanghai）。状态：仅实施指导，下面代码、命令、目录和测试全部供未来执行；本次没有开发产品或连接模型。
仓库根：`C:/Users/asd15/Documents/ChatGPT/ai`。下面实现/测试路径均相对于此根；每张任务卡列出其明确拟建或修改的文件。
上游：[主计划](../2026-10-13-industrial-agent-workbench-plan.md)、[设计合同](../../../../DESIGN.md)、[翻译规格](../../specs/2026-10-13-translation-delivery-spec.md)、[基础后端指南](01-foundation-runtime.md)。
任务数据：[tasks-02.json](data/tasks-02.json)。所有卡初始为 `planned`，不能因文档中写有通过条件就标为完成。

## Global Constraints

- 质量以 A 独立完成基准为目标，尽量减少 A 总 token；必要推理、全文定稿、返修与失败消耗不能从账本删去。
- A 默认 Claude Code/Claude，B 为 ZCode/GLM；A 可选 GPT。实际模型身份 unknown/mismatch 时停止，不按 App 名猜测。
- Claude 的输入中文完整英译，英文回答完整中译，包含追问和必要上下文；GPT 无显式翻译任务时强制 translator 调用必须为 0。
- 主聊天只呈现用户问题、批准的回答、必要澄清/中文错误和文件；内部流在后端公开投影之前排除，不能靠 CSS 隐藏。
- A 原文必须来自 A 实际完整英文输出；B 写作后 A 只给 PASS 不满足要求。内容作者、审核者、渲染器分别记录。
- PDF/DOCX/MD 按用户请求格式双语配对；原件哈希、源版本、块映射、QA 和批准一致才能原子发布，原件改变使译文失效。
- 每个翻译作业最多 3 次候选，自动检查和同模型自查不是绝对语义保证；关键歧义用中文澄清，失败不发布成功。
- Electron 使用隔离进程与窄桥接；本地服务令牌留主进程，凭据不进入聊天、renderer 或普通诊断。
- 翻译不改变服务使用资格；不得添加地区限制绕过、隐蔽模型替换或假的连接成功。
- 所有文件读写经 D017 作用域网关；翻译模块的 context_gateway 仅形成语言视图，不另建可绕过权限的读取入口。

## 执行与共享接口

每卡顺序：核对依赖证据 → 建立具体业务反例 → 运行到预期断言失败 → 小步实现 → 原反例通过 → 检查证据与差异 → 独立复核 → 提交。
缺包、拼写错或 fixture 尚未实现只算装置故障，不作为业务红灯。完成条件不满足时保持进行中，不能写已通过；只重跑受影响检查及该卡门槛。
D007 保持 `ProviderIdentity(adapter, model_id, family, connection_id)`、`AgentRequest`、`AgentEvent` 的既有接口，核验扩展存独立记录。
D009 入口为 `app.api.application.create_app(settings: AppSettings)`，settings 含 data_root、api_token、provider_mode、startup_recovery。
会话 API：POST/GET `/v1/conversations`；POST `/v1/conversations/{id}/turns` 使用 text、provider_profile_id、client_request_id，返回 202。
只读公开历史与 SSE：GET `/v1/conversations/{id}/messages`、GET `/v1/conversations/{id}/events?after_seq=N`；取消为 POST `/v1/tasks/{id}/cancel`。
fake 配置沿用 `fake-gpt`/`fake-glm`；真实测试使用已核验 profile ID。模拟结果必须标为 fake，不能纳入 D040 真实完成证据。
测试翻译分支时 D026 为 fake 适配器增加测试专用 `fake-claude`，模拟身份元数据，仍标 provider_mode=fake；生产连接注册表拒绝该profile。
测试装置沿用 `tests/conftest.py::probe(CASE, **options)`，调用 `scenario_driver.py CASE --root DIR --options JSON`，stdout 为真实采集 JSON。
D021 建 Electron fixture；D025 扩展 getPublicFrames。下面四组代表性测试是最低合同；每卡列出的其他测试须包含其具体正/负场景。
任务负责人对产品文件负责；QA 对独立反例和证据负责；双语/领域评审对语义样本裁决负责，模型自评不可代替。
所有证据包含任务 ID、Git 提交、环境、时间、输入哈希、真实命令/退出码和未完成项。原始正文在受控本地存储，摘要证据与日志脱敏。

---

### D021：Electron 宿主、隔离 preload 与本地服务生命周期

**目的 / 负责人 / 估算：** 让安装后的单个桌面入口可靠启动和退出本地服务，并将 renderer 权限限制在业务调用内。 客户端工程师；后端工程师复核生命周期；14 工时。
**依赖 / 需求：** D007、D009、D011、D012；R06、R12、R13。
**输入与接口：** D009 的回环 API 与一次性启动凭据；D011 子进程句柄和 D012 恢复协议；输出 DesktopBridge 类型及 BackendSupervisor 状态。
**拟建/修改文件：**
`apps/desktop/src/main/index.ts`；`apps/desktop/src/main/backend.ts`；`apps/desktop/src/main/ipc.ts`；`apps/desktop/src/preload/index.ts`；`apps/desktop/src/shared/desktop-bridge.ts`；`tests/desktop/backend.test.ts`；`tests/desktop/preload.test.ts`；`tests/support/electron-fixture.ts`

- [ ] 1. 先在 backend.test.ts 构造健康检查超时、服务提前退出、旧端口被占用三个反例，断言窗口不把未就绪服务标为已连接。
- [ ] 2. 在 shared/desktop-bridge.ts 声明 createConversation、submitTurn、cancelTurn、listMessages、subscribePublic、chooseFiles、saveArtifact、settings 接口；所有输入使用 D007 schema 校验。
- [ ] 3. 在 index.ts 创建 BrowserWindow，固定 contextIsolation=true、nodeIntegration=false、sandbox=true；只加载本地打包资源，阻止未允许的顶层导航和弹窗。
- [ ] 4. 在 backend.ts 以参数数组启动锁定的 Python 可执行文件，绑定 127.0.0.1 动态端口；认证令牌只保留在主进程，不写 URL、日志或 renderer 全局变量。
- [ ] 5. 为启动协议设置就绪确认、健康超时和有界重启；只有握手的进程标识、端口及协议版本一致才接受服务。
- [ ] 6. 在 ipc.ts 按 channel 白名单与发起窗口校验调用来源；preload 逐个导出窄方法，不暴露通用 invoke、执行 shell 或任意读取文件接口。
- [ ] 7. 把关闭窗口与退出应用分开：关闭行为按偏好处理；应用退出先请求保存检查点，按超时终止其管理的子进程树，记录未确认状态供下次恢复。
- [ ] 8. 加入单实例锁；第二次启动仅聚焦现有窗口，不再启动后端；后端掉线时保留草稿和已有消息，显示可重试的中文连接状态。
- [ ] 9. 建立仅测试构建可用的 electron-fixture.ts，启动实际 Electron 与临时用户数据目录；测试结束等待托管进程退出并保留失败日志。
- [ ] 10. 运行宿主和桥接测试，查看进程树、IPC 载荷与退出证据；记录实际锁定版本，复核通过后提交本卡文件。

**测试命令：** `npm exec vitest run -- tests/desktop/backend.test.ts tests/desktop/preload.test.ts`。
**预期负例：** 伪造 IPC 来源、renderer 请求任意路径、后端未完成握手均被拒绝；关闭再打开不产生第二个运行任务。
**证据：** `artifacts/acceptance/D021/lifecycle.json`；`artifacts/acceptance/D021/ipc-boundary.json`；`artifacts/acceptance/D021/process-tree.txt`。
**完成条件：** 正常启动、健康失败、单实例、恢复与退出均有真实进程证据，renderer 不获得通用执行权或认证令牌。
**失败回退：** 禁用启动入口并保留草稿/数据库；只清理本卡创建的临时测试目录，不以全盘查杀或猜测 PID 修复。

---

### D022：聊天基础布局、主题与设计 tokens

**目的 / 负责人 / 估算：** 按 DESIGN.md 建立可键盘操作、可缩放的聊天壳，后续页面共用一套视觉规则。 客户端工程师；产品与 QA 复核视觉；10 工时。
**依赖 / 需求：** D021；R06。
**输入与接口：** DESIGN.md 色彩、字号、侧栏和断点；D021 的 DesktopBridge；输出 AppShell 及可复用基础控件。
**拟建/修改文件：**
`apps/desktop/src/renderer/App.tsx`；`apps/desktop/src/renderer/layout/AppShell.tsx`；`apps/desktop/src/renderer/components/Button.tsx`；`apps/desktop/src/renderer/components/InlineNotice.tsx`；`apps/desktop/src/renderer/styles/tokens.css`；`apps/desktop/src/renderer/styles/layout.css`；`tests/e2e/layout.spec.ts`

- [ ] 1. 在 layout.spec.ts 先固定 1440×900、1280×800、1024×768、320 CSS px 四种视口，断言正文无整页横向溢出且输入区可见。
- [ ] 2. 将 DESIGN.md 的浅/深色颜色、4–48px 间距、16px 正文、820px 内容宽度逐项写入 tokens.css；组件只引用这些变量。
- [ ] 3. 在 AppShell.tsx 建立侧栏、主标题、消息区和输入槽，侧栏展开 260px、折叠 64px；窄窗口使用可关闭抽屉。
- [ ] 4. 为 /chat/new、/chat/:id、/settings/connections、/settings/preferences、/usage 声明页面路由；未知路由返回新会话页面并保留当前草稿。
- [ ] 5. 实现 Button 和 InlineNotice 的键盘焦点、禁用、等待、错误状态；主要发送/停止命中区至少 40×40px。
- [ ] 6. 加入跳到对话、跳到输入框入口及可见焦点样式；抽屉和弹层关闭后恢复触发控件的焦点。
- [ ] 7. 实现主题及正文字号 14–22px 偏好，处理 prefers-reduced-motion；动画只保留短透明度变化。
- [ ] 8. 用长中文、代码块、宽表、长文件名填充测试页面；代码和表格局部滚动，用户上翻时保持阅读位置。
- [ ] 9. 对浅色、深色、200% 缩放和大字号逐项截图，检查实际组合对比度、控件遮挡及系统字体回退。
- [ ] 10. 运行布局与键盘检查，将截图、尺寸和问题裁决存入证据目录；修改 DESIGN.md 数值前先记录差异理由，提交通过的布局。

**测试命令：** `npm run test:e2e -- tests/e2e/layout.spec.ts`。
**预期负例：** 320 CSS px、200% 缩放和长 URL 下发送入口不能消失；没有焦点或只靠颜色表达的错误不能验收通过。
**证据：** `artifacts/acceptance/D022/layout-matrix.json`；`artifacts/acceptance/D022/screenshots/`；`artifacts/acceptance/D022/accessibility-notes.md`。
**完成条件：** 约定视口、主题、键盘和缩放场景可用，未引入流程图、代理头像队列或内部状态面板。
**失败回退：** 退回上一份已验收 tokens 与布局；保留组件接口，不用隐藏溢出裁掉用户正文掩盖问题。

---

### D023：会话历史、消息输入、中文输入法与附件

**目的 / 负责人 / 估算：** 完成用户真实发问、继续会话和添加材料的核心交互，避免输入法误发送和重启丢草稿。 客户端工程师；后端工程师复核幂等键；24 工时。
**依赖 / 需求：** D008、D009、D018、D021、D022；R06、R12。
**输入与接口：** 会话/消息 API、附件导入 API、D018 公开消息 DTO；输出 ConversationList、Composer 和可恢复草稿。
本卡补齐后端接口：`GET /v1/conversations?q=&cursor=` 分页搜索；`PATCH /v1/conversations/{id}` 更新 title/pinned/archived 并校验版本；`DELETE /v1/conversations/{id}` 先停止关联活动任务，再按引用规则删除。`POST /v1/attachments` 接收主进程传来的文件流、conversation_id和名称并返回 attachment_id；`DELETE /v1/attachments/{id}` 解除草稿引用。turn 请求新增可选 `attachment_ids: list[str] = []`，逐项校验所属会话、导入完成、类型与大小；renderer不提交本地源路径。
**拟建/修改文件：**
`apps/desktop/src/renderer/chat/ChatPage.tsx`；`apps/desktop/src/renderer/chat/ConversationList.tsx`；`apps/desktop/src/renderer/chat/MessageList.tsx`；`apps/desktop/src/renderer/chat/Composer.tsx`；`apps/desktop/src/renderer/chat/AttachmentChip.tsx`；`apps/desktop/src/renderer/chat/drafts.ts`；`tests/e2e/composer-history.spec.ts`；`tests/fixtures/ui/messages.json`
后端及桥接同时修改：`services/orchestrator/app/api/conversations.py`；`services/orchestrator/app/api/attachments.py`；`services/orchestrator/app/api/turns.py`；`services/orchestrator/app/api/application.py`；`services/orchestrator/app/storage/attachments.py`；`apps/desktop/src/main/attachments.ts`；`apps/desktop/src/main/ipc.ts`；`tests/integration/test_attachments_api.py`。

- [ ] 1. 建立 messages.json：空会话、含长中文及代码的 30 条消息、两个置顶会话、一个归档会话；composer 测试先断言 IME Enter 不会创建新轮次。
- [ ] 2. 实现上述会话后端接口及对应界面操作，分页、搜索、重命名、置顶和归档均持久化；标题用本地规则或 B，不请求 A。
- [ ] 3. 为 Composer 处理 compositionstart/compositionend 与 KeyboardEvent.isComposing；Enter 发送、Shift+Enter 换行，组合输入期间两者不触发提交。
- [ ] 4. 按 conversation_id 保存草稿、附件引用和所选 A；切换会话、窗口关闭和后端掉线均保留草稿，明确发送成功后才清除。
- [ ] 5. 实现主进程选文件→受控文件流导入→后端不可变保存与哈希→返回附件ID的链路；大小/类型限制、名称和作用域在后端校验。
- [ ] 6. 附件逐个显示读取中、可用、失败和移除；必要附件未就绪时禁止发送并定位失败文件，限制由后端能力合同返回。
- [ ] 7. 提交携带客户端生成的唯一提交键；连点发送、重连补发和 UI 重挂载必须复用该键，等待 message.accepted 后生成唯一消息。
- [ ] 8. MessageList 仅渲染公开用户消息及批准回复，Markdown 禁用原始 HTML；代码复制保留原文，不自动翻译用户代码或引用。
- [ ] 9. 实现 Ctrl+N、Ctrl+K、消息复制、滚动锚点和“有新回答”提示；归档可撤销，删除使用明确确认与后端删除语义。
- [ ] 10. 执行 IME、附件失败、连续发送、刷新恢复、历史分页及 XSS 样例；保存 API 请求计数与截图后提交。

**测试命令：** `python -m pytest tests/integration/test_attachments_api.py -q`；`npm run test:e2e -- tests/e2e/composer-history.spec.ts`。
**预期负例：** 组合输入 Enter、同一提交键重复请求和切换会话不能新增重复轮次；含 <script> 的 Markdown 只显示文本或被清理。
**证据：** `artifacts/acceptance/D023/submission-ids.json`；`artifacts/acceptance/D023/ime-recording.webm`；`artifacts/acceptance/D023/history-recovery.json`。
**完成条件：** 中文输入、附件、历史和草稿可连续使用，所有消息与附件都绑定正确会话。
**失败回退：** 关闭问题快捷键或附件类型入口并保留草稿；不得删除整个会话库或重复提交模型任务恢复界面。

---

### D024：模型连接检测、A 选择与设置

**目的 / 负责人 / 估算：** 让用户连接 Claude Code/ZCode 并选择真实 A，连接状态反映实际检测结果。 客户端工程师与接入工程师；12 工时。
**依赖 / 需求：** D007、D009、D020、D021、D022；R03、R04、R06、R12。
**输入与接口：** D020 真实适配能力报告、ProviderIdentity、连接配置 API；输出可用连接及下一轮 A 选择。
**拟建/修改文件：**
`apps/desktop/src/renderer/settings/Connections.tsx`；`apps/desktop/src/renderer/chat/ModelSelector.tsx`；`apps/desktop/src/main/credentials.ts`；`services/orchestrator/app/api/settings.py`；`tests/e2e/connections.spec.ts`；`tests/integration/test_connection_settings.py`；`docs/acceptance/real-profile-ids.json`

- [ ] 1. 先用未配置、检测中、已核验、身份未知、凭证失效五个连接 fixture 验证页面状态，禁止单凭填写模型名显示已连接。
- [ ] 2. 连接页分别列 A 默认 Claude、A 可选 GPT、B ZCode/GLM，显示实际检测的模型族、入口版本和必要能力，不显示或导出凭证。
- [ ] 3. 连接设置保存凭据引用；需要凭据时调用系统安全存储或既有 CLI 登录，不能在 SQLite、前端状态或普通日志中存明文。
- [ ] 4. “检测连接”发起受支持的小型能力探测并返回时间、真实身份和启动/取消/恢复/用量能力；检测失败保持原因与重试入口。
- [ ] 5. 为受限制能力显示具体说明，例如未支持取消或无法取得用量；演示连接显式标“演示”，禁止成为真实交付默认连接。
- [ ] 6. ModelSelector 默认使用已核验 Claude；GPT 未配置时保留清楚的未连接状态，不能后台切换其他模型完成当前任务。
- [ ] 7. 每次提交发送连接 ID 与预期配置版本；选择新 A 只影响下一轮，当前运行快照在后端保持不变。
- [ ] 8. 运行中发现后端身份变化时请求暂停并显示中文连接问题；用户重新连接后由后端建立新执行版本，不能沿用旧通过记录。
- [ ] 9. 验证连接页面、消息导出和诊断对凭证全部遮罩；检测服务不可达与身份 unknown 的中文文案可操作且不展示原始堆栈。
- [ ] 10. 运行连接 UI/API 测试，使用 P0 已通过的真实连接复查一轮；记录未支持入口，提交本卡结果。

**测试命令：** `python -m pytest tests/integration/test_connection_settings.py -q`；`npm run test:e2e -- tests/e2e/connections.spec.ts`。
**预期负例：** 伪造 App 名、未知实际模型族、失效凭证不能获得绿色可用状态；未配置 GPT 不可偷偷使用 Claude。
**证据：** `artifacts/acceptance/D024/connection-matrix.json`；`artifacts/acceptance/D024/redacted-settings.json`；`artifacts/acceptance/D024/screenshots/`。
**完成条件：** Claude/ZCode 默认连接可真实检测；GPT 可选择或明确不可用；凭据、当前轮和下一轮设置边界清楚。
**失败回退：** 保留最后一次已核验配置并标为需复检；遇凭证问题停止新任务，不更换地区代理或猜测账号条件。

---

### D025：仅消费公开问答事件、真实取消与中文错误

**目的 / 负责人 / 估算：** 让内部英文、翻译与工具日志从数据层就无法进入聊天，同时保持取消和失败信息真实。 客户端工程师；后端与 QA 联合审查；14 工时。
**依赖 / 需求：** D010、D012、D018、D023、D024；R06、R08、R11、R12。
**输入与接口：** D018 PublicEvent 投影、D010 outbox 游标、D012 取消确认；输出公开消息 reducer 与事件泄漏证据。
**拟建/修改文件：**
`apps/desktop/src/renderer/chat/public-events.ts`；`apps/desktop/src/renderer/chat/MessageList.tsx`；`apps/desktop/src/renderer/chat/RunNotice.tsx`；`tests/support/electron-fixture.ts`；`tests/e2e/chat-publication.spec.ts`；`tests/integration/test_public_chat_transport.py`

- [ ] 1. 在本指南测试组 A 写 canary 反例：向后端注入 model.delta、tool.delta 和 translation.delta，捕获全部公开传输帧而不只检查最终 DOM。
- [ ] 2. 只接受 D018 白名单事件并再次按 schema 验证；未知事件丢弃并记脱敏诊断，不把原始 payload 自动展开成消息。
- [ ] 3. 以 turn_id、event_id、sequence 去重公开回放；重连从已确认游标恢复，旧轮次事件不能覆盖当前等待或文件状态。
- [ ] 4. response.pending 仅驱动“正在准备回答…”；answer.published 才创建答案，Claude 内部英文和候选译文在服务端不可进入该事件。
- [ ] 5. 停止按钮先显示“正在停止…”并发送唯一取消请求；收到取消确认后才显示“已停止”，远端未确认时不虚报已结束。
- [ ] 6. request.failed 和 input.required 采用后端批准的中文消息；未提供可显示文案时用稳定中文兜底，不能渲染内部异常对象。
- [ ] 7. 前端收到取消后迟到答案时拒绝更新，并验证后端也未发布该答案；Esc 只关闭弹层，不隐式取消工作。
- [ ] 8. 扩展 electron-fixture 导出 getPublicFrames(): Promise<unknown[]>，捕获主进程真实发给 renderer 的全部公开帧；emitInternal 返回前等待投影与渲染队列排空。
- [ ] 9. 通过 MutationObserver、可访问性树和 IPC 帧检查一度闪现的英文 canary；内部英文文件只经批准附件下载入口可用。
- [ ] 10. 运行传输层与 GUI 测试，检查正式构建没有场景注入入口；存储脱敏 IPC 样本、取消时间线及截图后提交。

**测试命令：** `python -m pytest tests/integration/test_public_chat_transport.py -q`；`npm run test:e2e -- tests/e2e/chat-publication.spec.ts`。
**预期负例：** 即使组件通过 CSS 隐藏，任何 canary 已进入公开帧也必须失败；取消未确认不得显示已停止或继续发布。
**证据：** `artifacts/acceptance/D025/public-frames.json`；`artifacts/acceptance/D025/dom-mutations.json`；`artifacts/acceptance/D025/cancel-timeline.json`。
**完成条件：** 服务端投影、IPC、DOM 和重连回放四层无内部内容泄漏，正常问答、错误、取消与澄清可用。
**失败回退：** 暂停该连接的新发布并保存内部稿；修复投影后重放同一已批准事件，不把内部消息直接送前端应急。

---

### D026：锁定真实 model_family 的轮次语言路由

**目的 / 负责人 / 估算：** 保证只有实际 Claude 启用翻译，GPT 完全跳过强制翻译，身份不明时先停止。 后端工程师；接入工程师复核；10 工时。
**依赖 / 需求：** D007、D008、D013、D024；R03、R07、R08、R10、R12。
**输入与接口：** 已核验 ProviderIdentity、任务合同版本和连接配置版本；输出不可变 RouteSnapshot 与 needs_translation。
**拟建/修改文件：**
`services/orchestrator/app/translation/router.py`；`services/orchestrator/app/contracts/translation.py`；`services/orchestrator/app/storage/schema/0002_route_snapshots.sql`；`tests/unit/test_language_router.py`；`tests/integration/test_route_snapshot.py`
测试适配注册同时修改：`services/orchestrator/app/providers/fake.py`；`services/orchestrator/app/api/application.py`。

- [ ] 1. 先为“Claude Code 内接 GPT”“其他 App 内接 Claude”“unknown 身份”写反例，沿用主计划 ProviderIdentity 与 needs_translation 的兼容签名。
- [ ] 2. 保留 D007 ProviderIdentity 构造字段不变；RouteSnapshot增加身份依据、connection_version、turn_id、attempt_id、policy_version、locked_at，以(turn_id,attempt_id)唯一；接管生成新attempt，旧快照不可改。
- [ ] 3. 仅从适配器的核验结果创建快照；family 不属于 claude/gpt 或 identity_status 不是 verified 时返回 UNVERIFIED_MODEL_IDENTITY。
- [ ] 4. needs_translation 只比较枚举 model_family；禁止匹配 App 名、配置别名、展示名或用户提问语言推断模型。
- [ ] 5. 在首次执行前以事务保存快照和轮次；规划、修复、翻译、验收、发布全部引用该 route_snapshot_id。
- [ ] 6. 为 GPT 返回 native 并绕过 translator 构造；保留 B 执行功能，统计调用岗位时不能把正常 B 执行算成翻译。
- [ ] 7. 执行事件报告模型身份变化时暂停当前 attempt，撤销发布资格；需要接管则生成新 attempt、合同引用和路由快照。
- [ ] 8. 后续轮次更换模型时按该轮新策略构造历史视图；复用来源映射，不把上轮英文摘要误当完整中文原始需求。
- [ ] 9. 测试重启、并发修改连接和迟到旧身份事件，断言已锁定快照字节内容不被覆盖且未知模型未启动 A。
- [ ] 10. 运行路由与快照测试，保存身份核验来源和调用计数；复核后提交迁移与接口。

**测试命令：** `python -m pytest tests/unit/test_language_router.py tests/integration/test_route_snapshot.py -q`。
**预期负例：** unknown、mismatch、CLI 名称与模型族冲突均不能猜路由；GPT 样例强制 translator 调用数必须为 0。
**证据：** `artifacts/acceptance/D026/route-snapshots.json`；`artifacts/acceptance/D026/provider-calls.json`。
**完成条件：** 每轮路由可追溯且不可变，模型切换不会混淆语言路径，兼容旧 ProviderIdentity 读写。
**失败回退：** 禁用新轮次创建并保留已有快照；迁移失败使用 D008 备份恢复，禁止回填猜测身份。

---

### D027：结构化分段及代码、数字、公式保护

**目的 / 负责人 / 估算：** 建立可完整还原的翻译单元，防止翻译改变可执行代码、证据和数量含义。 翻译后端工程师；领域评审复核保留规则；14 工时。
**依赖 / 需求：** D007、D016、D026；R07、R08、R09、R15。
**输入与接口：** 不可变源文本、格式、任务术语表与源位置；输出 TranslationBlock、ProtectedSpan 和还原检查结果。
**拟建/修改文件：**
`services/orchestrator/app/translation/segments.py`；`services/orchestrator/app/translation/protection.py`；`services/orchestrator/app/contracts/translation.py`；`tests/translation/test_segments.py`；`tests/fixtures/translation/protected.md`

- [ ] 1. 创建 protected.md，包含 Python 代码、Windows 路径、DOI、LaTeX 公式、-0.03、95% 区间及用户自带占位符；先测完整往返一致。
- [ ] 2. Markdown 通过语法树分出标题、段落、代码、表格、链接和公式；普通文本按段落及安全长度切块，不跨句截断否定或条件。
- [ ] 3. 为每块生成稳定 block_id、source_locator、source_sha256、document_version；超长块拆分时记录父块和顺序。
- [ ] 4. 为代码、公式、路径、链接目标和引用标识生成带命名空间的保护标记，保存原始字节、类型、位置和 SHA-256。
- [ ] 5. 先转义用户原文中碰撞的占位串，再插入系统标记；回填要求每个预期标记出现一次，未授权的新标记拒绝。
- [ ] 6. 数字和单位同时记录原字面及归一化语义，允许“95%”与“百分之九十五”等已声明等义呈现；负号、范围方向和单位不可静默变化。
- [ ] 7. 产品代码内中文用户界面字符串按原任务保留；只翻译被标注为可译的说明，避免全局替换改动程序行为。
- [ ] 8. 恢复目标块后验证保护项哈希、出现次数、交叉引用和必要顺序；有缺失、重复、篡改时直接返回可定位错误。
- [ ] 9. 对恶意占位串、嵌套 Markdown、长表格和多字节中文做边界测试；记录未支持语法并阻止静默丢块。
- [ ] 10. 运行分段测试并核对 fixture 的块覆盖，保存差异报告；提交保护协议和版本号供后续缓存使用。

**测试命令：** `python -m pytest tests/translation/test_segments.py -q`。
**预期负例：** B 改动命令、公式变量、负号或丢失占位标记时不能回填成已通过译文；完整原文不得被裁成摘要。
**证据：** `artifacts/acceptance/D027/block-map.json`；`artifacts/acceptance/D027/protected-diff.json`。
**完成条件：** 源文每个可译/保护块都有去向，保护内容可字节验证，数量与引用保持语义。
**失败回退：** 保留不可变原件和解析失败位置，停止该格式翻译；不得退化为全文字符串替换绕过校验。

---

### D028：中文输入完整英译、追问与历史视图

**目的 / 负责人 / 估算：** 使 Claude 接收忠实英文需求和必要资料，同时完整保留用户中文原话及来源。 翻译后端工程师；调度工程师协作；16 工时。
**依赖 / 需求：** D012、D013、D017、D026、D027；R02、R07、R12、R15。
**输入与接口：** RouteSnapshot、TranslationBlock、用户消息、附件索引和 D017 工作区；输出英文上下文清单及输入检查待办。
本卡先支持D027已实现的文本/Markdown解析。PDF/DOCX依赖D032完成后接入同一分块合同；此前明确 unavailable，不建立对后续任务的循环依赖，也不宣称复杂附件已通过。
**拟建/修改文件：**
`services/orchestrator/app/translation/input_pipeline.py`；`services/orchestrator/app/translation/context_gateway.py`；`services/orchestrator/app/translation/prompts/input_translator.txt`；`services/orchestrator/app/translation/history.py`；`tests/integration/test_input_translation.py`

- [ ] 1. 先构造两轮追问 fixture：首轮禁止删除原始文件，次轮只增加 PDF；断言第二轮传给 A 的英文仍保留禁止项且覆盖两条需求。
- [ ] 2. 在 translator 提示中列出完整翻译、保留语气/条件/不确定性、禁止补造与输出 block_id schema；翻译岗位使用独立于 B 执行的上下文。
- [ ] 3. 保存中文 raw_content_ref 和哈希，将全部待译块交 B；输入量过大则分批保留块顺序，不能用摘要替代完成未处理部分。
- [ ] 4. 为中文附件、需要提交 A 的中文检索内容和工具说明建立派生英文视图；原文件、图片和原始数据保留证据引用。
- [ ] 5. translation/context_gateway.py 仅构造语言派生视图，所有 A 文件读取仍经 D017 的 runtime/context_gateway.py 唯一权限网关；关键 OCR 歧义停在 NEEDS_INPUT，不补造字符。
- [ ] 6. 历史按原消息与英文映射读取；命中相同源版本时复用已通过译文，禁止多次中英回译产生语义漂移。
- [ ] 7. A 提出的英文澄清先保存 internal 待翻译记录，输出合同交给统一发布门槛；用户补充作为新输入版本再次翻译，保持任务关联。
- [ ] 8. 记录全文范围与 A 当前读取范围两个字段；A 按索引选择上下文时不得把未读取材料声称已审查。
- [ ] 9. 输入校验未 READY 前调度器不得启动 A；重启恢复先查看已有翻译作业状态，再决定继续或新尝试。
- [ ] 10. 运行两轮历史、附件缺页、中文工具日志、重复提交和截断反例，保存 A 实际收到的请求文件与全文映射后提交。

**测试命令：** `python -m pytest tests/integration/test_input_translation.py -q`。
**预期负例：** 缺一段、遗失首轮约束、OCR 关键字段不明或翻译未通过时 A 请求数为 0；不得改传中文原件绕过失败。
**证据：** `artifacts/acceptance/D028/a-request-context.json`；`artifacts/acceptance/D028/input-block-coverage.json`；`artifacts/acceptance/D028/followup-map.json`。
**完成条件：** 首问、追问、必要历史和资料均有完整英文对应及可追溯原件，跨任务材料不可混入。
**失败回退：** 回到输入准备检查点并保留中文原件；限制未支持附件类型，使用中文必要澄清，不调用 A 修补每句翻译。

---

### D029：翻译 QA、术语表、缓存与有限修复

**目的 / 负责人 / 估算：** 把忠实翻译的校验、错误修复和停止规则落成可审计机制，控制 B 返工并保护 A token。 翻译后端工程师；双语评审与 QA；18 工时。
**依赖 / 需求：** D014、D015、D027、D028；R02、R07、R08、R14、R15。
**输入与接口：** 源块/候选译文、保护项、术语表、预算；输出 TranslationQA、READY/NEEDS_INPUT/FAILED 和缓存记录。
**拟建/修改文件：**
`services/orchestrator/app/translation/quality.py`；`services/orchestrator/app/translation/glossary.py`；`services/orchestrator/app/translation/cache.py`；`services/orchestrator/app/translation/prompts/semantic_checker.txt`；`tests/translation/test_quality_cache.py`；`tests/fixtures/translation/golden.jsonl`；`tests/translation/test_pipeline_contract.py`

- [ ] 1. 写入测试组 B 的 golden.jsonl：否定反转、负号丢失、限定语消失、代码破坏及正确样本；期望 issue code 由双语人员先裁定。
- [ ] 2. C 检查块覆盖、非空/截断、保护标记、数字实体、引用和结构；每个失败保留源/目标位置，不能仅有总分。
- [ ] 3. B 使用独立校验请求逐块对照源文和候选，输出语义问题列表；高影响否定、条件、结论及数量额外逐句检查。
- [ ] 4. 术语表按任务领域、义项和版本维护，变更记录理由与影响块；不能把同一词的不同领域含义强制套用。
- [ ] 5. 缓存键包含 source_sha256、direction、context_sha256、glossary_version、policy_version、translator_model_version；仅缓存 READY 候选。
- [ ] 6. 实现初次生成加两次定点修复，总候选数最多 3；每次只改指出问题并复查受影响块及全局一致性。
- [ ] 7. 连接超时重试与质量候选分别计数；两者均有上限并计入 B 用量，先查上一请求状态避免重复执行。
- [ ] 8. 发现关键歧义时返回 NEEDS_INPUT 和中文必要问题；用完修复次数返回 FAILED，不默认把翻译交给 A 无限复核。
- [ ] 9. 缓存命中后重新检查源依赖和保护项；源文、上下文、模型或术语表变化使缓存失效，同模型自检报告不标成独立真值。
- [ ] 10. 运行质量、预算、歧义和缓存反例；双语评审核对样本并签记录，标明自动检查局限后提交。

**测试命令：** `python -m pytest tests/translation/test_quality_cache.py -q`；`python -m pytest tests/translation/test_pipeline_contract.py -q`。
**预期负例：** 省去 not、将 -0.03 改 0.03、复用旧术语缓存或第 4 次自动修复均必须被阻止；B 自评通过不单独决定 READY。
**证据：** `artifacts/acceptance/D029/translation-qa.json`；`artifacts/acceptance/D029/bilingual-review.csv`；`artifacts/acceptance/D029/cache-invalidation.json`；`artifacts/acceptance/D029/attempt-ledger.json`。
**完成条件：** 结构门槛全部通过、已知重大误译被拦截、歧义可澄清、3 次上限生效；不宣称未来文本绝对零误差。
**失败回退：** 停用问题缓存版本并回到源块重试；保留诊断及已用 token，不删除失败样本来美化准确率。

---

### D030：英文回答完整中译与最终发布门槛

**目的 / 负责人 / 估算：** 确保 Claude 的最终英文回答只在完整中文译文验收后显示，GPT 直接路径不增加翻译。 翻译后端工程师；客户端工程师验证；14 工时。
**依赖 / 需求：** D018、D025、D026、D029；R08、R10、R11、R12、R15。
**输入与接口：** A 的已完成英文回答、A 验收、RouteSnapshot、D029 QA；输出待发布中文内容或中文失败/澄清。
**拟建/修改文件：**
`services/orchestrator/app/translation/output_pipeline.py`；`services/orchestrator/app/translation/prompts/output_translator.txt`；`services/orchestrator/app/runtime/answer_publication.py`；`tests/integration/test_output_translation.py`；`tests/e2e/claude-answer.spec.ts`

- [ ] 1. 先写测试：A 返回带英文 canary 的完整答案，B 三次候选均失败；公开事件必须没有 answer.published。
- [ ] 2. C 捕获 A 正文为 internal 不可变消息，保留请求与完成标记；截断/失败响应不能进入最终回答翻译。
- [ ] 3. 对英文正文完整分块中译，保留标题、列表、代码、数字、证据和不确定性；不可因字数较长只发中文总结。
- [ ] 4. 调用 D029 结构及语义门槛，保存中文版本与英文源哈希；全部块 READY 后才创建可发布候选。
- [ ] 5. 输出门槛同时校验 A 审核有效、轮次未取消、身份快照一致和依赖版本未变化；translated=true 不是发布凭据。
- [ ] 6. 无文件的回答通过 D010 同事务写入公开答案及 outbox；有文档的回答等待 D035 完整交付包，避免先说完成再缺文件。
- [ ] 7. 失败保留 A 原文及检查点，以 request.failed 呈现通用中文文案；显式重试复用同一 A 原件，源文未变时不再调用 A。
- [ ] 8. A 的必要澄清同样完整翻成中文，通过 input.required 展示；被保护的原文术语和代码允许保留其语言。
- [ ] 9. GPT 路径直接使用已批准的用户语言回答，不创建强制 TranslationJob；任何流式显示也只能来自已批准内容。
- [ ] 10. 运行中译、失败、取消迟到、完整性及 GPT 零翻译测试，核对 IPC 载荷；保存发布证据并提交。

**测试命令：** `python -m pytest tests/integration/test_output_translation.py -q`；`npm run test:e2e -- tests/e2e/claude-answer.spec.ts`。
**预期负例：** 英文先闪现后替换、只译摘要、失败仍显示完成、取消后补发均失败；GPT 无显式翻译需求时方向日志为空。
**证据：** `artifacts/acceptance/D030/output-block-map.json`；`artifacts/acceptance/D030/publish-decisions.json`；`artifacts/acceptance/D030/chat-transcript.json`。
**完成条件：** Claude 答案逐块完整中译并经门槛发布，失败重试不重复花 A token，GPT 保持原语言直接路径。
**失败回退：** 撤销未发布候选资格并保留内部原稿；使用中文失败状态，不能临时展示英文或未校验译文。

---

### D031：A 英文原件捕获与真实来源证据

**目的 / 负责人 / 估算：** 让“A 原文档”有真实完整 A 输出依据，并将内容作者、审查者和格式渲染者分开记录。 文档后端工程师；接入与 QA 复核；12 工时。
**依赖 / 需求：** D007、D016、D026、D030；R01、R02、R09、R14。
**输入与接口：** A 响应流、任务/轮次/请求标识、完成标记和验收；输出 CanonicalDocument 与不可变 A 正文证据。
**拟建/修改文件：**
`services/orchestrator/app/documents/canonical.py`；`services/orchestrator/app/documents/provenance.py`；`services/orchestrator/app/contracts/artifacts.py`；`tests/artifacts/test_canonical_provenance.py`；`tests/fixtures/documents/a-response.jsonl`

- [ ] 1. 先建立 A 完整正文、A 仅回复 PASS、B 伪造作者字段、A 响应被截断四种事件流，断言后三者不能形成 A 原件。
- [ ] 2. Claude文档合同 require_a_authored_canonical=true，要求A实际完整输出英文定稿并保留成本；GPT按用户目标语言定稿，来源核验保留但不强制英文。
- [ ] 3. C 从受信适配器响应提取正文，与工具日志分开保存；绑定 provider_profile、model、request、turn、attempt 及完成状态，不采信 B 自报作者。
- [ ] 4. 以原始 UTF-8 正文字节保存 canonical 内容和 SHA-256；原始响应另外归档，完整性哈希只能证明未改动，不能单独证明来源。
- [ ] 5. 分别记录 origin_authors、canonical_issued_by、reviewed_by、rendered_by；若 A 根据 B 草稿定稿，记录 B 草稿依赖而不抹除来源。
- [ ] 6. 将 A 内容定稿与系统格式渲染分开：C 可按确定规则生成 PDF/DOCX，但不得修改正文事实或把渲染器标成内容作者。
- [ ] 7. B 只给出全文且 A 只审核时返回 A_CANONICAL_REQUIRED；保留草稿并安排 A 完整定稿步骤，不把标签改成“A 审定”绕过要求。
- [ ] 8. 文本实质变更创建新的 canonical 版本并撤销关联批准；无语义变化的格式处理必须有转换记录和内容等价检查。
- [ ] 9. 支持长文多段输出时为 A 定稿建立明确 manifest、段序、结尾标记和合并哈希；缺段或重复段必须重新补齐与验收。
- [ ] 10. 运行来源和截断测试，核对 raw_a_output 与 canonical 源一致；保存真实 A 请求证据和用量后提交。

**测试命令：** `python -m pytest tests/artifacts/test_canonical_provenance.py -q`。
**预期负例：** B 改 metadata、A 只说通过、A 流被截断都不能成为英文原件；零字节或缺节长文不能通过。
**证据：** `artifacts/acceptance/D031/provenance.json`；`artifacts/acceptance/D031/raw-a-output.md`；`artifacts/acceptance/D031/canonical-sha256.txt`。
**完成条件：** 每份原件都可追到 A 完整内容响应与固定版本，来源与渲染分离，必要 A 用量完整记账。
**失败回退：** 隔离来源不明版本并撤销发布资格；保留 B 草稿，等待 A 实际定稿，不能仅补伪造哈希或作者标签。

---

### D032：文档块模型与 PDF、DOCX、Markdown 输入解析

**目的 / 负责人 / 估算：** 将不同格式完整解析为可对齐、可定位、可验证的结构，保留原件并阻止静默漏内容。 文档工程师；双语与领域评审；18 工时。
**依赖 / 需求：** D016、D019、D027、D031；R05、R07、R09、R15。
**输入与接口：** 不可变附件/定稿、格式能力检测、原文位置；输出 DocumentModel、DocumentBlock、资源关系和解析缺口。
**拟建/修改文件：**
`services/orchestrator/app/documents/model.py`；`services/orchestrator/app/documents/parse.py`；`services/orchestrator/app/documents/parsers/markdown.py`；`services/orchestrator/app/documents/parsers/docx.py`；`services/orchestrator/app/documents/parsers/pdf.py`；`tests/artifacts/test_document_parse.py`；`tests/fixtures/documents/structure-manifest.json`；`tests/fixtures/documents/build_fixtures.py`

- [ ] 1. 定义 fixture manifest，列出标题、正文、表格单元格、脚注、公式、图注、参考文献、附录和交叉引用的预期块 ID 与原文。
- [ ] 2. DocumentBlock 包含 kind、block_id、parent_id、order、source_locator、source_sha256、content、resource_ids、translatable 和保留理由；序列化版本写入合同。
- [ ] 3. 实现 Markdown AST 到块模型映射，处理代码围栏、链接目标、表格与数学扩展；未知扩展产生明确解析问题而非丢弃。
- [ ] 4. 实现 DOCX 段落/运行、表格、脚注尾注、超链接、图像替代文本与公式的提取；在输入清单中区分正文与嵌入资源。
- [ ] 5. 实现可选取文本 PDF 的阅读顺序和原页/边界框定位，校验跨栏与连字符；扫描页转 OCR 时保留页图、置信度和来源区域。
- [ ] 6. 能力检测决定 DOC 导入转换是否可用；转换前后结构不一致或密码保护无法打开时拒绝接收并说明需要的输入。
- [ ] 7. 解析后的每块关联原始字节哈希及来源位置；附件原件只读保存，解析器不得原地修改用户文件。
- [ ] 8. 验证文本、表格、图注与参考文献覆盖；关键 OCR 字符和公式无法确认时产生 NEEDS_INPUT，禁止按上下文猜数。
- [ ] 9. 用 build_fixtures.py 从结构 manifest 生成正常 DOCX/MD，再固定验收 PDF 和扫描页；损坏、跨栏与复杂表格 fixture 独立保留哈希。
- [ ] 10. 运行解析测试并逐页核对样本，保存提取清单和缺口矩阵；能力未通过的格式不显示已支持。

**测试命令：** `python tests/fixtures/documents/build_fixtures.py --verify`；`python -m pytest tests/artifacts/test_document_parse.py -q`。
**预期负例：** 空正文但存在脚注、PDF 跨栏乱序、OCR 负号不明、损坏 DOCX 均不能被当作完整解析通过。
**证据：** `artifacts/acceptance/D032/parse-manifests.json`；`artifacts/acceptance/D032/source-location-map.json`；`artifacts/acceptance/D032/format-capabilities.json`。
**完成条件：** 首版承诺格式在冻结样本中无已知漏块，源位置可追踪，无法解析项目明确阻止后续完整交付声明。
**失败回退：** 关闭失败格式的导入能力并保留原件；返回中文文件错误或澄清，不将抽取到的部分文本伪装完整内容。

---

### D033：英文原文与中文文档逐块配对生成

**目的 / 负责人 / 估算：** 从真实 A 英文定稿生成完整中文副本，保持结构、证据和语义的一一可追溯对应。 翻译与文档后端工程师；14 工时。
**依赖 / 需求：** D026、D029、D031、D032；R02、R09、R10、R15。
**输入与接口：** CanonicalDocument、DocumentModel、术语表、用户请求格式；输出英文/中文文档模型和未发布配对清单。
**拟建/修改文件：**
`services/orchestrator/app/documents/translate.py`；`services/orchestrator/app/documents/pairs.py`；`services/orchestrator/app/contracts/artifacts.py`；`tests/artifacts/test_bilingual_generation.py`；`tests/fixtures/documents/bilingual-blocks.json`

- [ ] 1. 建立包含正文、表格、脚注、公式说明、引文及附录的 bilingual-blocks.json；先测删除任一必需块均无法生成 READY 配对。
- [ ] 2. 读取 A canonical 只读快照，先核对源哈希和 A 验收版本；不从 B 草稿或目录中最新文件名猜测英文原件。
- [ ] 3. 按 DocumentBlock 的 translatable 标记批量调用 B，要求保留 block_id 和上下文；不可翻译代码/公式/原题保留并记录原因。
- [ ] 4. 每块记录 source_version、target_version、TranslationJob 和 QA，中文不得另起章节替代原文内容或新增推断结论。
- [ ] 5. 重建中文文档树时保留章节、表格与引用关系；中文可以调整自然语序，但引用必须仍指向同一来源与公式。
- [ ] 6. 对图内可译文字生成中文图注或受控替换资源，同时保留原图证据；无法完整本地化且影响理解时阻止声称完整译文。
- [ ] 7. 整篇核对术语、指代、跨章节引用和表格标题，逐块通过不代表全文一致性自动通过。
- [ ] 8. 创建 artifact_pair_id，绑定 source_version_id、目标语言和用户要求的格式集合；此阶段 state=STAGING，不返回可下载文件。
- [ ] 9. GPT 模式若用户未另要求双语，直接产生单语言交付描述，translator 调用数保持 0；代码与数据按原始语义保存。
- [ ] 10. 运行缺块、重复块、版本错配与 GPT 反例，保存完整块对应和译文语义裁决；提交配对生成模块。

**测试命令：** `python -m pytest tests/artifacts/test_bilingual_generation.py -q`。
**预期负例：** 漏译脚注/附录、表格条件改变、中文依赖旧原件或仅中文摘要时不得 READY；GPT 不额外造英文版。
**证据：** `artifacts/acceptance/D033/bilingual-block-map.json`；`artifacts/acceptance/D033/qa-by-block.json`；`artifacts/acceptance/D033/staging-pairs.json`。
**完成条件：** 所有可译块完整处理且全篇一致，英文原件不变，所有配对仍等待渲染与发布门槛。
**失败回退：** 按失败块停留在 STAGING 并保留已通过块；源版本变化时整组标为 STALE，不强行与新原件合并。

---

### D034：PDF、DOCX、Markdown 渲染与版面核验

**目的 / 负责人 / 估算：** 将中英结构分别输出为真实可打开文件，并对中文字体、表格、公式与分页作可核验检查。 文档工程师；视觉 QA；20 工时。
**依赖 / 需求：** D019、D032、D033；R05、R09、R15。
**输入与接口：** 两种语言 DocumentModel、格式请求和锁定渲染能力；输出暂存文件、资源包及每格式渲染报告。
**拟建/修改文件：**
`services/orchestrator/app/documents/render.py`；`services/orchestrator/app/documents/renderers/markdown.py`；`services/orchestrator/app/documents/renderers/docx.py`；`services/orchestrator/app/documents/renderers/pdf.py`；`services/orchestrator/app/validation/document_layout.py`；`tests/artifacts/test_render_layout.py`；`tests/fixtures/documents/layout-cases.json`

- [ ] 1. 建立 layout-cases.json：长中文标题、跨页表格、宽公式、脚注、图片、引用链接与缺字；正常/损坏两套期望独立保存。
- [ ] 2. 锁定可用的 DOCX/PDF 渲染器及字体版本并记录许可证和系统依赖；启动时检测能力，缺工具则该格式不能显示可用。
- [ ] 3. Markdown 渲染保留语法与相对资源路径，连同图片资源生成可携带目录或明确包；验证链接不越出交付范围。
- [ ] 4. DOCX 分别使用中英样式，保留标题层级、表格重复表头、脚注、图题与可用公式；禁止把复杂内容悄悄降成丢信息文本。
- [ ] 5. PDF 使用同一内容模型，嵌入或可靠引用可用中文字体；建立书签/链接/页码，核对导出后文字和资源清单。
- [ ] 6. 允许中英重新分页和不同页数，跨语言定位依赖 block_id；不得为了相同页数缩小字体到不可读。
- [ ] 7. 程序检查页面边界、空白异常、字体替换、表格溢出、公式/图片缺失和引用失效；不把文字抽取成功等同于版面正确。
- [ ] 8. 将两种语言的关键页、复杂表格页和首尾页渲染为图像；人工检查并保存带页号问题记录，修复后重验受影响页面。
- [ ] 9. 注入渲染器崩溃、磁盘不足、文件占用和中文字体缺失，保证输出停留暂存且发布方能看到明确失败。
- [ ] 10. 运行渲染测试，使用实际阅读器抽查 PDF/DOCX 可打开；保存版本、页面图与裁决后提交。

**测试命令：** `python -m pytest tests/artifacts/test_render_layout.py -q`。
**预期负例：** 缺字方框、图表丢失、公式截断、孤立表头、无法打开文件不能通过；页数不同本身不是错误。
**证据：** `artifacts/acceptance/D034/render-environment.json`；`artifacts/acceptance/D034/page-images/`；`artifacts/acceptance/D034/layout-review.csv`；`artifacts/acceptance/D034/render-checks.json`。
**完成条件：** 每个请求格式的两种语言可打开、内容完整且版面经核验；资源和字体依赖有记录。
**失败回退：** 保留结构模型及暂存失败文件供诊断，停用问题渲染能力；不发布半成品或偷偷改变用户请求格式。

---

### D035：双语文件原子发布、版本失效与恢复

**目的 / 负责人 / 估算：** 确保用户始终下载同版本完整双语文件，不会在中断或上游修改后看到新旧混配。 后端工程师；可靠性 QA；18 工时。
**依赖 / 需求：** D010、D012、D016、D030、D031、D033、D034；R09、R11、R12。
**输入与接口：** A 批准、原件/译文/渲染 QA、不可变文件和依赖图；输出可见 DeliveryBundle 与公开发布事件。
**拟建/修改文件：**
`services/orchestrator/app/documents/publish.py`；`services/orchestrator/app/documents/invalidation.py`；`services/orchestrator/app/api/artifacts.py`；`services/orchestrator/app/storage/schema/0003_delivery_bundles.sql`；`tests/artifacts/test_atomic_publication.py`；`tests/integration/test_document_invalidation.py`；`tests/artifacts/test_pair_contract.py`

- [ ] 1. 先发布完整 v1，再注入 v2 英文已写、中文未写故障；读取接口必须只能看见完整 v1，不能看见 v2 半配对。
- [ ] 2. 定义 DeliveryBundle.format_pairs：artifact_pair_id、format、source_version_id、english_artifact_id、chinese_artifact_id；数据库检查两者同源、同任务、同请求。
- [ ] 3. 文件先在受控同卷暂存目录完成写入和刷盘，再迁入内容寻址不可变目录；禁止先发文件卡再等待文件生成。
- [ ] 4. 发布前复核文件存在、实际字节哈希、源版本、A 来源、QA、批准和未取消状态；每种请求格式均须完整两份。
- [ ] 5. 使用一笔数据库事务切换可见 bundle 指针并写 answer.published/artifacts.published outbox；事件携带同一 bundle_id、turn_id 和版本。
- [ ] 6. 外部文件操作与数据库并非一个事务，设计恢复对账：未引用完整 blob 可回收，已提交引用缺文件视为损坏并停止对外可见。
- [ ] 7. 原件或上游数据改变时创建新版本，通过依赖图令译文、图表、渲染和批准 STALE；已发布旧完整版本保留历史标签。
- [ ] 8. 下载和重发依据不可变 artifact_id 与 bundle_id，核验作用域；不根据文件名相似、目录时间或最新缓存临时配对。
- [ ] 9. 在写文件、校验、事务提交和 outbox 发送前后逐点中断，加入 Windows 文件占用与重启；观察者只能读到旧完整组或新完整组。
- [ ] 10. 运行原子发布和依赖失效测试，检查实际文件哈希、事务日志、事件次数；复核清理策略不会删已发布文件后提交。

**测试命令：** `python -m pytest tests/artifacts/test_atomic_publication.py tests/integration/test_document_invalidation.py -q`；`python -m pytest tests/artifacts/test_pair_contract.py -q`。
**预期负例：** v3 英文配 v2 中文、缺一格式、取消后的新结果、来源未知和缺失 blob 均不能发布；重发不重复生成 A 内容。
**证据：** `artifacts/acceptance/D035/visible-manifests.json`；`artifacts/acceptance/D035/crash-point-matrix.csv`；`artifacts/acceptance/D035/dependency-invalidation.json`。
**完成条件：** 所有可见配对实际存在且哈希/版本一致，崩溃可对账，回复和文件共用同一次批准。
**失败回退：** 保持上一已发布完整指针，隔离损坏新包并回到 STAGING；不可覆盖旧原件或删除数据库掩盖半发布。

---

### D036：文件卡、隔离预览、保存单份与双份

**目的 / 负责人 / 估算：** 让用户清楚识别英文原件/中文译文，并可靠预览、保存同一版本的交付文件。 客户端工程师；文档与安全 QA；14 工时。
**依赖 / 需求：** D021、D022、D025、D034、D035；R06、R09、R11、R12。
**输入与接口：** 公开 ArtifactCard/ArtifactPair DTO、受限预览与下载 API；输出文件卡、文档预览和系统保存交互。
**拟建/修改文件：**
`apps/desktop/src/renderer/chat/ArtifactPair.tsx`；`apps/desktop/src/renderer/chat/ArtifactCard.tsx`；`apps/desktop/src/renderer/documents/DocumentPreview.tsx`；`apps/desktop/src/main/artifact-files.ts`；`apps/desktop/src/main/ipc.ts`；`tests/e2e/artifact-files.spec.ts`

- [ ] 1. 先为同版本双语组、GPT 单文件、历史版本、预览失败和损坏文件建立界面场景；卡片配对只读 artifact_pair_id。
- [ ] 2. ArtifactPair 显示标题、格式、版本、英文原文/中文译文以及预览、保存、保存两份；同一请求多格式分组清晰。
- [ ] 3. ArtifactCard 处理 GPT 默认单语言、代码包、数据和图片，不能为非文字数据自动制造翻译副本。
- [ ] 4. PDF 预览隔离加载固定 artifact_id 资源；DOCX 使用已校验的派生预览并注明是预览，下载仍为原始 DOCX。
- [ ] 5. Markdown 禁用不可信 HTML/脚本并限制资源到当前 bundle；外部链接经明确点击走系统浏览器，禁止自动导航。
- [ ] 6. 双语预览设置正确 lang，页码依各自文档，必要时按 block_id 跳转对应章节；关闭预览回到触发文件卡的焦点。
- [ ] 7. 保存动作走主进程系统对话框，由用户选目录；后端只提供受控文件流，renderer 无任意文件路径写权限。
- [ ] 8. “保存两份”固定同 bundle 版本，预检重名、可写目录和空间，临时写完整后改名；失败清理本次临时文件并报告已保存项。
- [ ] 9. 预览能力暂不可用但原文件已验证时允许保存并显示说明；文件本体损坏则撤销可交付状态，不以预览失败文案掩盖。
- [ ] 10. 运行预览安全、键盘、保存取消、重名、文件占用和两个语言版本测试，记录下载字节哈希与截图后提交。

**测试命令：** `npm run test:e2e -- tests/e2e/artifact-files.spec.ts`。
**预期负例：** 未发布 artifact_id、越权任务文件、恶意 Markdown 链接、保存取消、双份中途写失败不得显示全部保存成功。
**证据：** `artifacts/acceptance/D036/saved-file-hashes.json`；`artifacts/acceptance/D036/screenshots/`；`artifacts/acceptance/D036/save-failures.json`。
**完成条件：** 用户可预览/保存各格式同版本双语文件；GPT 单语言正确；保存失败不重跑模型。
**失败回退：** 禁用受影响预览器但保留已验证文件的受限保存；损坏文件整组停止交付，保留故障版本供修复。

---

### D037：独立用量、存储偏好与脱敏诊断页面

**目的 / 负责人 / 估算：** 提供可核对的 A/B 用量和可管理的本地存储，同时保持主聊天简洁。 客户端与后端工程师；QA 核账；20 工时。
**依赖 / 需求：** D009、D015、D021、D022、D024、D035；R02、R06、R12、R14。
**输入与接口：** D015 请求级账本、储存目录/空间 API、脱敏诊断合同；输出 /usage 与设置页面。
本卡提供 `GET /v1/usage` 的过滤/分页与口径字段、`GET /v1/storage` 占用/引用状态、`POST /v1/storage/cleanup-preview` 的候选清单及 `POST /v1/storage/cleanup` 的版本化清理请求。偏好使用 D024 settings API；目录迁移提供预检与执行入口，先暂停写入、逐文件校验再切换，失败保留原目录。上述路径只通过主进程业务IPC公开；D051另接实际备份恢复。
**拟建/修改文件：**
`apps/desktop/src/renderer/settings/Usage.tsx`；`apps/desktop/src/renderer/settings/Storage.tsx`；`apps/desktop/src/renderer/settings/Preferences.tsx`；`apps/desktop/src/renderer/settings/Diagnostics.tsx`；`services/orchestrator/app/api/diagnostics.py`；`tests/e2e/settings-usage.spec.ts`；`tests/integration/test_diagnostics_export.py`
后端同时修改：`services/orchestrator/app/api/usage.py`；`services/orchestrator/app/api/storage.py`；`services/orchestrator/app/api/settings.py`；`services/orchestrator/app/api/application.py`；`services/orchestrator/app/storage/cleanup.py`；`services/orchestrator/app/storage/relocate.py`；`apps/desktop/src/main/ipc.ts`；`tests/integration/test_storage_settings.py`。

- [ ] 1. 建立账本 fixture，含成功、失败、重试、缓存、B 翻译/B 执行、累计计数和缺失值；先测缺失不能显示为 0。
- [ ] 2. Usage 按日期、任务、A/B 与岗位筛选，显示输入/输出/缓存等提供商真实口径；估算字段显式标“估算”。
- [ ] 3. 将“每次合格交付 A token”分母绑定合格交付，分子包括失败和返工；零交付时显示不可计算，不显示 0 消耗。
- [ ] 4. 只有存在批准的独立基准报告且计量可比时才显示节省率；当前无证据状态明确写未评测，不能算 B 更便宜就声称智能等效。
- [ ] 5. 实现存储统计与清理后端，Storage先展示可删候选；执行时重核引用及版本，不删除活跃任务、已发布或备份依赖的blob。
- [ ] 6. 偏好页提供主题、字号、发送快捷键和导出目录；目录变更时由后端受控迁移/核验，UI 不直接搬动运行中文件。
- [ ] 7. Diagnostics 导出版本、能力矩阵、错误代码、用量和脱敏日志；默认不带密钥、完整用户正文、内部提示或原始模型回答。
- [ ] 8. 需要包含原始诊断材料时列明内容并取得具体用户选择；导出目标由保存对话框指定，不自动上传外部服务。
- [ ] 9. 页面访问独立于聊天流；设置操作失败用页面内中文提示，主聊天不得出现 token 数字或内部模块日志。
- [ ] 10. 运行用量核账、缺失值、存储引用与凭据 canary 扫描，保存脱敏样包和页面截图后提交。

**测试命令：** `python -m pytest tests/integration/test_diagnostics_export.py tests/integration/test_storage_settings.py -q`；`npm run test:e2e -- tests/e2e/settings-usage.spec.ts`。
**预期负例：** 重复累计计数、null→0、无基准节省百分比、诊断包含凭据或删除活跃成果均为失败。
**证据：** `artifacts/acceptance/D037/usage-reconciliation.json`；`artifacts/acceptance/D037/redacted-diagnostics.zip`；`artifacts/acceptance/D037/screenshots/`。
**完成条件：** 用量与后端账本一致，未知/估算可辨认，存储操作保护引用关系，主聊天无内部诊断内容。
**失败回退：** 关闭问题导出/删除入口，账本原始事件只读保存；不得重算成更好看的数字或自动清理用户成果。

---

### D038：编程、论文与普通文档任务 profile 接入

**目的 / 负责人 / 估算：** 用领域合同指定 A 的关键判断、B 的执行和验证职责，保证通用流程能完成真实不同任务。 调度工程师；编程/学术/文档评审；18 工时。
**依赖 / 需求：** D013、D014、D019、D030、D035、D036；R01、R02、R05、R09、R15。
**输入与接口：** D013 TaskContract、D019 validators、A 审核与交付规则；输出三个版本化 profile 及验收合同。
**拟建/修改文件：**
`services/orchestrator/app/profiles/registry.py`；`services/orchestrator/app/profiles/code.yaml`；`services/orchestrator/app/profiles/paper.yaml`；`services/orchestrator/app/profiles/document.yaml`；`tests/integration/test_task_profiles.py`；`tests/fixtures/profiles/requests.json`

- [ ] 1. 在 requests.json 给每类一个正常请求和一个关键缺口：代码越界、论文缺证据、文档受众未定；先断言缺口不会机械标为通过。
- [ ] 2. profile schema 定义 required_inputs、deliverables、A_decisions、B_actions、mechanical_checks、semantic_reviews、escalation 和 budgets。
- [ ] 3. code profile 要求 A 审关键设计与异常行为，B 实现/运行测试；构建通过只完成机械项，代码包和双语说明分别管理。
- [ ] 4. paper profile 要求来源可追、数据可复算、方法与结论相符；不补造文献或统计，A 处理研究问题、论证与结果解释。
- [ ] 5. document profile 固定受众、用途、结构、事实来源和输出格式；结构字段齐全不替代 A 对表达和可用性的检查。
- [ ] 6. 任务类型由用户选择或 B 提议、A 在合同中确认；混合任务可组合 profile，不按关键字直接降低审查等级。
- [ ] 7. 每个必需验收项有负责角色、证据 ID 和成果版本；只有所有机械/语义必需项通过才能请求发布。
- [ ] 8. 把常规执行、关键节点指导、A 接管困难部分映射为 profile 可升级策略；不设置全局只允许调用 A 两次。
- [ ] 9. 论文和文档 Claude 路径启用 A 完整英文原件及中文副本；GPT 按用户语言和格式，不附加强制双语成本。
- [ ] 10. 运行三类合同和失败案例，领域评审核对标准是否覆盖真实质量；保存 profile 版本和样例合同后提交。

**测试命令：** `python -m pytest tests/integration/test_task_profiles.py -q`。
**预期负例：** 测试全绿但漏需求、引用存在但不支持论点、缺数据仍写确定结论不能通过；B 自报完成不得写 PASS。
**证据：** `artifacts/acceptance/D038/profile-contracts.json`；`artifacts/acceptance/D038/domain-review.md`；`artifacts/acceptance/D038/requirement-evidence-map.json`。
**完成条件：** 三类任务按相同调度协议生成不同的真实验收合同，必要 A 判断未被格式检查替代。
**失败回退：** 对未验证领域启用保守 A 主导配置并保留证据，不宣称该领域已证明等效或节省。

---

### D039：数据→代码→图表→报告的综合依赖用例

**目的 / 负责人 / 估算：** 验证综合成果来自同一数据和方法版本，上游修改会正确使下游结果与双语报告失效。 数据/后端工程师；领域 QA；18 工时。
**依赖 / 需求：** D016、D019、D032、D034、D035、D038；R01、R05、R09、R12、R15。
**输入与接口：** 冻结 CSV、数据字典、综合 profile 与依赖版本图；输出可复算代码、图表、双语报告及完整证据。
**拟建/修改文件：**
`tests/fixtures/composite/sales.csv`；`tests/fixtures/composite/request.zh.md`；`tests/fixtures/composite/expected.json`；`tests/integration/test_composite_workflow.py`；`services/orchestrator/app/profiles/composite.yaml`；`tests/support/scenarios/composite.py`

- [ ] 1. 写入四行 sales.csv：2026-01 A 10、2026-01 B 20、2026-02 A 15、2026-02 B 25；数据字典说明 amount 为同一计量单位。
- [ ] 2. request.zh.md 要求按月汇总、报告月增量并给复现代码和图表，禁止补造数据；expected.json 固定 30、40、增加 10。
- [ ] 3. composite profile 建立 source_data→analysis_code→computed_results→figures→report_en→report_zh→delivery 的显式依赖。
- [ ] 4. A 先确认聚合与比较方法，B 执行计算和绘图；C 在固定工作区独立运行分析代码并比对冻结数值。
- [ ] 5. 图表保存所用数据哈希、代码版本和参数；正文每个关键数字关联 computed_results 的字段，不能手填旧结果。
- [ ] 6. 报告经 A 审核并完整输出英文定稿，B 全文中译；C 渲染请求格式，并把代码/CSV/图表作为原语义附件一起交付。
- [ ] 7. 先完成并发布 v1，再将最后一个数值从 25 改 35 形成 v2；预期第二月 50、增量 20，下游全部标 STALE。
- [ ] 8. 重跑必要计算/图表/报告/译文与审核，确认 v2 中英均引用新值，已发布 v1 仍可历史查看。
- [ ] 9. 注入图表生成失败、代码使用旧 CSV、报告保留旧结论三类负例；任一失败阻止新 bundle 发布。
- [ ] 10. 运行综合依赖用例，人工核对图表与双语正文，再保存代码输出、依赖图、版本清单及故障证据后提交。

**测试命令：** `python -m pytest tests/integration/test_composite_workflow.py -q`。
**预期负例：** v2 图表配 v1 报告、数据已变但 A PASS 沿用、CSV 少行仍报告完整都必须阻止发布。
**证据：** `artifacts/acceptance/D039/reproduction-output.json`；`artifacts/acceptance/D039/dependency-graph.json`；`artifacts/acceptance/D039/bundle-v1.json`；`artifacts/acceptance/D039/bundle-v2.json`。
**完成条件：** 真实计算可复跑、所有下游版本一致，上游变更正确触发复验，最终文件与公开回复同版本。
**失败回退：** 保持 v1 完整交付可见，v2 停留内部修复；不得覆盖 v1 数据或直接改报告数字跳过计算与 A 复验。

---

### D040：真实 GUI→A/B→验证→双语交付垂直贯通

**目的 / 负责人 / 估算：** 在用户实际 Claude Code/ZCode 环境走完可复核产品链路，明确区分功能通过与尚未证明的质量/节省资格。 集成负责人；QA 与领域评审共同验收；20 工时。
**依赖 / 需求：** D020、D025、D026、D029、D030、D035、D036、D037、D038、D039；R01、R02、R03、R04、R05、R06、R07、R08、R09、R10、R11、R12、R14、R15。
**输入与接口：** D020 真实能力证据、已装配全部产品门槛、四类冻结任务和连接配置；输出真实垂直贯通报告。
**拟建/修改文件：**
`tests/integration/test_vertical_real.py`；`tests/e2e/vertical-real.spec.ts`；`tests/support/run-real-e2e.mjs`；`tests/support/scenarios/vertical_real.py`；`package.json`；`docs/acceptance/vertical-scenarios.json`；`docs/acceptance/vertical-report.md`

- [ ] 1. 冻结代码、论文、普通文档、综合各一例输入、输出格式和验收项；报告记录模型版本、入口、环境、时间与任务预算。
- [ ] 2. 先执行全部 fake 契约测试排除可确定故障，再启动测试构建 Electron 连接真实 Claude Code 和 ZCode/GLM；报告标记 provider_mode=real。
- [ ] 3. 从 GUI 上传真实材料并中文发问，核对 A 实际收到的英文等义内容、B 执行记录与原始用户中文保存一致。
- [ ] 4. 完成至少一轮 A 指定返修与一次必要澄清，检查 B 修复后仅批准新固定版本，主聊天只见中文问题/回答。
- [ ] 5. Claude 四类任务均核对中文最终答复；请求文档者下载 A 英文原件与 B 中文译文，并验证来源请求、全文块映射和文件哈希。
- [ ] 6. 使用已配置 GPT 真实入口跑中文问答及一个文档任务，断言 translator 强制调用为 0；入口不可用时记功能缺口并禁止声称 GPT 已验收。
- [ ] 7. 在运行中取消一例并重启一例，核对外部执行次数、恢复状态、消息去重和无迟到发布；故障时保留实际检查点。
- [ ] 8. 下载双语文件后在实际阅读器打开，运行代码成果及综合复算；领域评审检查关键质量，不只看 GUI 显示成功。
- [ ] 9. 对账 A/B 输入、输出、缓存、失败返修及翻译用量；无真实用量则标不可得/估算，不在此小样本中宣称等效或节省。
- [ ] 10. 运行真实集成测试与桌面场景，附批准文件、脱敏请求、公开帧和评审结论；缺连接/缺证据标未通过，移交 D041 之后发布质量阶段。

**测试命令：** `python -m pytest -o addopts='' tests/integration/test_vertical_real.py -m real_provider -q`；`npm run test:e2e:real -- tests/e2e/vertical-real.spec.ts`。
本卡在package.json定义 `test:e2e:real` 运行 run-real-e2e.mjs；脚本通过参数数组启动Playwright，只对子进程设置 `AIBROKER_REAL_PROVIDERS=1`。普通 `test:e2e` 排除真实场景；真实fixture未见开关即拒绝启动外部模型。全部Python真实场景统一使用D002的 `real_provider` 标记。
**预期负例：** 仅 fake、人工复制交接、手动改完成状态、没有真实 ZCode 运行或 GPT 未连接均不能把相应功能标已通过。
**证据：** `artifacts/acceptance/D040/real-provider-calls.json`；`artifacts/acceptance/D040/public-transcript.json`；`artifacts/acceptance/D040/downloaded-manifests.json`；`artifacts/acceptance/D040/usage-ledger.json`；`docs/acceptance/vertical-report.md`。
**完成条件：** 真实产品路径和声明支持的连接完成四类任务且故障可恢复；功能证据齐全，质量等效/节省资格留待独立评测。
**失败回退：** 停止新任务并保留已完成版本，按失败所属卡返回修复；不得用 mock 替换真实失败来通过或关闭强制验收门槛。

---

## 代表性测试与 fixture：可复制到未来测试文件

以下代码是完整测试示例，不是产品实现。场景驱动必须调用实际服务并读取真实事件/文件；不能硬编码结果来满足断言。fake 只替代外部模型响应，数据库、调度、翻译门槛、发布和 GUI 使用真实产品代码。

### 测试组 A：公开传输边界与中文输入法（D023、D025）

文件：`tests/e2e/chat-publication.spec.ts`。D021 fixture 导出 test/expect、chatPage；D025 增加 emitInternal 和 getPublicFrames。
每个测试使用独立 fake-gpt 会话。emitInternal({type,text}) 经测试进程注入后端内部事件，等待公开投影、IPC 和渲染排空；getPublicFrames 返回实际发往 renderer 的全部公开载荷。
页面定位合同：`chat-messages` 为消息容器，`composer-text` 为 textarea，`user-message` 为用户消息行。测试专用入口只存在测试构建。

```typescript
import { test, expect } from "../support/electron-fixture";

test("内部内容从未传给聊天页面", async ({
  chatPage, emitInternal, getPublicFrames
}) => {
  await chatPage.evaluate(() => {
    const leaks: string[] = [];
    Reflect.set(window, "qaLeaks", leaks);
    const root = document.querySelector('[data-testid="chat-messages"]');
    if (!root) throw new Error("缺少聊天容器");
    new MutationObserver(records => {
      for (const record of records) {
        const text = [record.target.textContent,
          ...Array.from(record.addedNodes, n => n.textContent)].join("");
        if (text.includes("INTERNAL_ENGLISH_CANARY")) leaks.push(text);
      }
    }).observe(root, { subtree: true, childList: true, characterData: true });
  });
  for (const type of ["model.delta", "tool.delta", "translation.delta"]) {
    await emitInternal({ type, text: "INTERNAL_ENGLISH_CANARY" });
  }
  expect(JSON.stringify(await getPublicFrames())).not.toContain("INTERNAL_ENGLISH_CANARY");
  expect(await chatPage.evaluate(() => Reflect.get(window, "qaLeaks"))).toEqual([]);
  await expect(chatPage.getByTestId("chat-messages")).not.toContainText("tool.delta");
});

test("组合输入 Enter 不提交，结束后只提交一次", async ({ chatPage }) => {
  const input = chatPage.getByTestId("composer-text");
  await input.dispatchEvent("compositionstart");
  await input.fill("请保留原文件");
  await input.dispatchEvent("keydown", { key: "Enter", code: "Enter", isComposing: true });
  await expect(chatPage.getByTestId("user-message")).toHaveCount(0);
  await input.dispatchEvent("compositionend", { data: "请保留原文件" });
  await input.press("Enter");
  await expect(chatPage.getByTestId("user-message")).toHaveCount(1);
  await expect(chatPage.getByTestId("user-message")).toHaveText("请保留原文件");
});
```

### 测试组 B：路由、忠实度门槛与失败停止（D026–D030）

D029 建 `tests/fixtures/translation/golden.jsonl`，以下每行是完整 JSON。真实语义评测另用未参与提示调优的保留样本，下面已知样本不能证明通用零误差。
此schema与D043共用；后续扩展按唯一id追加，不覆盖既有样本。`negative_candidate`为可选，缺省测试approved_reference；`expected_issues`始终为数组。

```jsonl
{"id":"neg-num","direction":"en-zh","source":"Do not release when delta < -0.03.","approved_reference":"当差值小于 -0.03 时，禁止发布。","protected_spans":[],"required_facts":["prohibition","threshold=-0.03"],"ambiguities":[],"negative_candidate":"当差值小于 0.03 时允许发布。","expected_issues":["NEGATION_CHANGED","NUMBER_CHANGED"]}
{"id":"uncertain","direction":"en-zh","source":"This may improve accuracy; it has not been proven.","approved_reference":"这可能提高准确率；但尚未得到证明。","protected_spans":[],"required_facts":["uncertainty","not_proven"],"ambiguities":[],"negative_candidate":"这已经被证明能提高准确率。","expected_issues":["UNCERTAINTY_CHANGED"]}
{"id":"valid","direction":"en-zh","source":"Keep the original file. The estimate is 95%.","approved_reference":"保留原文件。估计值为 95%。","protected_spans":[],"required_facts":["preserve_original","estimate=95%"],"ambiguities":[],"expected_issues":[]}
```

CASE 合同：translation_route(provider,turns,adapter_alias?,identity_status?,omit_input_block?,fail_output?) 输出 translation_directions、a_received、a_call_count、published_answers、candidate_attempts、state。
translation_semantics(source,candidate) 输出 publishable、issues；fake 语义校验响应只验证门槛是否消费错误报告，D029 的人工裁决与 D040 的真实模型记录另行验收。
translation_cache(source,glossary_versions) 输出 cache_keys、cache_hits；术语版本不同不得命中。文件：`tests/translation/test_pipeline_contract.py`。

```python
import json
from pathlib import Path
import pytest

CASES = [json.loads(line) for line in
         Path("tests/fixtures/translation/golden.jsonl").read_text(encoding="utf-8").splitlines()]

@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_semantic_findings_control_publication(probe, case):
    candidate = case.get("negative_candidate", case["approved_reference"])
    result = probe("translation_semantics", source=case["source"], candidate=candidate)
    assert set(case["expected_issues"]) <= set(result["issues"])
    assert result["publishable"] is (not case["expected_issues"])

def test_gpt_inside_claude_named_app_has_no_forced_translation(probe):
    result = probe("translation_route", provider="gpt", adapter_alias="claude_code", turns=2)
    assert result["translation_directions"] == []
    assert result["published_answers"] == 2

def test_unknown_identity_never_calls_a(probe):
    result = probe("translation_route", provider="unknown", identity_status="unknown", turns=1)
    assert result["a_call_count"] == 0
    assert result["state"] == "BLOCKED"

def test_input_omission_blocks_a(probe):
    result = probe("translation_route", provider="claude", turns=1, omit_input_block=True)
    assert result["a_call_count"] == 0
    assert result["published_answers"] == 0

def test_failed_output_stops_after_three_candidates(probe):
    result = probe("translation_route", provider="claude", turns=1, fail_output=True)
    assert result["candidate_attempts"]["output"] == 3
    assert result["published_answers"] == 0
    assert result["state"] == "FAILED"

def test_glossary_change_invalidates_cache(probe):
    result = probe("translation_cache", source="The bank is stable.", glossary_versions=["1", "2"])
    assert result["cache_keys"][0] != result["cache_keys"][1]
    assert result["cache_hits"] == [False, False]
```

运行：`python -m pytest tests/translation/test_pipeline_contract.py -q`；先使 missing-block 和 failed-output 反例命中真实门槛断言，再实现/修复。

### 测试组 C：来源真实性与原子文件对（D031–D035）

D032 的 `structure-manifest.json` 最小源 fixture 如下；build_fixtures.py 使用锁定工具生成文件并验证相同语义块，测试 PDF 固定页图与文件哈希后入库。

```json
{"version":1,"blocks":[
 {"id":"h1","kind":"heading","text":"Results"},
 {"id":"p1","kind":"paragraph","text":"The change is -0.03; causation has not been established."},
 {"id":"t1","kind":"table","cells":[["Month","Amount"],["Jan","30"],["Feb","40"]]},
 {"id":"eq1","kind":"formula","text":"y = x^2"},
 {"id":"fn1","kind":"footnote","text":"Amounts use the same unit."},
 {"id":"app1","kind":"appendix","text":"Keep the original data."}
]}
```

artifact_publication(fault) 先发布 v1 再尝试 v2；返回 source_actor、raw_a_output、english_original、rejected_codes、visible_manifests。
raw_a_output/english_original 指本轮原始 A 正文与未渲染 Markdown 原件；PDF 字节不要求与正文相同。manifest 含 roles、pair_versions、files[{path,sha256}]。
故障枚举新增 b_authored_only、approval_only、stale_translation；历史字段保持兼容。文件：`tests/artifacts/test_pair_contract.py`。

```python
import hashlib
from pathlib import Path
import pytest

def test_interruption_keeps_only_complete_previous_pair(probe):
    result = probe("artifact_publication", fault="after_english_before_chinese")
    assert result["source_actor"] == "A"
    assert Path(result["english_original"]).read_bytes() == Path(result["raw_a_output"]).read_bytes()
    assert result["visible_manifests"]
    for manifest in result["visible_manifests"]:
        assert manifest["pair_versions"] == ["v1", "v1"]
        assert set(manifest["roles"]) == {"english_original", "chinese_translation"}
        for item in manifest["files"]:
            assert hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest() == item["sha256"]

@pytest.mark.parametrize("fault,code", [
    ("b_authored_only", "A_CANONICAL_REQUIRED"),
    ("approval_only", "A_CANONICAL_REQUIRED"),
    ("stale_translation", "SOURCE_VERSION_MISMATCH"),
])
def test_false_origin_or_stale_translation_cannot_publish(probe, fault, code):
    result = probe("artifact_publication", fault=fault)
    assert code in result["rejected_codes"]
    assert all(m["pair_versions"] == ["v1", "v1"] for m in result["visible_manifests"])
```

运行：`python -m pytest tests/artifacts/test_pair_contract.py -q`；保存各中断点的实际文件和事务记录，不只保留通过截图。

### 测试组 D：综合 fixture 与真实产品贯通（D039、D040）

`tests/fixtures/composite/sales.csv` 内容为 `month,category,amount\n2026-01,A,10\n2026-01,B,20\n2026-02,A,15\n2026-02,B,25\n`，以实际换行保存 UTF-8。
`expected.json` 内容为 `{"v1":{"2026-01":30,"2026-02":40,"delta":10},"v2":{"2026-01":30,"2026-02":50,"delta":20}}`。
`request.zh.md` 内容为“请按月汇总金额并比较增量，提供可复现代码、图表以及 PDF 报告；保留原始数据，不得补造观测。”
D024/D040 从已核验设置导出 `docs/acceptance/real-profile-ids.json`，只含 claude、gpt、glm 三个实际 profile ID；缺连接记录缺口，不能用示例假 ID 或凭证填入。
vertical_real(domain,profile_ids,required_mode,budget_seconds) 从真实 GUI/服务启动任务，返回 provider_mode、providers、state、all_required_checks_passed、artifact_pairs、forced_translator_calls_gpt、evidence_paths。
场景最长运行时间由 budget_seconds 控制并小于 probe 的 600 秒测试进程超时；真实小样例超时记失败，完整长任务另列运行报告。文件：`tests/integration/test_vertical_real.py`。

```python
from pathlib import Path
import pytest

@pytest.mark.real_provider
@pytest.mark.parametrize("domain", ["code", "paper", "document", "composite"])
def test_real_product_path_has_required_evidence(probe, domain):
    profiles = Path("docs/acceptance/real-profile-ids.json")
    assert profiles.is_file(), "真实连接尚未完成，不能把本项记为通过"
    result = probe("vertical_real", domain=domain, profile_ids=str(profiles.resolve()),
                   required_mode="real", budget_seconds=480)
    assert result["provider_mode"] == "real"
    assert {"claude", "glm", "gpt"} <= set(result["providers"])
    assert result["state"] == "PUBLISHED"
    assert result["all_required_checks_passed"] is True
    assert result["forced_translator_calls_gpt"] == 0
    assert result["evidence_paths"]
    assert all(Path(path).is_file() for path in result["evidence_paths"])
    for pair in result["artifact_pairs"]:
        assert pair["source_version_id"] == pair["translated_from_version_id"]
        assert pair["canonical_issued_by"] == "A"
        assert Path(pair["english_path"]).is_file()
        assert Path(pair["chinese_path"]).is_file()
```

运行：`python -m pytest -o addopts='' tests/integration/test_vertical_real.py -m real_provider -q`；真实外部调用属于 D040 执行范围，不能在编写本计划时自动运行。
真实场景结果必须由适配器事件、QA、数据库和下载文件计算，不能由报告作者直接填写 true；截图与 GUI 录像由 vertical-real.spec.ts 同步保存。
本组只证明限定样例的软件功能路径，不证明总体“A 等效且省 token”。后者由独立质量/节省评估与发布阶段决定。
以上代表性真实测试针对同时声明Claude与GPT可用的完整候选；未连接GPT时，本例保留未验证，Claude路径可另存限定范围报告，不能填假profile或删除断言后宣称GPT已交付。

