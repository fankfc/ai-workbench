# D026–D030 翻译实施记录

日期：2026-10-14。状态：`in_progress`，本地澄清闭合和回归已完成，生产源码 `SOURCE_STABLE` 并移交根代理；最终统一 Python 验收为 1318 passed。真实 Claude/ZCode 连接仍 blocked；双语人工裁决尚未完成。未执行真实模型，未提交（unborn checkout）。本记录不把外部响应 fixture 的成功当作真实模型验收。

## 现有产品接口

- `app.translation.router.snapshot_from_provider(ProviderContract, *, task_id,turn_id,attempt_id,policy_version='1.0',snapshot_id=None)` 生成既有公共 `RouteSnapshot`。`persist_snapshot(connection,snapshot)` 必须与创建 turn/task 在同事务。`LanguageRouter(db).lock(task,attempt)` 注册旧任务快照；`check_identity(task,attempt,provider)` 身份变化持久暂停、撤销发布资格并标记翻译 STALE。
- `TranslationService(db,translator,checker,*,policy_version='translation:1.0',max_b_tokens=None)` 接受两个独立 verified GLM 端口。`invoke(TranslationRequest)->TranslationResponse` 和 `request_status(request_id)` 是外部边界，默认不构造真实运行时。响应必须绑定 `ProviderContract`；translate/check 分别持久保存调用与用量。恢复先确认已有请求状态；未知执行不重复提交。
- `await service.translate(*,task_id,attempt_id,source,source_language,target_language,purpose,source_ref=None,context_sha256=None,glossary_version='1',format='markdown',source_version_id=None,source_locator='text',budget_id=None,job_id=None,explicit_retry=False)` 返回 `TranslationResult`。只有 READY 进入缓存；初次加两次修复，总候选最多3。连接重试另计最多3。
- `await InputPipeline(service).prepare(task,attempt,workspace,*,materials=())` 返回完整原文或英文历史、`english_views/full_scope/read_scope`。材料使用唯一 runtime workspace 网关；critical OCR 缺口返回 NEEDS_INPUT。GPT 原语言直通且翻译调用为0。
- `await OutputPipeline(service).prepare(task,attempt,source_revision,*,complete=True,explicit_retry=False)` 保留完整 A 英文内部稿；通过 `documents.canonical.require_canonical` 复核真实 A step/event/正文证据。
- `AnswerPublisher(db,evidence_root,service)`：`await stage(task,attempt,version,source_revision,review_id,*,complete=True,explicit_retry=False)` 后，执行 OUTPUT_PREPARING→READY，再 `publish(task,attempt,version)`。文件任务通过 `publish_in_transaction(connection,task,bundle_id=...)` 与完整文档包同事务发布。
- `validate_translation_release(connection,store,task,release,*,historical=False)` 供公开投影复核 source/job/QA/字节绑定。历史只放宽 STALE 和已变连接，不放宽完整源/译文、QA或哈希。
- `await ClarificationPublisher(db,service).publish(task,attempt,step_id,*,origin='planning'|'workflow_review')` 从实际已完成 A 步骤和持久原始响应提取完整 `clarification_text`。Claude 必须经 B 完整中译和独立 QA，GPT 原文发布且译者调用0。来源、原始响应、正文、QA与公开事件同事务绑定；`validate_publication(connection,store,event_id,*,historical=True)` 是公开投影和历史复用的必要门槛。
- `PlanningNeedsInput(task_id,attempt_id,step_id,prompt_id)` 是 planner 的私有可信返回值；`require_planning_clarification(db,result,*,connection=None)` 校验当前 task/attempt、实际 A 来源及发布证明。`TaskSupervisor` 在同事务核验 claim、接收澄清并清除 lease，不转交 B 执行任务。
- `NativeTaskPlanner(db,workspace_manager,runtime,*,allow_fixture=False,...,input_pipeline=InputPipeline(service))`：先验证完整输入/历史/材料和英文视图 READY，再调用 A 规划。冻结原文 SHA 与完整英文视图 SHA，profile 输入作为不可信原始资料参与完整读取；Claude 使用其经 QA 的英文视图。返回模型合同后校验固定字段及 `validate_profile_contract`。缺失 profile 文件或不完整二进制解析进入 NEEDS_INPUT，A 调用为0。
- `Workflow(db,workspace_manager,B,validator,A,budget_port,*,...,translation_service=service)`：私有 Claude 完整路径为输入 READY→B执行→真实C观察→A takeover 发出完整英文正文→`CanonicalCapture(logical_id='answer')`→再次 C→A review。仅 B 正文加 A PASS 不获得完整 A 源文资格。每个 A 请求重新验证持久输入证明和 provider 身份，漂移暂停并撤销资格。
- `NativeTaskExecutor(workflow)`：Claude 自动使用 `AnswerPublisher`；`requested_formats` 文件任务先完整解析 A canonical 并由 `DocumentTranslator` 逐块译制，再 answer stage→`BundlePublisher.stage`→READY→同 approval/同事务发布答复和文件包。GPT 文件请求同样由 A 发完整原语言正文、保留 canonical，直接渲染，翻译端口调用0。
- `build_native_backend(planner,executor,*,provider_registry,allow_fixture=True)` 和 `TaskSupervisor(...,provider_mode='fake')` 仅允许明确注入并验证的 fixture 私有路径。生产 `PhaseBridge` 资格检查没有删除或放宽，默认 real 注册表仍空。

