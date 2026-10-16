# Codex 元数据连接器实现与验证

状态：元数据协议实现完成；推理、实际执行身份、文件系统隔离和生产启用均未由此模块验收。
本 lane 没有新增真实模型请求，也没有修改 gpt.py、workflow.py、processes.py、账户设置或权限规则。

先建立可导入 stub，九个业务检查失败（codex-protocol-red.log），再实现受管 transport。
后续反例日志覆盖配置身份、官方入口、跨线程取消、参数作用域、未知通知和模型流活动。
最终 Codex/通用 transport 42 项通过；与 ZCode 消费者合并验证 97 项通过、退出 0，
日志 native-connectors-green.log，耗时 6.41 秒。所有进程用例使用临时本地 Python NDJSON
服务器，无模型或账户请求；配置模型与账户字段用明确脚本 fixture。

`NativeRpcClient(command, cwd, metadata_methods=..., protocol_envelope='plain'|'jsonrpc',
timeout_seconds=60, max_output_bytes=65536)` 的端口为 `start()`、
`request(method, params=None, timeout=None)`、`notify(method, params=None)`、`close()`/`cancel()`。
一次实例只允许一次启动；close 前后、close/start 竞争以及重复 close 均保留同一清理结果。
NativeRpcError 仅公开固定 reason_code 和可选数字 error_code，不复制远端错误文本。

父端通过 D011 ProcessManager 启动隐藏的可信 broker；broker 创建的官方服务器和后代
继承同一 Windows Job。stdin 指令使用本实例私有临时 inbox，响应只经过有界内存，
不创建响应或原始日志文件。服务器 stdout/stderr 合并预算由 broker 边读边检查，
外层 ProcessManager 另有硬字节预算；stderr 原文直接丢弃。EOF、截断、错误、洪泛和
超时均有负例。跨线程取消先在锁外设置关闭 Event/本实例关闭信号，挂起请求及时停止，
而不是等待请求持有的锁直到超时。真实子/孙进程回收及句柄/临时目录为零经过检查。

RpcCleanup 返回 local_state、remote_state、cleanup_complete、forced、output_limited、
running/open_handles/temp_dirs。已启动连接的 remote_state 保持 unknown；本地 Job 回收
不构成远端模型停止证明。RPC 有效期为最多 60 秒并预留清理时间，失败清理不假称成功。

父端和 broker 均采用同一固定方法全集，调用方只能缩小：initialize、initialized、model/list、
account/read、thread/start、thread/read、runtime/capabilities、session/create、session/read、
session/close。所有方法使用固定参数或本实例创建后登记的资源 ID；不接受账户额外字段、
隐藏目录扩展、既有外部历史、外部 session 关闭、指令/权限覆盖或调用方强加未知方法。
ZCode 创建参数强制 guarded、deferred、titleGenerationEnabled=false、toolAllowlist=[]、
dynamicWorkflowEnabled=false、offPeakToolEnabled=false。account/read 固定 refreshToken=false，
thread/start 仅本工作目录+ephemeral=true，thread/read 排除 turns。
模型方法 turn/start、session/send、generation 及未列出的变更方法无法进入该端口。

未实现的服务端请求真实返回 -32601，不伪造 runtime preferences、headers、权限或浏览器
成功；callback 与未知 notification 的公开诊断采用固定分类。服务端 frame 与 broker 控制
消息分开，不能伪造 private diagnostics 注入凭据。若收到 turn/item/model 活动，包括
agentMessage delta 和 ZCode 嵌套 model.streaming，立即报 RPC_UNEXPECTED_MODEL_ACTIVITY，
不保存私有正文、推理或 tool payload。submitted_model_turns 始终为 0；完整 thread/turn
启动 ID 才能去重计数，仅流增量而无启动绑定时 model_turn_starts=None、observed_model_activity=true。

默认 CodexProtocolClient 在创建进程前验证 D006 supported-entry 的准确官方 executable
路径与 SHA，且只允许 app-server 固定 stdio 入口。exec、多余 flags、其他 executable 和
已变更 SHA 被拒。显式注入可信测试 factory 标记 injected_transport=true/entry_verified=false，
不能把 fixture 自称为官方入口验证。元数据只保留登录布尔值/类型、可见模型目录、
本实例线程引用和配置选择，不保留账号、邮箱、计划或 token。返回的 actual_model_id=None、
identity_status=unknown、scope_enforced=false、production_enabled=false 不因握手成功而改变。

可执行脚本 scripts/probe_native_connections.py 仅提供 GPT/Codex 选项。本 lane 没有调用它
重放官方服务器；脚本交根代理扩展 ZCode，并由根代理统一运行最终零模型复验。
ZCode 包装器只显式透传已经授权的 ZCODE_BUILTIN_PROVIDER_CONFIG_FILE 路径引用，
不继承凭据环境变量或修改系统/用户设置。

身份的唯一可接受后续来源是实际执行时受支持服务 response/notification 的白名单模型字段，
同时绑定本次 thread/turn/response ID 并固定 runtime/schema 版本。配置、目录、别名、
未发生 reroute、模型正文自报都不是 actualModelID 证据。官方 model/rerouted 提供每轮
fromModel/toModel，但只在真实服务切换时出现；缺席不证明默认模型执行身份。
本机 Thread.model 明确是配置字段，Turn 响应没有 guaranteed 执行模型；internal-only
RawResponseCompleted 的 usageMetadata.metadata 是任意 JSON，也不保证含 model。
这些限制和零模型实际探针结果见 gpt-route-investigation.md/gpt-metadata.json。

完整生产连接和原 D020 验收仍不得由这份元数据实现报告替代。
