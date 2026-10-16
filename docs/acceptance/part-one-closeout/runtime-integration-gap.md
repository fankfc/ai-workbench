# 第一部分真实 GPT + ZCode 工作流接入缺口

审计问题：在用户授权 GPT 替代 A、暂不进入第二部分的前提下，现有 GPT/ZCode 适配器距离正式 API→合同→B 执行→机械检查→A 判断→可信发布还缺哪些最小代码？

结论：目前是可验证捕获的适配器边界与完整的 fixture 后端流程，两者尚未接通。注册真实 adapter 或把 probe 标为通过，仍不能产生正式 workflow 的候选、A review、用量或取消/恢复能力。需要补齐可信运行端口、阶段响应转换及应用调度，不需要重写已有 SQLite/outbox、发布审批、版本栅栏或进入翻译/GUI产品实现。

本报告为只读分析和文件级建议。没有改生产源码或测试，没有触发模型、CLI transport、UI、账户、网络或配置操作。GPT 替代 A 的授权改变可选 A 路线，不替代身份、作用域、用量、验收或实际产物证据。

## 按直接阻断程度排序

| 顺序 | 缺口与影响 | 置信度 | 直接证据 |
| --- | --- | --- | --- |
| 1 | capture 事件与 workflow 业务事件不兼容：没有 artifact.candidate / review.decision；已观察 usage 也会按 unknown 入账。 | 高 | gpt.py:136、zcode.py:48 对照 workflow.py:406、:436、:462、:538；synthetic decoder 实证见附录。 |
| 2 | 没有生产 transport 或可信 scope 实现；workflow 正确阻断全部普通真实 adapter。 | 高 | GptAdapter 默认 transport=None，scope_enforced 不存在；workflow.py:332；TaskWorkspace.execution_directory 默认拒绝 OS_SANDBOX_UNVERIFIED。 |
| 3 | 应用 registry 恒空，没有正式任务 dispatcher；API 请求最多建立 RECEIVED。 | 高 | application.py:22、turns.py:45、:58；Workflow 仅在测试/支持脚本中实例化。 |
| 4 | 身份来源未接可信 transport；probe 返回上次成功缓存，不能证明本次模型/连接。 | 高 | gpt.py:95、:113、:186、:198；providers.py 的合同核对只能校验给定记录。 |
| 5 | accepted ID 到达过晚；cancel 未实现、query/observe 不在 adapter 协议，startup 只注入 unknown。 | 高 | run 等待整个 CapturedRun 后才发 started；base.py:8；gpt.py:207；application.py:33。 |
| 6 | 正式来源准备、A 合同生成、机械验证与可信 publisher 的装配缺失；目前装配在 D020 固定夹具中。 | 高 | scenario_driver.py:79、:136、:164、:181；workflow 接收已建 TaskContract，并停在 OUTPUT_PREPARING。 |
| 7 | real_provider 测试是拒绝假验收的门槛，不是真实 workflow runner。 | 高 | test_backend_vertical.py:96；scenario_driver.py:252 仅允许显式 fake。 |

## 最小文件级实施建议

### 1. providers/base.py、gpt.py、zcode.py：把捕获解码器接到可信运行端口

**Evidence。** [base.py](C:/Users/asd15/Documents/ChatGPT/ai/services/orchestrator/app/providers/base.py:8) 只有 probe/run/cancel。 [gpt.py](C:/Users/asd15/Documents/ChatGPT/ai/services/orchestrator/app/providers/gpt.py:181) 的 transport 是一个等待完整 CapturedRun 的 callable，既不启动受管理进程，也不持有当前步骤的进程/远端句柄。[zcode.py](C:/Users/asd15/Documents/ChatGPT/ai/services/orchestrator/app/providers/zcode.py:51) 继承同一实现。当前 probe 脚本的 subprocess/120秒/输出限制属于有界实验，不是 D011 生命周期或授权作用域实现。

**Inference / 建议。** 新建私有生产 runtime/transport（例如 providers/runtime.py 与 providers/transport.py），由服务装配已核实入口、进程管理器和连接，而非从用户/profile 接受任意 shell command。保持既有 AgentRequest 七个位置参数兼容，可另用私有 ExecutionContext 传入 step_id、当前角色、租约、批准的读写域、运行策略与 pinned identity。D011 ProcessManager 的 step_id 用真实 steps.id；不得默认所有阶段共用 default。已有 decoder 仍可保留为离线捕获验证器，正式 run 应在接受后及时输出真实 started 引用，并保存受限原始流/结果/错误证据，不等待整次 capture 才登记。