`translation.runtime_context.prepare_sources(...)` 将完整双语历史和完整材料视图确定性装配成 A 上下文；已发布助手消息保留原 A 英文正文，不重新翻译其批准后的中文替代原稿。`load_gateway(...)` 复核 SQLite 证明、当前 route、READY 作业、原文字节/译文字节及保护范围后交给唯一 runtime `ContextGateway`。`conversation_context` 保留 PDF/DOCX 原二进制及 SHA、完整派生 UTF-8 视图和 block 范围；缺失/不完整解析不启动 A。

planner 将 profile 必需的 Markdown/TXT/CSV/JSON 原始资料逐件加入固定 `inputs`、完整 `source_unit_ids` 和 SHA；PDF/DOCX 只使用已验证原二进制 SHA 且完整解析的派生正文视图。Claude 对这些资料也须拥有完整经 QA 的英文视图。冻结 profile 的验收条件及证据类型逐字保留，额外 C 检查才使用 `C_METHOD`。mixed 任务在 A 规划前调用 root 的 `prepare_composite_context(...)`，将实际计算摘要、输入和精确依赖冻结进合同；A 不能添加或替换依赖，执行前再次复核持久 run 和来源。

迁移 `0002_route_snapshots.sql` 包含不可变路由、失效记录、作业、候选、独立校验请求、缓存、术语义项版本及双语历史。root 管理 parser 依赖锁，当前使用 `markdown-it-py==4.0.0` [官方 AST/token 文档](https://markdown-it-py.readthedocs.io/en/latest/using.html)。没有正则全文替代 AST；块内保护使用精确标记与字节回填。

## 已运行的业务红灯

命令均使用项目 `services/orchestrator/.venv/Scripts/python.exe`，`PYTHONPATH=services/orchestrator;tests`，pytest 排除 real_provider。

1. `translation-business-red.log`：已完整英文 A 原件和有效 A.review 的 Claude 回答仍被既有 NativePublisher 阻断，`LANGUAGE_AND_PROVENANCE_GATES_MISSING`，1 failed。
2. `translation-quality-red.log`：中文原文候选直接回传，结构覆盖与 fake 无findings语义检查误判 READY；期望 FAILED，1 failed / 7 passed。已增加目标语言检查。
3. `translation-budget-red.log`：未知用量仍发起下一次检查、极小预算仍调用译者；2 failed / 8 passed。已接 D015 保守估算预算门槛，未知消费阻止后续调用。
4. `translation-history-red.log`：中文回答发布后未保存对应完整 A 英文历史；1 failed / 4 passed。现与公开 outbox 同事务保存双语映射。
5. `translation-restage-red.log`：同 attempt 新源文 staging 被旧 release 失效标记污染；已在确认新源和新审查后撤下旧 staging 引用，历史发布证据保留。
6. `translation-native-red.log`：已有实际 Workflow 和 A planner 分别因 Claude 硬阻断/GPT-only 资格拒绝进入产品路径，2 failed。现通过持久输入证明、完整 A canonical 与可信发布器实际接入，未取消生产资格门槛。
7. `translation-clarification-red.log`：实际 A 英文必要澄清被固定中文模板替代、planner 拒绝 NEED_EVIDENCE 返回，2 failed。现只消费实际 A 步骤的完整显式问题，不把诊断 `issues` 当作用户问题。
8. `translation-clarification-history-red.log`：追问上下文丢失已批准澄清的原 A 英文。现保存并复用来源绑定的原文与完整中文映射。
9. `translation-late-receipt-red.log`：取消、路由漂移和响应身份错误后，已返回的 12 输入 + 12 输出用量被丢弃，3 failed。现先持久计费回执及响应，再执行取消/身份/来源门槛；错误响应仍留失败账，不能发布。
10. `translation-glossary-content-red.log`：默认空 v1 后安装术语和不同任务/领域同版本发生旧译文缓存复用，5 failed。缓存键现绑定实际不可变术语快照的 task、domain、content SHA 和安装状态，空默认版本不会与后装版本同键，失败历史保留。
11. `translation-clarification-partial-echo-red.log`：中文前缀加完整未翻英文问题仍 READY 并泄漏，1 failed / 4 passed。澄清机械 QA 和公开投影现各自拒绝未保护的完整英文句复制；最多3候选仍不合格即失败，不以中文模板冒充翻译。

早期相关回归（项目 `.venv`）：`python -m pytest tests/translation tests/unit/test_language_router.py tests/integration/test_route_snapshot.py tests/integration/test_input_translation.py tests/integration/test_output_translation.py tests/integration/test_claude_native_pipeline.py -q`，**48 passed / 6 依赖弃用警告，33.32s**，记录于 `translation-green.log`；属于中间记录，最终状态以下述统一回归为准。

单独完整 native 产品链回归为 **8 passed / 6 依赖弃用警告，29.85s**，见 `translation-native-check.log`。包括真实 public API document profile turn→TaskSupervisor→A规划→Workflow→A完整正文→逐块文档翻译→中文答复和三种格式六文件原子发布；每件实际下载文件核对 SHA，Markdown/PDF/DOCX 英中配对完整。profile C2 消费实际预渲染观察，最终文件另过实际渲染 QA，不以恒真 DTO 代替。fixture 仅替换外部模型回答，SQLite、作用域、正文捕获、QA、渲染、下载与发布均为产品模块。

同组核心反例：缺输入翻译→A0；输入作业失去READY→B0；规划后身份漂移→PAUSED+持久路由失效+B0；中文输出已准备后的取消→公开答复/文件事件0。GPT public API 文件任务同样通过 privateSupervisor 且 `translation_jobs=0`、translator/checker调用0。

新增严格 Word 导出期间曾实际遇到 `DOCX_WORD_RENDER_FAILED` 并正确阻断公开文件；由 root 修改 renderer 的跨进程互斥和严格关闭处理后，上述48/单组8项均通过。此 lane 未改 Word/renderer。`word-rpc-green.log` 实际记录7 passed，以 root 最终记录为准。

## 澄清闭合与最终验证

必要 A 澄清已实际装配：planning 的原始 A 响应捕获、Workflow 的实际 `review.decision` 事件流均绑定已完成 A 步骤、provider、task/attempt 和不可变路由。完整问题经 `ClarificationPublisher` 发布；Claude 英文不可直接投影，B 步骤或伪造的 `input.required` 不能获得资格。旧 A 响应只有 `issues` 而没有显式问题时，仍使用安全缺资料模板；该模板不计为语义翻译。公共 `InputRequiredPayload.language` 严格限定 `zh-CN` 或 `en`，兼容旧中文消息并如实标注 GPT 原始英文消息。

实际测试问题为 `Do not delete the original files. Should I use only 2 source files, or wait for the missing appendix?`，公开完整译文为 `不得删除原始文件。应当只使用 2 个源文件，还是等待缺失的附录？`。数字保护、否定语义重大错误、纯英文回传、中文前缀加整段英文、检查失败、取消迟到、身份漂移、无关 QA 指针及来源篡改都阻断发布。已冻结问题可在身份漂移后历史回放，来源/正文/QA 绑定仍严格；下一次用户追问保留实际 A 原始英文。真实 `PhaseBridge` 解码器验证新问题字段及旧响应兼容，完整 `TaskSupervisor` 规划澄清路径验证不启动 B 任务执行，GPT 英文澄清译者和 checker 调用均为0。

相关绿灯记录：`translation-late-receipt-green.log` 为 **3 passed**；`translation-glossary-content-green.log` 为 **11 passed**；`translation-clarification-green.log` 为 **64 passed**。更广的 `translation-final-regression.log` 为 **215 passed**，profile/material 来源锁定后的 `translation-final-closure.log` 为 **129 passed**；这些均是中间回归。最后澄清泄漏修复后的 `translation-clarification-final.log` 为 **90 passed / 1 warning，26.87s**，覆盖完整澄清、历史、真实解码、用量回执、缓存及保护负例。

最终依据为 root 已完成的 `python -m pytest -q tests --junitxml=docs/acceptance/part-two/final-python.xml`：**1318 passed、0 failed、0 errors、0 skipped、1 real_provider deselected，237.80s**，见 `final-python.log`、`final-python.json`、`final-python.xml`。统一回归前后的 `final-backend-source-before.json` 与 `final-backend-source-after.json` 哈希完全一致，`source_sha256=32eb1efafed0200a4c33e25235e214c5141dd9148764512175a5367a6b2689ef`，包含最终澄清、partial echo、receipt、cache 和 profile pin 源码。此后本 lane 只更新本报告，不再修改生产源码或重跑全套。

## 范围和剩余验收

自动化使用明确 `FakeTranslationPort` 仅代替外部模型响应，产品路由、SQLite、AST、保护、缓存、历史、QA门槛与 outbox 均真实执行。已有测试覆盖错模型名、未知身份、身份漂移、GPT0次、完整追问/材料、保护攻击、语义重大问题、三候选、三连接重试、未知请求不重复、调用后崩溃恢复、预算未知、模型/上下文/术语失效、取消迟到与历史保存。

Markdown当前支持 CommonMark + table；脚注扩展及超大结构块明确 unavailable，不静默丢块。数字采用严格原字面保护；没有声明中文数字词与数字字面等义转换。PDF/DOCX/OCR 的结构与渲染能力由 documents lane 负责，语言层直接输入未解析二进制格式会停止。

已知重大语义问题的自动测试证明门槛会消费独立检查报告；不证明真实译者能发现所有错误。同模型 checker 不算独立人评。金标准样例未获双语人签字，D029 不可称全部门槛 done。真实连接、GUI统一验收与独立 review 属于根代理最终审查范围，D040不得用本记录代替。

先前未装配的必要 A 英文澄清本地门槛现已闭合，普通完整答复、澄清、当前输入/历史/材料和文件翻译均已接实际产品流程并完成反例回归。此 lane 没有另留待实现的澄清、用量、缓存或来源锁定本地缺口；整体 `in_progress` 仍保留真实外部连接和双语人评的未完成门槛，卡片最终裁决由 root 负责。

其他支持边界：Markdown脚注及超大结构块、无法完整解析的二进制/OCR、缺失材料或目录 profile ref 都保持明确 unavailable/NEEDS_INPUT，不静默降级为全文 AST 或完整资料。双语人评、真实模型连接、生产 Claude runtime 的当前真实能力资格均未完成。源码已移交，不再在此 lane 修改；根代理负责最终全量、独立 review 和卡片状态裁决。


根代理最终展示修正后复验：final-python.log 再次 1318 passed / 0 failed / 0 errors / 0 skipped / 1 real_provider deselected，231.05秒；此前237.80秒的全量作为 pre-presentation-python 历史保留。当前后端源码稳定 hash 30b7567c862172887774d62ec9a6fe03b7abf06047a36b65c5b6e126d469c697；翻译生产源码未在这次展示修正中更改。最终统一结果以 verification.json 为准。
