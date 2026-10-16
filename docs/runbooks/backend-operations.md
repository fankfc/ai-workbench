# 部分一后端运行与恢复

当前后端接口和本地固定场景可复验，真实模型工作流尚未启用。D004/D005 的必需能力没有通过，因此 D020 真实交接保持 blocked。GPT 选择 Codex native 路线，功能仍未连接。GUI、完整翻译、A 英文原件来源和双语附件发布属于后续任务。

## 本地验证

在仓库根目录运行项目解释器，不使用全局依赖：

```powershell
& .\services\orchestrator\.venv\Scripts\python.exe -m pytest -q
& .\services\orchestrator\.venv\Scripts\python.exe scripts/check_contracts.py --strict
& .\services\orchestrator\.venv\Scripts\python.exe tests/support/scenario_driver.py backend_vertical --root .tools/vertical-local --options '{"provider_mode":"fake"}'
```

scenario_driver 是测试装置，只接受显式 fake 模式，生产 API 不导入或暴露它。它仅替换外部模型响应；SQLite、不可变文件、Windows 进程、验证器、用量和公开发布流程实际运行。每次运行建立独立短路径目录，保存数据库、源文件、验证证据、账本、公开 SSE 和 scenario-result.json。综合场景实际执行固定分析代码，生成 CSV 汇总和 SVG，再连接数据→代码→结果→图表→报告五个版本节点。

## 本地服务

桌面主进程负责令牌并代理 renderer 请求。桌面模块尚未实施；后端单独检查时可在同一个 PowerShell 进程中使用：

```powershell
$env:WORKBENCH_API_TOKEN = & .\services\orchestrator\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
$env:WORKBENCH_DATA_ROOT = Join-Path $env:LOCALAPPDATA 'AgentWorkbench'
& .\services\orchestrator\.venv\Scripts\python.exe -m app.api
```

服务只绑定 127.0.0.1:8765。请求使用 Bearer 令牌；OpenAPI 也需要认证。令牌不写入响应或诊断报告。生产注册表当前为空，不能用任意模型名称或编辑身份字符串来启用请求。会话 SSE 返回持久游标范围后结束，客户端带 after_seq 重连；它从未转发未提交的模型流。

## 受管原生连接检查

2026-10-14 补齐了官方 app-server 的受管 RPC 客户端、协议检查以及阶段结果桥接。实际只读检查已成功：Codex 返回登录、模型目录和临时线程元数据；ZCode 成功建立并关闭延迟会话。两者的本地 Job 资源均清理完毕，检查没有提交模型任务。ZCode 的空目录仍要求官方账户宿主提供上下文；配置模型名不证明实际响应模型。

在项目环境中可单独运行 metadata-only 检查，输出路径按本次检查指定，保留已有验收证据：

```powershell
& .\services\orchestrator\.venv\Scripts\python.exe scripts/probe_native_connections.py --provider all --cwd .tools/native-connection-local --output .tools/native-connection-local/report.json
```

该入口只有固定元数据方法，没有生成、认证刷新或账户修改方法。遇到工具、模型活动、未知回调或入口哈希变化时停止。报告中的 `protocol_probe_completed=true` 仅表示元数据检查和本地清理完成；`production_enabled`、`scope_enforced` 及实际身份仍需各自证据。现有阶段桥接由私有可信 runtime 注入，普通 API 注册表仍为空，不能用配置布尔值直接启用工作流。

## 真实接入的阻塞与试验记录

- Claude Code 官方 CLI 2.1.296 安装在仓库 `.tools/claude`，官方状态检查未登录。用户已授权先用 GPT 进行试验；没有将试验回填为 Claude 能力通过。
- ZCode GUI 3.15.1.8093 附带 CLI 0.16.9。GUI 已产生一次实际 GLM 回复。standalone 与 app-server 的账户上下文不同，不能用 GUI 选择或空会话目录判定实际账户权限。官方 SDK 宿主验证和每次只读查询的结果见 `docs/acceptance/part-one-closeout/zcode-supported-host-build.md`。
- Codex CLI 0.160.0 已登录，实际文本运算、用量和响应引用已有证据。现有完成事件缺少可核验的执行模型身份；公开 `dynamicTools=[]` 也不等于禁用全部内置工具。身份与强制执行作用域未同时通过前，生产连接继续禁用。

原后端验收批次为 ZCode 两次、Codex 一次、Claude 零次入口启动；这不是整个会话的模型请求总数。后续文字试验与本轮观测分别记录在 `desktop-connect-20261013/native-trial-budget.json` 和 `part-one-closeout/continuation-budget.json`。元数据查询、模型提交、实际完成和远端内部请求分别记账，缺失计费用量保持 unknown。不得填入猜测的 model_id 或放宽作用域门槛来获得通过状态。

## 故障处理

先保留整个数据目录和原件，停止新的请求。SQLite 采用 WAL/FULL 和显式事务；不能只拷贝运行中的主库当完整备份。D008 测试覆盖迁移与原件保存边界，完整一致性备份属于 D051。

当前服务重建读取已有执行关联，并保守返回 unknown、保持 BLOCKED；生产注册表为空，启动尚未查询真实提供方。Recovery的受支持端口可注入真实查询、继续观察和成果核验，核验完成后进入验证或阻塞，不创建新模型请求。未发外部请求的本地任务保持 local_pending。恢复按当前步骤的实际连接及远端标识判断，冻结A连接和首次请求记录不能替代当前执行。所有 task/attempt/contract、提供方序号和会话游标分别核对；取消、旧尝试和终态不会被迟到完成复活。恢复 API 没有“重新启动模型”回调。

Windows Job 拥有进程树，记录 task/attempt/step 和远端状态。未知远端不能靠本地退出推断已停止；未确认状态阻止新步骤。查询/清理失败保留 cleanup_failed 审计并停止新启动，不宣称资源清理成功。普通工作目录和服务写入租约不是 OS 沙箱；没有受支持强制边界的真实外部执行继续阻塞。

发布前重新核对冻结合同、A 审查摘要、实际证据、版本图、不可变字节和取消状态，PUBLISHED 与公开 outbox 同事务提交。历史已真实发布的内容保留原版本；未发布的旧审批或模型事件不会借用新审批获得发布资格。Claude 和正式附件还需后续完整语言、来源、QA、渲染和原子 bundle 门槛。