作用域必须实际成立：服务网关的 read/write/lease、cwd、普通同用户进程和 Windows Job 对象都不能单独限制 CLI 绕过网关读取其他目录。可实施的最小真实路线是使用支持的、经验证的执行隔离或禁止任意工具的模型调用，只提交服务准备的内容，并仅由服务落盘；若 provider 支持工具，则需把路径与操作交给真正受约束的 broker/隔离运行环境。用负例证明越界读写、junction、源文件改写、A/B lease 越权与工具请求被阻断。`scope_enforced=True` 只能由运行端口在真实约束生效后产生/验证，不能在 GptAdapter/ZCodeAdapter 添加常量来跨过 workflow.py:332。D011 Job 回收证明本地进程树生命周期，不证明文件系统或远端停止。

### 2. gpt.py、zcode.py：增加业务阶段响应转换，保留原始结果

**Evidence。** [gpt.py](C:/Users/asd15/Documents/ChatGPT/ai/services/orchestrator/app/providers/gpt.py:136) 只输出 started/identity/delta/tool/usage/completed(error)，不会输出候选或 A review。默认成果要求是 probe 的 result.txt 固定 bytes。ZCode result.response 可替换 facts.text，但没有转成 normalized model.delta，DecodedRun 也没有独立的最终内容/产物字段；因此正常的 turn.completed/result 文本还可能在业务层完全不可用。 [workflow.py](C:/Users/asd15/Documents/ChatGPT/ai/services/orchestrator/app/runtime/workflow.py:462) 要求恰好一个非空文本 artifact.candidate，[同文件](C:/Users/asd15/Documents/ChatGPT/ai/services/orchestrator/app/runtime/workflow.py:538) 要求恰好一个 review.decision。

**建议。** 为 execution/takeover/review 定义私有严格结果 envelope，并在可信阶段桥接层转换，不把所有 agent prose 当作 artifact，也不以完成字符串生成 PASS。execution/takeover envelope 最小包含当前 task/attempt/contract digest、目标 deliverable、candidate 内容/语言与实际产物引用；review 包含 revision/hash、decision、逐项 criterion_results、read_unit_ids/source_refs、issues。服务对固定上下文重新核对绑定后生成现有 AgentEvent，原始模型最终响应 bytes/hash、实际 provider identity 和 remote refs 写入 step/check evidence。每次契约/成果改版使用新步骤和新 review，旧响应不得套入新版本。

保留 probe 的 FIXTURE_ARTIFACTS 验证入口，但正式 adapter 不得仍要求 PROVIDER_BOUNDARY_OK，也不能用 expected_artifacts={} 代表已验证成果。对真实文件成果，transport 按批准 manifest 收取真实 bytes，并验证存在、尺寸、规范路径、非 reparse/hardlink、内容 hash、归属 task/attempt/step，再交 D008 不可变登记；当前 workflow 只支持单一文本 deliverable，可首先明确限定该可执行切片。保留私有受限原始结果与脱敏日志的区分：现有 _safe_payload 会脱敏 delta，不能把经过脱敏的文本静默登记成原始 canonical 成果。扩展一般多文件 code/data/figure 输出需单独实现真实 manifest→ArtifactVersion→D016 依赖映射，不能复用 D020 fixed mixed helper 充当模型真实产物。

### 3. gpt.py 与 workflow.py：修复实际用量形状和幂等绑定

**Evidence。** decoder 输出 `provider.usage.payload={status,usage}`，workflow.py:436 读取 `payload.raw` 和 `payload.source`。因此已有 input_tokens/output_tokens 在正式组合中不会进入 ledger，变成 unknown。provider.started 只给 execution ID，未把 metadata.request_id 发出。steps.external_request_id 当前是本地不可变 invocation ID，不能替换成 provider 的 request ID。

**建议。** adapter/桥接统一输出 `provider.usage={raw:<actual usage>,source:reported|estimated|unknown,mode:request_total|cumulative|delta,...}`，保留实际计量来源、raw receipt/hash、stable receipt ID/provider sequence，并使用 D015 已有同序号幂等/冲突逻辑。正式请求继续先保留 pending usage，再以实际观察更新；订阅或缺 usage 保持 null/unknown，不以零或固定 fixture 数授予预算继续。真实 provider request/execution ID 放 provider.started 与 active_external_request/step.remote_execution；ledger 的本地 invocation key 保持不变，同时在私有 binding/audit 保留远端关联。A planning、B execution、A review/takeover 均单独入账，不能只统计最后一次成功答复。

