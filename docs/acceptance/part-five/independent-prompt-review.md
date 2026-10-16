# 阶段五提示词集成独立审查

日期：2026-10-15（Asia/Shanghai）。本报告由非实现者执行，只读检查产品源码并运行现有针对性测试及两个隔离探针；本轮仅新增本审查及探针证据。范围为第五部分第3–7节及既有语言、身份、证据和预算边界。没有执行全量回归，没有真实模型调用。

## 当前结论

COMMENT：发现的两项可达行为缺陷均已由实现者修复，原失败探针完整保留，新的独立探针及针对性测试复验通过。当前审查范围没有未关闭的HIGH/CRITICAL发现；冻结历史语言视图继续使用其原策略证明的限制保留在下文。本报告是单个非实现者的工程审查，不构成完整多评审合并批准、真实供应商资格或人工语义验收。

### F1 — HIGH，已关闭：Claude连续返修接管收到原始中文检查正文

- 发现时位置：`services/orchestrator/app/runtime/workflow.py:861`、`services/orchestrator/app/runtime/review_handoff.py:45`、`:59`。
- 事实：返修工作单将实际C检查的原始正文放入 `mechanical_observations`。连续同一缺陷触发A接管时，该工作单直接进入Claude请求；`_request`核对的是合同输入的英文视图，没有转换工作单内的检查正文。此前 `_review` 已准备并通过QA的英文检查视图不会被该接管分支复用。
- 可达性：B执行→A完整定稿→A返修→B执行→A完整定稿→A相同缺陷返修→A接管。完整定稿分支没有设置 `takeover_used`，因此不能以“Claude已经接管过”排除该路径。
- 实际证据：[隔离探针源码](prompt-tests/independent-claude-repair-language-probe.py)、[结果](prompt-tests/independent-claude-repair-language-probe.json)。产品实际到达 `OUTPUT_PREPARING`，3次A审查、3次A接管；审查请求具有英译检查正文，返修接管请求仍出现中文原始注释。所有模型输出明确为fixture。
- 影响：阶段四已经建立的Claude自然语言英文视图边界在新增返修交接路径被突破，英文角色提示本身不能修复数据内容的语言路由。
- 修复要求：服务继续保留并重验原始工作单；A接管只接收与同一原始证据哈希绑定、已通过QA的英文检查视图。优先复用同次A审查的英文视图，避免重复翻译和额外调用；缺失、过时或篡改视图应停止派发。
- 已复验修复：`workflow.py:643`保存当前审查ID、成果版本和已验证的英文检查视图；`review_handoff.py:82`的 `takeover_prompt_order`核对审查/成果绑定、原始证据ref/hash集合和实际视图文件字节后，只为Claude的外发工作单替换机械检查正文。原始工作单继续交由C重验。新的[独立探针结果](prompt-tests/independent-claude-repair-language-fixed-v1.json)仍实际经过3次审查/3次接管并到达 `OUTPUT_PREPARING`，`raw_chinese_note_in_takeover=false`，英文审查正文仍在。
- 准确适用范围：接管复用同次审查已经通过QA的视图，没有新增翻译请求。helper核对QA/工作ID存在以及视图的来源和字节；没有再次查询数据库执行独立QA资格审查，因此应称“复用并重验当前审查的既有英文视图”，不能称“接管重新做了一轮QA”。该元数据由可信 `_review`路径产生，任务资料或模型报告不负责填充它。

### F2 — HIGH，已关闭：译者报告的关键源歧义被丢弃

- 发现时位置：`services/orchestrator/app/translation/service.py:217`、`:229`、`:237`，以及 `translation/prompts/input_translator.txt:5`、`output_translator.txt:4`。
- 事实：`TranslationResponse`具有独立 `findings` 字段，新增忠实译者角色要求报告关键歧义、缺失和不可读输入；但QA仅接收 `check.findings`，忽略 `response.findings`。现有两份翻译TXT的JSON格式示例也未展示独立问题列表。
- 实际证据：[隔离探针源码](prompt-tests/independent-translator-finding-probe.py)、[结果](prompt-tests/independent-translator-finding-probe.json)。译者在实际持久化响应中报告 `AMBIGUITY/major`，独立checker未报告问题；产品返回 `READY`，保存的QA问题列表为空。
- 影响：系统丢弃其已经取得的直接失败/歧义证据，可能在源材料需要澄清时继续交付；这不是“翻译模型可能误译”的一般未知风险，而是可以确定复现的问题列表处理错误。
- 修复要求：独立校验并保存译者问题，将其与当前checker问题共同参与QA和澄清判定。保持checker的请求不携带译者/旧QA的 findings，避免破坏独立上下文。拒绝伪造块ID或畸形问题结构，保留已经发生的实际请求计量。
- 已复验修复：`translation/service.py:60`严格校验问题字段、块ID及源定位；`:142–151`在拒绝无效问题时仍保存实际用量；`:251`将当前译者和checker的问题共同送入QA，checker请求仍不携带这些问题。两份翻译TXT增加独立findings及未完成输入说明。新的[独立探针结果](prompt-tests/independent-translator-finding-fixed-v1.json)返回 `NEEDS_INPUT`，译者的 `AMBIGUITY/major`实际保留于QA；原来的READY反例不覆盖或删除。

