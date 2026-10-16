# GPT 官方 app-server 元数据调查

本次只运行一次本机官方 Codex 0.160.0 app-server，5.768 秒结束，未发送模型请求。
`gpt-metadata.json` 保存脱敏结果、可执行文件和临时探针 SHA、十份本机生成协议 schema SHA。
临时探针位于已忽略的 `.tools/gpt-metadata-probe/probe.py`，使用既有 Windows Job-at-creation
启动器和隐藏窗口；关闭后实际运行数、句柄及临时目录均为零。

完成的调用顺序是 initialize → initialized → model/list → account/read(refreshToken=false)
→ thread/start(ephemeral=true) → thread/read(includeTurns=false)。只有这六种方法能被探针发送。
账号响应仅保留 logged_in=true/type=chatgpt，不保存账号、邮箱、计划或令牌。
探针没有直接读取 auth/config 文件，也没有覆盖模型、系统设置、权限或规则；官方服务会按既有登录状态和配置运行。

实际线程响应的 result.model 和 thread.model 均为 gpt-6.1-sol，modelProvider=openai；
同一临时 thread ID 的 thread/read 返回一致，turns 为空。模型目录有七个可见项，
默认项同为 gpt-6.1-sol。这证明官方本地协议和现有登录状态能被自动读取，不能证明模型访问权限或实际推理完成。
目录还可能采用缓存或内置列表，不能把列表可见当作推理资格。[官方说明](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server)

身份限制不能省略。本机 ThreadStartResponse schema 明确把 Thread.model 定义为当前配置值，
并注明它不是每轮执行遥测；TurnStartResponse、TurnStartedNotification、TurnCompletedNotification
的 Turn 仅提供 ID、状态、时间、items 和 error，没有 guaranteed executed model_id。
因此这里的 gpt-6.1-sol 是服务报告的选定模型，actual_model_identity_verified 仍为 false。
不能用它回填旧 CLI 试验的未知响应身份，也不能直接转换成现有 GptAdapter 所要求的
provider_response_metadata(model_id, request_id) 来启用生产。

原生消费者可沿官方 thread/start 和 turn/start 生命周期建立确定绑定：先持久 thread ID
及服务返回的选定模型，再在 turn/start 明确传相同 threadId/model，持久返回的 turn ID，
核对完成通知对应同一 thread/turn、状态 completed、实际响应及用量。模型切换通知
model/rerouted 绑定 threadId/turnId，收到与冻结模型不一致的切换必须阻断旧审批。
这些调用属于[官方 app-server 协议](https://learn.chatgpt.com/docs/app-server)，本次没有执行 turn/start。

这个流程能绑定请求与模型选择，尚不能单靠配置回声证明上游实际执行身份。
仍须取得受支持、绑定本次请求的执行模型元数据，或明确变更并复核身份合同的证据口径。
生成协议还含 internal-only RawResponseCompletedNotification：有 responseId/threadId/turnId
和每个上游响应的 usage，却没有保证的 model 字段。experimentalRawEvents 在 schema 中
注明供内部使用，不建议当作已验证的正式产品入口。

结论：本地自动握手、账号类型与线程模型选择已实测；正式请求执行、真实模型身份、工具边界、
取消/恢复、用量对账及后端生产接通没有由这个零模型探针验收。生产仍禁用。