### 4. providers runtime、contracts/providers.py 与应用 registry：建立可信身份/能力记录

**Evidence。** [gpt.py](C:/Users/asd15/Documents/ChatGPT/ai/services/orchestrator/app/providers/gpt.py:95) 接受 metadata.source/provider request/model 值，并比较 requested model 与 observed model；其安全性依赖 metadata 的构造端真实可信。Codex普通JSONL缺实际model时保持 unknown 是现有正确行为。 [providers.py](C:/Users/asd15/Documents/ChatGPT/ai/services/orchestrator/app/contracts/providers.py:195) 的 require_executable 将冻结路线与给定 provider 合同逐字段匹配，但不探测连接或校验外部证据本身。Workflow A 会核对冻结 route/live profile；实际 run 的 provider.identity 目前只存普通 workflow.provider_event，并未主动拒绝与 pinned profile 的不一致。

**建议。** runtime 读取已验证、版本绑定的连接证据并在每次请求消费 actual provider metadata：exact model、family、connection、request/execution、运行入口/配置版本及证据 hash。requested model、App 名、GUI selection、模型自述、last-success probe cache 不可替代 actual identity；actualmetadata 不足就 BLOCKED。ZCode app-server 的 configured selection 或 headers-needed 交互同样不能凭本地默认值标 verified，必须走官方支持的宿主授权/可信实际响应，不伪造 headersApplied 或读取账户密钥补齐。

无需把运行能力硬塞进既有公开 v1.0 schema：可由服务器私有 registry 持有经核验的 adapter/connection/capability record，与 provider_profiles.provider_json、connection_version 和证据hash对应。Workflow 在第一次 started/identity、后续身份变化及完成前核对该 pinned 记录；模型切换只能显式创建新 attempt/路线。GPT 替代 A 使用 native snapshot，B GLM 仍不得成为 A，Claude 的语言/来源门槛保持关闭。

### 5. base/runtime、application.py、tasks.py：实际取消与恢复端口

**Evidence。** [gpt.py](C:/Users/asd15/Documents/ChatGPT/ai/services/orchestrator/app/providers/gpt.py:207) 的 cancel 固定抛 CANCELLATION_NOT_VERIFIED；resume_supported=False。 [application.py](C:/Users/asd15/Documents/ChatGPT/ai/services/orchestrator/app/api/application.py:33) 启动只注入 unknown。workflow 的 cancel 仅在下一条 provider event 到达后调用；等待完整 capture 的 run 在挂起期间无法及时响应 API 的 cancel。tasks.py 当前正确持久取消与 pending_remote，但没有调 adapter 停止端口。

**建议。** runtime 维护 task/attempt/step→受管进程/实际远端引用注册，dispatcher 同时等待 provider stream、任务取消与超时信号。API 先提交取消栅栏，再通过内部 supervisor 发协作停止/本地 Job 回收；只有受支持的远端停止确认可置 external_stop_confirmed，否则保留 cancel_pending_remote。取消不能以本地进程已退出推断远端已停。

为 adapter 注册 query-existing/observe-existing/cancel-existing 能力，并绑定 D012 已实现的 active_external_request 私有当前 map：step_id/profile_id/role/actual request/execution/accepted/status，与实际 step镜像一致。Recovery 使用当前 B/A 引用，不退回首次 A/task 兼容列；accepted 缺 refs、query unknown、元数据损坏均保守阻塞。observe 只能重接已有调用，不能 new start。同步 Recovery callback 不可直接传 async coroutine；由 async startup/supervisor 提供实际完成的适配结果或独立异步 reconciliation wrapper。保留现有 cancelled/terminal/contract/current-step TOCTOU 栅栏。对于不支持 query/resume 的真实入口，显式 capability=false 并保留人工对账出口即可，不需要伪造自动恢复。

### 6. application.py、新私有 dispatcher 与 workflow.py：接通正式 API 任务

**Evidence。** [application.py](C:/Users/asd15/Documents/ChatGPT/ai/services/orchestrator/app/api/application.py:22) 永远创建空 registry；仅 fake profiles 被初始化。 [turns.py](C:/Users/asd15/Documents/ChatGPT/ai/services/orchestrator/app/api/turns.py:45) 真实提交要求 registry 中存在已验证 profile，因此现状全部阻塞是预期。即使外部手动注册，提交后的源码只有 RECEIVED/outbox/turn，没有计划/运行 worker。 [workflow.py](C:/Users/asd15/Documents/ChatGPT/ai/services/orchestrator/app/runtime/workflow.py:598) 接收已完成合同，PLANNING 是状态变更而不是调用 A 建模。