## 已核对的正确边界

- `runtime/role_prompts.py:20`从固定资源路径加载每个角色，返回角色ID、版本、组装指令哈希及逐资源哈希；资源路径不由用户资料或模型响应控制。`workflow.py:374`在数据展开之后注入服务生成的 `role_prompt`，源数据不能通过同名键覆盖可信角色元数据。
- `planning.py:218`把加载的A职责和语言策略放入实际规划请求。规划概念映射保留原TaskContract：决策→method/a_responsibilities，自主范围→b_write_scopes/constraints，升级→程序固定规则/guidance_depth，验收→稳定ID的acceptance。此适配有明确文档，不是假称新增八个公共字段。
- Claude任务角色使用英文；GPT角色保存用户原语言，不新增强制翻译。既有模型身份、路由和英文视图检查仍在角色注入前运行。角色文案明确不授予工具权限或发布权限。
- `translation/service.py:182–194`将译者/复核角色及源资源哈希、checker完整身份纳入有效策略哈希；每次重新进入 `translate()` 会重新计算，旧READY工作或缓存不能绕过该调用的策略变化。
- `translation/service.py:246`单独构造checker请求，只带当前源块、当前候选、术语和高影响块；不携带执行历史或上轮QA findings。文案明确同一B换上下文仍属于自动QA。
- `translation/service.py:112`按完整序列化请求估计预算，包含新角色文案；译者、checker、失败和重试继续使用实际账本。fixture预算增加没有放宽产品预算守卫。
- `pyproject.toml:34`包含角色MD和翻译TXT资源。修复后的最新[wheel构建](prompt-tests/wheel-build-translator-findings.txt)和[资源验证](prompt-tests/wheel-resources-translator-findings.txt)均退出码0，直接从wheel隔离导入12种角色上下文、10份资源。独立逐件复核确认10份资源哈希全部匹配当前源码，wheel自身SHA-256为 `8e743f57621b4f2dd502a2382438e0f7e94d01d55a7fa3653e9d248b1091d7e9`，与证据记录一致；这证明打包/加载，不证明供应商接入。

## 冻结语言上下文的适用范围

策略失效保证适用于重新调用 `TranslationService.translate()`。`translation/runtime_context.py:20–35`恢复已经准备好的语言上下文时，只核对既有上下文证明、任务/轮次、路由、工作状态、QA及内容哈希，不与当前角色资源重新比对；`translation/history.py:54`对已有合格英文历史也不会自动重新翻译。

因此，升级提示词后的新翻译会使用新策略；此前已经冻结的合格视图可以继续以其历史策略证明恢复，不能将其描述为“全部旧译文已按当前提示词重新验证”。这保留了原有版本恢复语义，不等同于数据失真或绕过其既有来源/QA检查。若产品以后要求升级即撤销全部既有语言上下文资格，需要独立的失效/迁移设计；本阶段没有实现或宣称这种策略。

## 验证与限制

- 实现者 [policy-green.txt](prompt-tests/policy-green.txt)：12通过，退出码0。
- 独立重跑 [independent-review-tests.log](prompt-tests/independent-review-tests.log)、[JUnit](prompt-tests/independent-review-tests.xml)：12通过，退出码0，保留1项既有Starlette弃用警告。这些测试未覆盖F1/F2，因此通过不能否定上述探针。
- 修复后的独立针对性重跑 [independent-final-tests.log](prompt-tests/independent-final-tests.log)、[JUnit](prompt-tests/independent-final-tests.xml)：22通过，退出码0，包含角色、翻译策略/问题处理及Claude连续返修接管。实现者额外[翻译修复批次](prompt-tests/translator-findings-green.txt)记录56通过；批次相互重叠，不能加和。
- `green-final.txt`明确记录此前154通过、1个provider_id注册fixture失败、退出码1，不能当作最终通过证据；README已正确标注其性质。后续修正的针对性通过证据见上面的12、22和56项批次；完整回归等待父代理最终批次，不能把这些重叠批次相加替代。
- 两个探针只运行隔离本地服务，实际请求和QA记录使用产品模块，外部模型输出均为明确fixture；`real_model_calls=0`。审查没有对实际翻译语义、真实提供方、人工质量、发布或token优化作通过判断。

## 后续复核

F1/F2的具体反例路径已关闭；完整回归仍以父代理冻结后的一次新批次为准。本报告没有修改产品源码或冻结历史，也没有把局部绿灯提升为真实提供方、完整产品、发布或优化目标验收。
