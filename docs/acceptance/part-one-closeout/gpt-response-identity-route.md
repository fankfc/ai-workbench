# GPT 响应身份观测路线：官方资料与源码核查

核查日期：2026-10-14。范围是本机 Codex 0.160.0、同版本官方源码、当日官方 `main` 的关键消费者，以及 OpenAI 官方 API / Codex 文档。没有发起模型、认证或带凭据的网络请求；没有读取认证文件、修改产品源码或用户设置。只启动了三个 `--help` 进程。

## 结论

**正式完成事件仍丢掉 `response.model`；另一位作者随后在独立授权、诚实命名的 HTTP route 上，通过精确原生 SSE TRACE 观察到服务端 `gpt-6.1-sol`，并绑定唯一 owned completion。** 该事实仅资格化这一次响应身份，没有资格化原内置路由、所有请求、强制工具 / 文件作用域或正式 workflow。原始两个观测的 unknown 保持不变，不能用新事实回填它们。后续观察与独立核对见文末；以下路线表与调查过程保留首次源码调查的条件和时间边界。

| 排序 | 路线 | 支持依据 | 可用性与硬限制 |
| --- | --- | --- | --- |
| 1 | 原生 CLI 收到模型 header 后的肯定性诊断日志 | 官方 `RUST_LOG`；源码中的 `ServerModel` 消费者 | 不改变客户端或 TLS。只有真正收到 header 才成立；日志本身没有 response ID，必须额外证明所属请求，不能把无日志当成功。 |
| 2 | 同一官方上游的原生 HTTP SSE + 精确模块 trace | 官方日志过滤；SSE 解码前的 trace；合法 provider transport capability | 可在 CLI 完成 TLS 后看到响应 JSON。当前内置 `openai` 固定使用 WebSocket capability；没有核实到可直接关掉它的公开开关。新 provider route 是待核实选择，不能默认为同一已批准路由。 |
| 3 | 将服务端 `response.model` 保留到正式绑定事件的上游修复 | 官方 SSE / WS 解码器与协议字段缺口 | 源级修改或未来正式发行版需要重新 pin 与验证；此调查没有构建替代客户端或改冻结源码。 |
| 拒绝 | OTel `model` / rollout recording 直接充当执行身份 | 源码明确从请求设置生成 | 配置元数据不是执行元数据。 |
| 拒绝 | 普通 HTTPS CONNECT 代理；TLS MITM；API-key 注入代理 | 官方代理源码与 TLS 边界 | CONNECT 看不到密文中的 response body；MITM 需要改变信任；注入代理要求读取 key 并改变路由。均不满足此次限制。 |

“服务端报告模型”仍是提供方的响应声明，不是权重的密码学证明。此处要解决的是可信客户端能否收集、绑定并保存该声明，不能从模型正文自述、请求配置或没有 reroute 推断它。

## 已核实证据

### 本机与已有实际观测

`docs/acceptance/D006/supported-entry.json` pin 的官方 executable SHA256 为 `4b01d5920e6785614727443bbecf343f4dedbb7347052b72ba805aab6353ef01`，版本 0.160.0。调查先检查该 hash，随后只执行 `--help`、`app-server --help`、`debug --help`，三个均 exit 0，无 stderr。输出保存在 `.tools/gpt-response-identity-source/{cli-help,app-server-help,debug-help}.txt`。

公开帮助没有 response-model observer / 请求观测代理开关。`app-server proxy` 是 stdio 到已有 app-server 控制 socket 的中继，不是上游模型响应代理。帮助结果不能证明所有隐藏内部选项不存在，因而也检查了官方 CLI source。

现有 `gpt-execution-metadata-observation.md` 证明一轮真实 arithmetic turn 已完成，response/thread/turn 有绑定，用量已报告，但 `actual_model_id` 仍未知。该实验没有保存原始 SSE / WS 数据；这份调查无法事后恢复已丢弃的响应字段。本机已生成 schema 中的 Thread 模型是配置状态，RawResponseCompleted 是 internal-only，不能替代执行身份字段。

### 服务端原始 Response 与 Codex 消费者的差别