**建议。** create_app 保持兼容签名，以私有 runtime_factory/dependency 参数注入已核验 GPT A 与 ZCode B，不在启动时自动试模型、改账户或从 fixture 加载真实 profile。应用 lifespan 创建/停止 supervisor，事务提交后按 durable RECEIVED 队列领取任务；拒绝重复 client_request/lease冲突及 unknown remote 的新调用。由服务准备原件/hash/来源单元，再调用 GPT A 的严格 planning envelope 生成 objective/method/constraints/deliverables/acceptance/budget/source/dependencies；validate_contract 后与 route/task/attempt digest 一起冻结。不能把 make_contract 固定夹具或 B 自评分当生产 A 合同。

生产装配向 Workflow 传实际 profile_ids、validator、budget estimates/ledger、workspace与真实 adapters，不依赖默认 fake-gpt/fake-glm。工作流到 OUTPUT_PREPARING 后，supervisor 依次调用既有 NativePublisher.stage、当前版本 READY gate、publish；答案只能经过 D018实际 artifact/审批/publication registry，不能直接公开 provider text、PASS claim 或退出码。

机械验证可直接装配 D019 Registry，但必须给真实来源/当前 blob/evidence context和受支持工具。代码执行需要实际授权隔离；document renderer 未就绪继续 block；paper 结构与算术检查只证明对应机械条件，语义由真实 GPT A 核对。任务不需要的第二部分翻译/双语/GUI能力不在此接入中实现，任务确实要求的 renderer/canonical/多文件能力也不能被静默去掉。

## 最小落地顺序和验收

1. 先完成 provider runtime 的实际连接/身份、scope 与早期 accepted 记录，保留不支持能力为 unknown/blocked；在本地 fixture transport 添加非probe语义envelope和usage兼容反例。
2. 完成 GPT A planning/review 与 ZCode B candidate 转换、原始响应/产物证据绑定，再接单文本 native workflow；保持 D008/D010/D012/D015/D016/D018 已验证栅栏。
3. 装配应用 registry/dispatcher/cancel/recovery/publisher。通过真实 API 提交而非测试直接 Workflow.run，核验重复提交只一 attempt、实际步骤数/usage/成果 hash/public event 一致。
4. 分离真实有界验收 runner 与现有 fake scenario_driver。保留当前 fake/real 标记与固定分析 helper，真实 test不得只因 production_enabled=true 就 PASS。至少真实正常、A返修、取消/迟到、accepted后失联与重启unknown，以及真实 usage缺失的阻塞案例保存 durable DB/step/blob/A响应/公开事件证据。真实控制不支持的部分明确记录阻塞，不把 synthetic case 当真实 provider通过。

GPT 原生路线可先以单文本、小预算、服务落盘且无任意模型工具的明确合同完成最小真实闭环。第一部分若要求四域真实接入，须逐域保存实际产物/机械证据/A判断，不能把上述单文本或 probe成功扩大成四域通过；新 D020真实runner应报告按域/能力的结果。第二部分交付范围保持未进入。

## 实证、未知与限制

独立命令：`services/orchestrator/.venv/Scripts/python.exe docs/acceptance/part-one-closeout/runtime-integration-gap-probe.py`，exit 0。该脚本仅在内存构造两份明确 synthetic CapturedRun 并调用现有 decoder，没有调用 GptAdapter.run/transport 或真实连接。GPT/ZCode synthetic_decode_success=true 时，candidate/review事件均为0，usage只有status/usage，started只有execution引用，scope属性缺失、resume=false。八个主审文件前后hash相同。 [实证JSON](C:/Users/asd15/Documents/ChatGPT/ai/docs/acceptance/part-one-closeout/runtime-integration-gap-evidence.json)保存完整 shapes 和 hashes；synthetic verified 字样仅为严格metadata夹具路径，不是实际身份结论。

**Unknown。** 本审计不调查现时登录状态、真实模型可用性/价格、官方入口新版本的 sandbox/query/cancel支持或新授权实验结果，也不读取凭证。既有D005/D006 manifest 的 production_enabled=false 是历史证据，不应作为本次用户授权后的再次审批要求；新实现需按实际支持能力与新证据更新，由真实接入 lane 单独执行。provider lane指出的实际metadata/runtime-header问题仅作须核验边界，尚未在本lane进行远端操作。

最小尚需实施的代码已经定位；没有通过放宽 scope/identity/canonical/usage检查来消除缺口的建议。本文不宣称真实workflow完成或正式merge批准。
