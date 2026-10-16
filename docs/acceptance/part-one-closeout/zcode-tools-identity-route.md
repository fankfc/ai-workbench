# B 工具关闭与响应身份：独立源码核查

2026-10-14，只读检查官方 `zai-org/ZCode` commit `aac4755666d09fdcd70272fcf063c077a639015f`。12 个关键本地源码文件与该 commit 的 public raw 原件逐字节相同，核查命令 exit 0，详细 SHA 见 `zcode-tools-identity-route.json`。没有启动模型、SDK 账户查询、UI 或认证；没有改产品代码或重复已有测试。

**结论：fresh root/main runtime 的空 toolAllowlist 在源码中确实拒绝注册全部内建与 MCP 模型工具；当前公开结果还没有可靠地保留实际服务端模型身份。** 工具构造政策不是 OS filesystem sandbox 资格。已成功的 HTTP 200 账户 availability 与服务器返回的 GLM 模型目录，是已知的账户 / 目录事实，不在这里重新判为未知。

## 空 allowlist 的实际效果

[tool-allowlist helper](https://github.com/zai-org/ZCode/blob/aac4755666d09fdcd70272fcf063c077a639015f/apps/zcode-cli/packages/core/src/runtime/helpers/tool-allowlist.ts) 保留 `[]`，没有将其转换成 undefined。[builtin registration](https://github.com/zai-org/ZCode/blob/aac4755666d09fdcd70272fcf063c077a639015f/apps/zcode-cli/packages/core/src/tool/handlers/index.ts) 第 214–225 行将它变为空 Set，并对每个 builtin 执行 membership 检查；空集合不注册 Read / Write / Edit / Bash 或其他 builtin。[MCP registration](https://github.com/zai-org/ZCode/blob/aac4755666d09fdcd70272fcf063c077a639015f/apps/zcode-cli/packages/core/src/mcp/index.ts) 第 82–98 行对 MCP 名称同样执行空集合拒绝。runtime-tools 与 MCP 刷新路径都传递该 allowlist。

JS 空数组是 truthy，所以 [app-config overrides](https://github.com/zai-org/ZCode/blob/aac4755666d09fdcd70272fcf063c077a639015f/apps/zcode-cli/packages/bootstrap/src/app/app-config-options.ts) 中的判断不会丢掉空数组；permission.allowedTools 也被设为空集合。[native session operation](https://github.com/zai-org/ZCode/blob/aac4755666d09fdcd70272fcf063c077a639015f/apps/zcode-cli/packages/bootstrap/src/zcode-protocol/server-operations.ts) 第 3386 行将实际提供的 toolAllowlist 转给 runtime。

这条结论有明确前提：必须是匹配源码的 fresh root/main session，字段真正被 native 接受并保留。subagent_child 会补回一个 coordinator 控制工具，不应宣称其严格工具集合为空。允许list不阻止宿主在启动时读取自身配置、运行既有 hooks 或初始化服务，也不约束提供方内部未公开的行为；不能据此把 `os_scope_verified` 改为 true。

还有一个值得提前避开的兼容路径：[zcodeAgentService](https://github.com/zai-org/ZCode/blob/aac4755666d09fdcd70272fcf063c077a639015f/packages/services/src/zcode-agent/zcodeAgentService.ts) 将 toolAllowlist 列在旧服务器可省略的字段中。如果服务器拒绝参数，应失败结束；不能通过删掉 restrictive 字段再发送来维持试验。直接匹配版本的 CJS 协议应严格校验这一点。

## 实际响应模型在哪里，以及哪里没有

[public model contracts](https://github.com/zai-org/ZCode/blob/aac4755666d09fdcd70272fcf063c077a639015f/apps/zcode-cli/packages/contracts/src/model/index.ts) 的 ModelTextResult 保存 text、usage、tool/source 和 providerMetadata，没有单独的 executed model / response ID 字段。[runner-generate](https://github.com/zai-org/ZCode/blob/aac4755666d09fdcd70272fcf063c077a639015f/apps/zcode-cli/packages/adapters/src/model/runner-generate.ts) 最终返回同一规范结果，未转发原 AI SDK `result.response`。[stream normalization](https://github.com/zai-org/ZCode/blob/aac4755666d09fdcd70272fcf063c077a639015f/apps/zcode-cli/packages/adapters/src/model/runner-normalization.ts) 不转发普通 response-metadata / finish-step；只有 finish 本身提供 response 时，才可能把它并入 providerMetadata。

因而 CJS result.response 的答复文本、ModelNetworkStatus 的选定 modelId、registry 的模型目录、configuredSelection，都不能自动转换成 `provider_response_metadata`。providerMetadata 若有模型字段，也必须追到真正的服务端响应，不接受模型正文自述或宿主重新填入的配置回声。

[runner-debug](https://github.com/zai-org/ZCode/blob/aac4755666d09fdcd70272fcf063c077a639015f/apps/zcode-cli/packages/adapters/src/model/runner-debug.ts) 明确读取原 AI SDK response 的 id / modelId / body / headers，说明原生调用层有候选观测边界。这里还没有核实该 SDK 的 modelId 在缺少服务端字段时是否有回填行为，因此单独出现 response.modelId 不足以建立 source provenance。优先要求原始服务端 JSON 中的 model 字段，保留 response/request 绑定并拒绝缺失、冲突或旧请求。

默认 model-io 面还记录请求、正文与 reasoning。后续阅读的 redaction source 确认 Authorization / token / cookie 等 header 在写出前会脱敏；**没有把 debug input 含 headers 误列成实际 credential 泄露 finding**。但宽日志仍不是本任务需要的最小身份观测接口，不应为了模型名导出完整 debug record。

## 最小有源码支持的观测选择与当前缺口

[AiSdkModelAdapterOptions](https://github.com/zai-org/ZCode/blob/aac4755666d09fdcd70272fcf063c077a639015f/apps/zcode-cli/packages/adapters/src/model/runner.ts) 公开提供 runtime 注入；[AiSdkModelRuntime](https://github.com/zai-org/ZCode/blob/aac4755666d09fdcd70272fcf063c077a639015f/apps/zcode-cli/packages/adapters/src/model/runner-runtime.ts) 的 defaultRuntime 直接委托真正的 `aiGenerateText` / `aiStreamText`。合法的受控 observer 可以保持原委托与返回值，只从真正返回的服务端 response/body 私有投影模型与 response ID，不读取 request headers 或 account material、不替代模型客户端。

这只是源码可支持的路线。当前成功账户查询使用的是 auth/availability 子集 bundle，不含该 model runtime；现有 CJS 公开协议也没有因此多出一个 raw-response observer。若要使用一次 inference 验证，应先以零模型 fixture 核实**实际准备使用的**观测端口：只接收 server-origin 字段、拒绝配置回声与未知/冲突、绑定 request/session/response、关闭宽 transcript 输出；fixture 不能授予真实执行身份。

实际 seed-registry → SDK host authorization → CJS inference 生命周期还须真运行并观察。不能由 HTTP 200 availability 推断这个 model 请求已经完成认证、取消已确认、usage 已归一或模型身份已报告。只有 completion 而观测口缺失时，应如实保留执行已完成 / 身份 unknown 的分离结论，不重复请求直到得到期待值。

本报告没有判断账户未授权。未通过的是实际模型请求的身份 / 执行桥与 OS scope 资格，正式 workflow / registry 接通也未由这次源码检查验证。
