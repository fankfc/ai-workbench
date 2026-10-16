# 阶段二桌面实施与验证

日期：2026-10-14（Asia/Shanghai）。范围：D021–D025、D036–D038 桌面 UI，以及 D040 真实入口的资格预检。Git 未有初始提交，未提交或修改 Python 产品文件，真实模型调用为零。

可启动入口：先 `npm run build:desktop`，然后 `npm run desktop`（real，本机无合格连接，禁止发送）；`npm run desktop:demo` 使用明确标识的固定演示响应。测试先构建正式及测试两个产物，再运行实际 Electron 测试。

## 产品结果

- Electron 隔离 main/preload/renderer；窄业务 IPC 同时校验 sender、主 frame、本地来源和 DTO 输入；公开事件再次按严格白名单过滤。令牌仅在 main 内存及所属 Python 子进程环境，不进入 URL、renderer、普通日志。Python 只接收 OS 环境白名单。静态打包资源使用受限 `workbench://desktop` 来源，不能读取任意路径或访问外部网络。
- Python 动态回环端口、实例 ID、协议、PID 所属关系及健康握手均核验；Windows venv redirector 仅接受其实际直接子进程。健康失败、提前退出、旧实例与连续失败均不显示已连接。单实例只聚焦原窗口；退出先 checkpoint，再使用固定系统路径结束所属进程树，确认 shim 和服务 PID 已退出。旧 child 迟到 exit 不能改变新实例；清理失败记录 `cleanup_confirmed:false` 并阻止重复启动。
- 中文聊天、每会话草稿、IME 组合键防误发、提交键幂等、历史、搜索/分页/改名/置顶/归档/明确删除；实际选中文件由 main 上传，不接收 renderer 文件路径。公开回答只有已批准消息；事件去重、旧轮次与取消后的迟到回答有单元反例。取消文案区分请求已记录与外部确认。
- 连接状态来自实际后端注册与核验；演示标签清楚，真实未知/未配置身份禁止发送且保留草稿。偏好包括主题、14–22px 正文、快捷键、关闭行为。默认导出目录由系统对话框选择，完整路径只在 main 的本地配置，renderer 只收到目录名称。
- 文件按同一 bundle / artifact_pair_id / 格式 / 版本配对。Markdown 安全文本/代码展示，PDF 本地 worker 绘制，DOCX 使用后端真正生成并校验的派生 PDF。双语保存先核对实际大小与 SHA-256，临时写入并独占发布，不覆盖已有文件；第二份失败会回滚，若回滚被文件系统拒绝则明确列出仍已保存的名称。
- 用量保留未知计量、总量下界、失败/返工岗位、输入/输出/缓存及提供方缓存口径；不直接把分量相加，不显示未经评测节省率。存储清理先预览并确认；迁移只接受 main 选择的目录，API 核验副本后 checkpoint/停树/更换私有配置/重启；原目录保留。诊断经独立系统保存对话框，不上传或包含正文。

## 验证与证据

版本固定：Node 24.19.0、npm 11.17.0、Electron 44.7.0、Playwright 1.64.0、React 19.3.0、TypeScript 7.0.2；新增 Vite 8.3.4、Vitest 5.0.4、esbuild 0.28.2、PDF.js 6.4.299 和匹配 React types。未升级既有版本。正常 npm 安装更新 package-lock；网络重置时将同一官方 npm tarball 放入 npm cache 后正常安装。Electron 固定官方分发包 SHA-256 与其包内 checksums 一致。

| 命令 | 结果 | 日志 |
|---|---|---|
| `npm run test:desktop` | 27 passed，6 files，exit 0 | `desktop-unit-green.log` |
| `npm run typecheck:desktop` | exit 0 | `desktop-typecheck.log` |
| `npm run build:desktop` | exit 0；Vite chunk 大小提示 | `desktop-build.log` |
| `npm run build:desktop:test` | exit 0 | `desktop-build-test.log` |
| `npm run test:e2e` | 28 passed，exit 0，实际 Electron / Python，3.1 分钟 | `desktop-e2e-green.log` |
| `npm run test:e2e -- tests/e2e/layout.spec.ts` | 5 passed，exit 0；新增发送按钮在可见视口内断言、原生整窗口截图 | `desktop-layout-green.log` |
| `npm run test:e2e:real` | 8 failed / BLOCKED，exit 1，真实资格不足，模型调用 0 | `desktop-real-preflight.log` |

