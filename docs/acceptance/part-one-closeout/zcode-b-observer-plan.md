# ZCode B observer — approved narrow implementation

使用固定 official commit aac4755666d09fdcd70272fcf063c077a639015f 的公开 AiSdkModelAdapter.runtime、AccountProviderRequestAuthService 与已有 readonly 账户/config 源。独立 `.tools/zcode-model-observer/` 构建，旧 SDK200/session/产品源码/产品锁不改。

Provider 必须由实际公开 registry 解析为 ZAI StartPlan GLM-5.3；安装公开 builtin 当前协议为 Anthropic，baseURL 是 https://zcode.z.ai/api/v1/zcode-plan/anthropic，官方 adapter 规范到 /v1/messages。不开 direct GLM API 替代，不使用 private CJS 注入或 createLocalServices。

runtime wrapper 真委托原 ai.generateText/streamText；模型身份仅从绑定请求的实际 server response.body.model/id 取得，SDK response.modelId 回填不授资格。只允许文字消息与空 tools，没有 execute callbacks、单 SDK step、maxRetries0、adapter maxAttempts1；HTTP guard 再拒第二次物理 POST。所有 body/header/认证资料留 worker 私有内存。

0model 阶段只以官方 auth service.resolveCurrent 检查 existing ZAI StartPlan material presence/key count；此公开分支仅 readonly loadOAuthTokenSet，不刷新或换 project token。报告 headersApplied=false，HTTP0、model0。实际模型授权、fresh availability 与 budget claim 后续由 root 单独赋予。

公开 adapter 的 refreshRuntimeHeadersBeforeAttempt 内部 headersApplied 字段是发送前鉴权材料绑定契约，不是服务端接收证明。内部仅在真实官方材料可绑定时确认，报告 actual headersApplied 直到可信 fetch 已把该材料带给准确官方 POST 才 true；不得伪 CJS callback ack。

先离线 RED→GREEN：服务端来源、绑定、不接受 SDK fallback、冲突/空body、私有字段脱敏、empty tools、官方 endpoint/一次物理调用、身份变更拒绝。SDK依赖按官方 lock直接版本固定，官方vendor补丁按原字节应用到独立node_modules并保存hash/lock。