[OpenAI 官方 streaming-events 文档](https://developers.openai.com/api/reference/resources/responses/streaming-events) 的 created / completed Response 包含 `response.id` 与 `response.model`。这说明标准 API 有响应字段；它不保证 ChatGPT Codex backend 每次返回同样的全部字段，也不证明已完成的旧实验返回了该值。

[0.160.0 SSE source](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/codex-api/src/sse/responses.rs) 的关键链为：

- 第 51–76 行读取实际 HTTP `openai-model`，有值才发送 `ServerModel`。
- 第 194–211、268 行附近只从 `response.headers` / 顶层 `headers` 解析 `openai-model` 或 `x-openai-model`；没有读取 `response.model`。第 1537 行的官方测试明确覆盖忽略正文模型字段。
- 第 108–115、418–458 行完成结构未保存模型；metadata 会被原始 `usage` 对象替换。
- 第 573 行在解码前记录 SSE 数据；它是诊断 trace，不是新增正式协议字段。此前 web 文本归一化行号 545 已修正为下载原件的真实行号；原件 SHA 未变。

这条源码链解释了一个具体可能性：**上游原始 JSON 有 `response.model`，但 app-server 的 raw-completion 包装仍然没有它。** 这是有源码支持的推论，不能升级为“这轮真实响应一定包含 model”。

[0.160.0 WS source](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/codex-api/src/endpoint/responses_websocket.rs) 第 739–805 行同样先解析 ResponsesStreamEvent 再调用 header-only 的 `response_model()`。正常 WebSocket 消息没有 SSE 那条全数据 trace。解析失败时的 debug 输出可能带原始数据，不能故意制造协议错误来获取它。

当日下载的 [官方 main SSE source](https://github.com/openai/codex/blob/main/codex-rs/codex-api/src/sse/responses.rs) SHA256 为 `c58b85803937e43eb66adf6148d8f8fcca8e7badf43c1e96a747c9e56ae4e618`，仍是 header-only 模型读取与不带模型的完成结构。`main` 会变化；该 hash 只标识本次下载内容，不代表本机已经运行它。版本 tag 与实际 binary 版本相符，调查没有声称完成了可重复构建或 binary/source attestation。

### 肯定性 header 日志：最小条件性诊断

[官方环境变量文档](https://learn.chatgpt.com/docs/config-file/environment-variables) 支持逐进程 `RUST_LOG`，包括按 Rust module 过滤。[Session source](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/core/src/session/mod.rs) 第 4033–4061 行在收到服务端模型后比较请求设置：相同也会记录一条 info；不同会记录 warning 并发出 ModelReroute。[turn consumer](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/core/src/session/turn.rs) 第 2876–2886 行从真实 `ServerModel` 进入该函数。

因此可研究精确的 `codex_core::session` info 过滤，而不打开 HTTP request/header/auth debug。只允许接受**明确存在的服务端模型记录**。这个消息文字没有 response ID；必须同时核对独占进程、真正观察到的全部请求、所属 thread/turn、完成 response ID、任何 warmup / 多响应情况。无法排除额外上游请求或建立唯一绑定时，只保留诊断事实，不生成 `provider_response_metadata`。

header 本身是可选值，API overview 也没有把它承诺为所有响应必带的公共 header。官方通用 [request debugging 文档](https://developers.openai.com/api/reference/overview#debugging-requests) 推荐 request ID 用于关联；request ID 本身不是模型身份。无 reroute、没有匹配日志或只见选定模型均不能通过门槛。

### HTTP SSE 路线：原生观测可行，transport 前提尚未验收

精确的 SSE module trace 运行在原生客户端接收和 TLS 解密之后。因此原理上不需要 CA、包捕获、认证代理或替代模型客户端。控制层只能在私有有界缓冲中解析响应，保存白名单的模型 / response ID / request ID / 所属 turn 与字段来源，立即丢弃正文、reasoning、所有未知 header、metadata 和错误原文。不能把原始 trace 存入 acceptance 日志。

但 [client source](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/core/src/client.rs) 第 1021–1032 行只按 provider capability 和内部 fallback 状态选择 WS；[provider source](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/model-provider-info/src/lib.rs) 第 520–557 行给内置 OpenAI 设置 WS capability。第 686–722 行的一般合并不会覆盖同名内置 provider。因此 `model_providers.openai.supports_websockets=false` 不能作为已验证 HTTP 开关；旧 `responses_websockets*` feature 名也不等于此版本的实际 transport 控制。不能故意破坏 WS、证书或网络以触发 fallback。

[官方配置参考](https://learn.chatgpt.com/docs/config-file/config-reference) 允许自定义 provider 的 `supports_websockets` 与 `requires_openai_auth`。[provider source](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/model-provider-info/src/lib.rs) 第 184–193、420–439 行表明原生认证状态为 ChatGPT 且未显式改 base URL 时，默认上游仍是官方 Codex backend。这构成一条**源码支持、尚未执行验证**的同官方上游 HTTP 方案：由真正的 CLI 自行处理已有登录，观测层不获取认证值。

它不是直接可用的实验配方。新 provider ID 会改变有效路由，可能改变内部 metadata / catalog / actor-auth 语义；也不自动继承当前用户 `openai_base_url`。必须先只投影核对非秘密的有效 origin 与配置结果，保留用户规则、固定真实模型名并重新 pin 此路由。不能伪装 provider 名称、造模型 Alias、把回声当执行身份，或把 endpoint 改成假本地模型服务。本次没有创建该 provider 配置，更没有消耗模型预算。

app-server 的 [日志初始化 source](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/app-server/src/lib.rs) 第 708–747 行还安装独立 feedback / DB / OTel layers。下面的追加核查已确定 info 的存储去向，不能承诺它仅在 stderr。`codex exec` 的 stderr logger 配置与 app-server 不同，不能混用它们的日志行为说明。

### OTel 与 recording 为何不能修复身份

[官方 OTel 文档](https://learn.chatgpt.com/docs/config-file/config-advanced#observability-and-telemetry) 支持日志与 trace exporter，但可导出哪些字段要看源头。[OTel shared source](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/otel/src/events/shared.rs) 的 `model` 来自 SessionTelemetry metadata；[step settings](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/core/src/session/step_settings.rs) 第 170–174 行用当前请求的选定模型与 model-info slug 填它。[session telemetry](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/otel/src/events/session_telemetry.rs) 第 1102–1125 行的完成事件保存用量，未读取响应模型。

这说明现有 OTel `model` 是请求元数据。打开 exporter 不会还原被丢掉的响应字段。默认 detailed log 还包含账号标识字段；没有必要为了这个身份问题启用新的 exporter。[OTel provider filter](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/otel/src/provider.rs) 也不把任意 SSE trace 自动转换成结构化响应模型证据。

[rollout inference source](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/rollout-trace/src/inference.rs) 第 80–92、169–218 行记录已经规范化的输出摘要，模型标签来自请求上下文，原始 stream 是未实现的单独 payload 类。Record & Replay 可以用于重放，不因此具有可信执行身份。

### 官方代理的适用范围与当前拒绝原因

[responses-api-proxy source / README](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/responses-api-proxy/README.md) 确有 request/response dump 功能；[实现](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/responses-api-proxy/src/lib.rs) 第 77–105、163–273 行从 stdin 读取认证值，转发到指定 API 上游，并替换 Authorization。它不是已登录 ChatGPT app-server 的透明 observation API，也不是一个只返回模型名的 observer。[dump source](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/responses-api-proxy/src/dump.rs) 记录完整请求 / 响应 body，只有有限 header 脱敏规则。不能照 README 的 key 管道 / dump 示例操作；此调查没有运行它。

普通 HTTP/HTTPS proxy 若只做 CONNECT，TLS 中的 response JSON 与 headers 仍不可见。[官方 network proxy README](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/network-proxy/README.md) 的 HTTPS 内容观测依赖 MITM / CA 配置，主要承担工具网络策略。此次禁止安装 CA、修改安全设置及绕过工具拒绝，因而不选这条路线。

标准 API retrieve 可以返回其资源模型字段，但它需要对应 API 认证与可访问资源。现有 ChatGPT backend 的 `resp_*` 不因此成为公开 API 可凭现有登录自动 retrieve 的资源；没有官方证据时不能复用或导出 ChatGPT token 去调用该 endpoint。本次没有查账号、密钥或该 response 资源。

## 留给 root 的选择边界

最小的后续动作是先验证观测端口与关联逻辑，不启动模型：用明确 synthetic 的私有响应样本证明只保留 server-origin 的模型、拒绝 request-only / configured / mismatch / 多请求歧义 / 缺字段，核实实际 logger 过滤与 transport 配置。它只验证采集器，不能产生实际身份资格。

如果 root 选择真实 budget 内的单轮观测，应继续使用官方 pin 的模型客户端与已批准工具约束，并明确记录它属于 header 日志还是原生 SSE trace、有效上游与 route、所有实际响应、完成绑定、未知项和清理。只要字段缺失、不能唯一绑定或路由前提不成立，保持 unknown；不能重试直到碰到期望名字，不能因此启用 PhaseBridge 的生产 identity / scope。

首次源码调查时的剩余未知是：此前原始响应是否含 `response.model`；现有服务端是否会返回模型 header；合法同上游 HTTP 配置是否被此登录与用户规则接受；全部内建工具的关闭与 OS 作用域资格。后续独立 HTTP/SSE 观察已缩小其中的配置和响应字段未知，仍未解决强制工具 / OS 作用域；详见追加记录。此前响应和 header 的缺失不能事后推断。

## root 后续要求的窄范围核查

### info 是否能够只保存到 stderr

**现有 app-server 路线不能这样声明。** [SQLite log source](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/state/src/log_db.rs) 第 61–85 行的独立 filter 默认 TRACE，没有排除 `codex_core::session`；第 274–323 行生成并排队存储 LogEntry。因此肯定性的服务端模型 info 可以被本地 SQLite 保存，不受 stderr 的 `RUST_LOG` filter 控制。[feedback source](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/feedback/src/lib.rs) 第 234–263 行另有独立 ring-buffer logger，也会保留此 info。没有找到公开的逐进程开关能只抑制这两层而保留该 info。

同两个 filter 明确将 `codex_api::sse` 上限设为 DEBUG，所以前述 SSE TRACE payload 被这些层排除；这只解释精确 target 的行为，不能推广为所有原始日志均不持久化。禁止开启 `tungstenite` / 全 transport TRACE：它们可能包含认证握手，不属于此次可选诊断。

[exec source](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/exec/src/lib.rs) 第 323–326、665–674 行只安装 stderr fmt 与 OTel layers，没有 app-server 的文本 SQLite / feedback logger。现有 OTel event filter 不接收这个普通 session info；`install_sqlite_telemetry` 是数据库运行度量，不是同一个文本日志 layer。这使原生 `exec` 成为源码支持的较窄日志选择，尚未执行验证。它仍加载用户配置并可能保存正常会话状态；不能称为进程完全无磁盘副作用，也不能用缺失的 response/turn 绑定代替实际绑定。

若 root 继续规划 app-server，可精确说明“观测层仅保存白名单投影，原生 CLI 会按自身默认日志策略存储模型 info”；不能改写为整个运行只有 stderr 保存。

### 公开配置能否关闭全部内建模型工具

**没有核实到此版本 stock CLI / app-server 的公开 all-tools-disabled 入口。** 本机 ThreadStartParams 的 `dynamicTools=[]` 仅为空动态集合；TurnStartParams 没有通用 tool allowlist。`environments=[]` 明确关闭所选环境访问，不能关闭所有控制、hosted、MCP / extension 工具。`disabledPluginIds` 的本机返回 schema 还注明尚未过滤 plugin capabilities。

官方 config schema 的 ToolsToml 只有局部工具设置；没有通用 `tools.enabled=false` / `tools=[]`。ConfigRead 的 ToolsV2 仅展示 web-search 子配置。不要利用 config 对任意 JSON 接受这一点发明开关。

[tool construction source](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/core/src/tools/spec_plan.rs) 第 1081–1095 行会因空环境或 `features.shell_tool=false` 去掉 shell，第 1269–1271、1283–1296 行按环境去掉 apply-patch / view-image；但第 1207–1249 行还能按模型能力注册 async user messaging / clock 等。因此多个局部 feature=false 不证明最终工具集合为空。只读 sandbox 也不是禁用文件读取；`approvalPolicy=never` 不是全部拒绝执行。

源码确有严格工具 ceiling：[ToolPolicy](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/ext/extension-api/src/tool_policy.rs) 的 `allowed_tools=Some(empty)` 可以拒绝全部工具，registry 与 hosted specs 都执行此策略。但 [Session initialization](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/core/src/session/session.rs) 第 984–994 行从 Rust `ExtensionDataInit` 注入该策略，普通线程默认允许正常工具选择。这是库级 host 能力，不能伪装成当前 public RPC 或配置已经暴露的能力。

所以可以用已支持的局部字段收紧下一次调查，却仍须记录 `all_builtin_tools_disabled=false/unknown`、`os_scope_verified=false`。收到 callback 或看见已开始的 tool notification 再中断属于事后检测，不能保证内建工具在执行前已被禁止；观察到 0 tools 也不授予该资格。若下一步要求强制全部工具为零，当前缺少合法可用端口，应停止在模型前。

### 配置投影与 source-derived origin

另一位作者负责唯一的实际零模型 config/account 投影；本审查只核实其解释所需的源码，不重复查询。[config-manager read source](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/app-server/src/config_manager_service.rs) 第 119–149 行读取指定 cwd 的合并 layers，转成 ConfigToml 并应用 exact requirements，再序列化为协议 Config。[协议 Config source](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/app-server-protocol/src/protocol/v2/config.rs) 第 281–316 行用 `additional` flatten 保留其他已序列化字段。因此实际快照中 `openai_base_url` / `model_providers` 的有效空值可以结合这条源码链解释，不能仅根据 schema properties 没列出字段来判断。

core config 第 3816–3819 行按 required provider、明确函数参数、配置 provider、最后默认 `openai` 的顺序选择；内置模型 provider 的默认 inference origin 再由原生 auth mode 选择。`chatgpt_base_url` 是另一项 ChatGPT 客户端配置，会用于 auth / plugin / MCP / workspace routing，不是 `to_api_provider` 的 inference override；不得直接拼接 `/codex` 当实际请求观测。

内置 provider 第 533–548 行只显式加入非秘密 version header，以及从 `OPENAI_ORGANIZATION` / `OPENAI_PROJECT` 读取的两个可选组织 / 项目 header；第 391–416 行只有 env 值存在且非空才加入。安全投影只需记录这些 env 是否存在，不读取或导出值。

在作者已记录的无有效 endpoint override、fresh auth type=chatgpt、已观察到 thread provider=openai 的前提下，可将官方 origin 明确标为 **source-derived configuration**。它不是实际 HTTP request/response 的 origin 观测，也不是已执行模型的证据。新诚实命名的 HTTP observation route 应独立保存实际 effective provider / origin 的投影，不能继承旧生产 profile 的资格。

## 调查证据与复现限制

`gpt-response-identity-route.json` 保存官方 public source 下载 URL / SHA、三个 help 输出 hash / exit，以及与作者 native freeze 的比对。完整 public source 缓存位于忽略目录 `.tools/gpt-response-identity-source/`。GitHub public tree API 首次读取返回 403 rate limit，原 shell invocation exit 1；三个 help 在此前均已成功。随后只下载固定官方 raw source，猜测不存在的路径保留 404 结果，没有把它当业务失败或权限拒绝。

追加的 schema 静态读取首次使用系统默认 GBK 解码 public UTF-8 schema，shell exit 1；已改为明确 UTF-8 读取，exit 0，属于调查命令修正，不是产品业务 RED。这个错误没有触及用户或认证文件。

本次没有运行产品 tests、重复已有绿测试、生成正式身份、修改 frozen production / tests，或调用模型 / UI / auth。最终结论是观测路径的支持范围与限制，**不是正式交接通过，也不是第一部分真实生产资格通过**。

## 最后一次窄范围追加：SSE TRACE 的各日志层与实际绑定

以下结论只针对固定 tag `rust-v0.160.0` 的 `codex_api::sse::responses` TRACE event。原件的 `trace!("SSE event: {}", &sse.data)` 在第 **573** 行；SHA256 为 `327127fb7e6886b0ffe73c74c753cc44b2c09e72c090600a861756334397cd2b`。

| app-server 已安装层 | 精确 SSE TRACE event 的处理 | 固定源证据 |
| --- | --- | --- |
| stderr fmt | `RUST_LOG=off,codex_api::sse::responses=trace` 可接收；`LOG_FORMAT=json` 选择 JSON fmt。 | [app-server lib.rs:708–747](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/app-server/src/lib.rs#L708) |
| SQLite log layer | 独立 target ceiling 将 `codex_api::sse` 限为 DEBUG，排除该 TRACE。 | [state/log_db.rs:61–85](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/state/src/log_db.rs#L61) |
| feedback ring logger | 同样的独立 DEBUG ceiling 排除该 TRACE。metadata layer 只接收固定 feedback tags target。 | [feedback/lib.rs:234–277](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/feedback/src/lib.rs#L234) |
| OTel log bridge，包括 reload layer | 只接受 `codex_otel` 前缀且非 trace-safe 的事件 target；SSE target 不满足。 | [otel_reloader.rs:22–39](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/app-server/src/otel_reloader.rs#L22)、[targets.rs](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/otel/src/targets.rs) |
| OTel trace layer | 普通 event 只接受 `codex_otel.trace_safe` 前缀；SSE payload 是 event，不是 span。 | [provider.rs:337–350](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/otel/src/provider.rs#L337) |

因此该精确原始 SSE TRACE 的源码路径是 stderr；它不经过上述独立持久化 / export event layers。这不证明整个 CLI 的会话状态、其他事件、正常 transcript 或第三方配置无持久化，也没有完成 binary/source attestation。不得扩大 `RUST_LOG` 为全 transport TRACE。

app-server 第 715–719 行使用 `.json()`，没有 `flatten_event`，所以采集器只接受嵌套的 `fields.message`。官方 stderr test 确认 JSON fmt 与 target filter，不直接断言键结构；随后真实观测实际收到该精确形状。采集器还要求 target 精确相等、level=TRACE、固定 `SSE event: ` 前缀，且只由 `response.completed.response.model` 授予身份。created 字段只能帮助检测冲突，request/config/model delta 不参与授权。

原生 info 仍可进入 `sqlite_home/logs_2.sqlite` 的 `logs`，写入字段是 `ts`（epoch seconds）、`ts_nanos`、`level`、`target`、`feedback_log_body`、`thread_id`、`process_uuid` 等；没有独立 turn/response 列。第 58 行默认 flush interval 是 **10 秒**。先前 INFO 观察只等待约 2 秒后查询，故 0 rows 只是未观察到，不证明服务端没返回 header。作者另加 limitations annotation，未改写此前 JSON 或旧 hash；本审查没有读取真实原生历史库。

另一位作者的 [实际 SSE report](C:/Users/asd15/Documents/ChatGPT/ai/docs/acceptance/part-one-closeout/gpt-sse-identity-observation.json) 保存一轮 accepted / completed、两个可识别 response 事件、一个 distinct response ID、一个 completed 与一个 RawReceipt。根响应的 `model=gpt-6.1-sol` 与该 receipt 的 response ID 匹配，receipt 绑定独占新 thread / turn。用量为 21954 input + 23 output = 21977；顶层提交 1，实际绑定 turn start 1，自动重试关闭，提供方内部认证恢复 HTTP 次数仍 unknown。0 observed tools/callbacks 和本地资源清理全部为 0，不是强制 scope 或远端停止证明。

此次使用新 route `workbench_chatgpt_http_observer`，不是原内置 profile 的自动升级；`scope_enforced=false`、`production_enabled=false` 保持正确。本审查只读取受限报告、parser/helper 与公共缓存 hash，没有重跑作者的 24 个离线绿测试或真实模型。[独立核对](C:/Users/asd15/Documents/ChatGPT/ai/docs/acceptance/part-one-closeout/gpt-sse-independent-verification.json) 将记录这些字段、source/helper/parser SHA 与冻结产品 hash 的一致性。后续正式能力 issuer、public 强制工具 / filesystem scope、API registry / planner / dispatcher 装配仍是未通过条件。

### 收敛后的作用域要求与公开配置边界

root 后续将诊断要求收敛为禁止越权 filesystem / arbitrary execution，而非强制删除 clock / update_plan。上文 all-tools-disabled 调查保留其原始更强问题，不应成为新的额外门槛。空 environments 对 shell / apply-patch / view-image 的注册确有作用；能否组成足够的公开限制需要固定 stock extensions 与实际有效配置，不从可见工具数量推断。

本 reviewer 的窄补查确认：core config 第 1716–1721 行把 `features.plugins` 传入 [PluginsConfigInput / manager](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/core-plugins/src/manager.rs#L812)，false 时立即返回空 PluginLoadOutcome；MCP 的 [connection manager](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/codex-mcp/src/connection_manager.rs#L314) 仅启动 effective `server.enabled()` 为 true 的项。每个已知 effective server 的 enabled=false 有源码依据；`features.apps=false` 不等于关闭用户配置 MCP。

[config merge source](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/config/src/merge.rs#L138) 递归合并 table，因此 `mcp_servers={}` 不清掉下层用户条目；数组落替换分支，`notify=[]` 可替换 legacy notify 参数。参数仍须由真实 config/read 解释为有效值，不能修改用户文件或删除规则以取得预期结果。

另一位作者继续核查 fixed stock skills / memories / image generation 与 CodeMode factory。已经指出 legacy `features.js_repl/js_repl_tools_only=false` 在此版本是 no-op，合法 cloud gate 是 `cloud.skills.enabled=false`。不能因为 model 工具目录强制 CodeMode 就断言该工具一定具有执行能力，也不能因为注册为空就授予 OS scope；须按 provider factory / dispatch gate 验证。尚未将这些源码选择装配为生产 capability issuer，本次实际 SSE report 的 scope=false 保持不变。