单元测试使用实际所属 Node HTTP 子进程与真实临时文件，覆盖认证、健康超时、提前退出、旧端口/身份、迟到旧 exit、失败清理与重复启动阻断，以及精确保存、同名拒绝、第二份失败、回滚拒绝。IPC/公开事件严格校验同时覆盖伪 sender、任意路径、内部额外字段和去重/取消竞态。

真实 Electron 用临时用户目录、实际 Python API/数据库/公开投影。文件种子只替换外部 A/B 响应，走产品 canonical、翻译、QA、PDF/DOCX/MD 渲染及原子发布；六份保存文件哈希逐项吻合。PDF/DOCX 预览检查可读文字和实际非白页面像素，并人工看图，不能仅凭 iframe/container 可见当成功。正式构建实际启动验证 main 和 renderer 都没有测试注入入口。

业务红灯：`desktop-red-boundaries.log`（最初五条边界反例）；`desktop-review-red.log`（旧 child exit 与无法撤回保存文件的反例）。中间 E2E 的 `desktop-e2e-intermediate.log` 是尚未等待目录保存完成的装置问题，不能算业务红灯。原生 PDF 容器空白由视觉检查发现，改为本地 PDF.js 后增强页面绘制断言。清理确认进一步发现环境 PATH 不含 taskkill，现固定系统可执行文件路径。

200% 缩放的原 Page/CDP 截图只取左上部分；已改用 Electron 原生 `webContents.capturePage`，同时核对发送按钮 bottom=380.90 < viewport height=432、right=692 < width=713。增强后的五条布局测试再次通过，整窗口截图可见完整输入和发送入口。

稳定截图：`artifacts/acceptance/D022/screenshots/` 的 1440、1280、1024、320 CSS px 布局及深色/22px/200% 缩放；`artifacts/acceptance/D036/screenshots/preview-pdf.png`、`preview-docx.png`、`artifact-pairs.png`。原始单次运行记录在 `artifacts/playwright`，真实资格预检逐场景记录在 `artifacts/playwright-real/*/real-preflight.json`。

## 卡片状态与限制

所有卡仍遵循完整门槛；本报告不把局部 UI 自动标 done。

| 卡 | 状态 | 未满足的完整门槛 |
|---|---|---|
| D021 | in_progress | 正常启动/退出、单实例与故障反例已验证；真实外部运行的异常退出、恢复与全部关闭偏好尚未做实际跨应用重启矩阵。清理失败记录恢复状态，退出应用仍可能留下未确认的后端，不能称清理成功。 |
| D022 | in_progress | 约定尺寸/缩放已测；系统 Narrator、全部组合对比度与长宽表的独立可访问性裁决未完成。 |
| D023 | in_progress | IME composition 事件、草稿/历史/幂等/实际 Markdown 附件已测；真正 Windows IME 输入录制、全部附件失败与历史分页负例 GUI 矩阵未完成。消息目前安全正文及 fenced code，未提供完整 Markdown 表格/复杂语法渲染。 |
| D024 | blocked | 真实 Claude/ZCode/GPT 生产资格、凭据配置与 secure storage 登录装配缺失；不得把演示探测当真实通过。 |
| D025 | in_progress | 内部 canary 在 IPC/瞬时 DOM 排除且 reducer 竞态已测；真实外部取消时间线、所有澄清和重连场景 GUI 门槛仍缺。 |
| D036 | in_progress | 实际六文件保存/Markdown/PDF/DOCX 预览与作用域、同名/取消/部分回滚已测；完整损坏/空间不足/复杂多页/所有历史版本 UI 负例与独立内容裁决未全部完成。 |
| D037 | in_progress | 偏好、默认导出目录、清理预览、实际迁移/重新连接、用量/筛选/未知口径/节省未评测 UI 已测，本地日期边界含最后毫秒；后台活跃外部任务、低磁盘、重启失败及完整账本对账 GUI 矩阵未完成。 |
| D038 | in_progress | code/paper/document 自然任务资料、附件角色/引用、格式选择与草稿恢复已装配，正常 API 冻结 profile。普通文档 GPT 原生文件、有效 CSV 综合报告/代码/数据/图已实际发布且翻译调用 0，缺资料 NEEDS_INPUT A0 已测；真实生产四域完整质量门槛和全部领域 C/语义人评矩阵仍未满足。综合数据当前限一个 CSV、四行、两月 YYYY-MM。 |
| D040 | blocked | 四域 × Claude/GPT 有真实开关、冻结输入哈希和动态生产资格预检；无生产资格八条都明确失败，零任务发送。真实附件材料、独立 C 判据、合格交付、双语人评和全 A 独立质量/token 基线全门槛尚未装配，不能把公开答案当最终通过。 |

## 独立复核修复（最终 27 单元 / 28 实际 Electron）

独立报告 `independent-desktop-review.md` 的四个 P2 已修：断线仅停订阅而保留已显示消息/文件；迟到认证回执保持公开事件的终态；跨会话提交/取消/文件异步续行有会话与导航代数 fence；用量按本地午夜至下一本地午夜前 1ms 序列化 UTC，配合后端瞬间比较。新增同文历史回放反例：未确认请求的 nonce、正文和附件保留；仅匹配实际 authenticated submit receipt 与 nonce 清原会话草稿，不再按旧 `message.accepted.text` 清理。NEEDS_INPUT 显示明确“放弃此任务”，取消后存储 active_tasks 回到 0，不自动放弃旧任务。InputRequired 支持 GPT 原生 en 与 zh-CN，错误/取消仍只允许中文，未知语言拒绝。

复核日志：`desktop-independent-review-red.log`、`desktop-profile-boundary-red.log`、`desktop-independent-review-green.log`、最终 `desktop-e2e-green.log`。原始独立复现提供断线业务红灯；新增断线测试最初用了不能匹配含重试按钮的 exact 文案 locator，修正为可观察连接按钮，这个装置失败不算业务红灯。中间正常文档的 CDP 截图挂起、snapshot CLI 非 UTF-8 解码和 mixed 使用 January/February 替代冻结 YYYY-MM 的样例问题均已修正，未通过伪造结果绕过。

D038 证据：`artifacts/acceptance/D038/native-document-snapshot.json`、`mixed-profile-snapshot.json`，两个 snapshot 都是正常 GUI 请求产生的真实 checkpoint，PUBLISHED 且 translation_count=0；截图在 `D038/screenshots/native-document.png`、`mixed-published.png`。paper/code 正例只确认真实提交 profile 与不可变引用冻结，不声称任意领域任务已通过全部 C 或语义审核。

## 文件索引

- `apps/desktop/src/main/{index,backend,ipc,local-assets,attachments,artifact-files,export-directory}.ts`：宿主、生命周期、静态资源、业务/文件/目录边界。
- `apps/desktop/src/preload/index.ts`、`src/shared/{desktop-bridge,validation}.ts`：隔离桥与 DTO。
- `apps/desktop/src/renderer/App.tsx`、`chat/*`、`settings/*`、`documents/*`、`components/*`、`styles/*`：聊天、公开 reducer、设置/账本/存储/诊断、双语卡及安全预览。
- `apps/desktop/{build.mjs,vite.config.ts,tsconfig.json,package.json,playwright.real.config.ts}`、根 `package.json/package-lock.json/playwright.config.ts`：固定构建/测试入口。
- `tests/desktop/*`、`tests/e2e/*`、`tests/support/electron-fixture.ts`、`run-real-e2e.mjs`：实际宿主、保存、IPC、UI 与真实资格门槛。

实现参考本地 Electron/Playwright 文档与固定包源码；PDF worker 接法参照 [PDF.js 官方示例](https://mozilla.github.io/pdf.js/examples/index.html)，本地静态相对资源参照 [Vite 构建指南](https://vite.dev/guide/build)。
