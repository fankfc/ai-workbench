# A评审机械证据输入：独立只读复核

日期：2026-10-15。审查者未实现本次工作流/PhaseBridge修改。仅静态检查与一个独立本地helper探针；未重跑实现者59/160项测试、未执行全量回归、未请求真实模型或访问账号。

## 结论

GPT已装配路径的新增实现把实际C检查正文及其原文件SHA送入A评审提示词，修复了仅提供路径的问题。缺失、篡改、候选版本错配、伪造passed及重复criterion在读取边界被拒绝；最终评审仍通过既有版本/批准/发布规则。未发现该修改放开生产资格或把机械证据推入公共事件。

独立复核发现的一项P2合同/未来接入缺口已用明确能力边界修复：`phase_prompt_text`现在与`PhaseBridge._binding`一致，对Claude合同直接返回`PHASE_BRIDGE_GPT_ROUTE_REQUIRED`，不再把Claude视图替换为原件。Claude本地fixture仍通过独立的翻译/QA/ContextGateway工作流验证；真实Claude PhaseBridge未实现、身份和生命周期资格未验收，不能宣称已支持。

## 已核对的实现证据

- `services/orchestrator/app/runtime/workflow.py`的`_review`先调用`read_mechanical_observations`取得实际正文；Claude单独调用翻译服务，要求READY和源SHA一致，经`english_view`及`ContextGateway`取得英文视图，并在等待翻译后再次核对原始证据字节。提交包含原ref/SHA、实际content、译文content_ref/哈希和job/QA标识。
- `services/orchestrator/app/providers/phase_bridge.py`的`read_mechanical_observations`读取受作用域约束的真实文件，拒绝符号链接/reparse/硬链接，核对ref SHA、criterion、revision、候选字节SHA、C身份和严格布尔passed，重复criterion也拒绝。`_review`再次读取实际候选和原proof；mandatory C检查不能由模型PASS覆盖。
- `services/orchestrator/app/translation/context_gateway.py`及`runtime/context_gateway.py`核对源和译文字节、QA状态、保护片段及数字实体，通过固定translation目录读取。中文自然语言不得留在Claude视图；代码中受保护的中文不被删改。
- `tests/integration/test_agent_workflow.py`新增实际正文/public隔离、缺失/改字节阻断及Claude翻译job/QA/代码数字保护回归；`tests/contracts/test_phase_prompt.py`新增原proof正文送入提示词和版本/内容/布尔负例。这些源测试支持设计意图；本复核不冒称重新执行它们。

## 已关闭P2：Claude QA视图与原proof对象比较不兼容

位置：`phase_bridge.py:266–297`的`phase_prompt_text`，以及`workflow.py:562–603`的`_review`。

`Workflow._review`为Claude发出的是英文content，且增加`content_ref`、`content_sha256`、`translation_job_id`、`qa_id`、`language`。`phase_prompt_text`无条件把它与`read_mechanical_observations`返回的原文`{ref, sha256, content}`列表作完全相等比较。即使译文正确、QA完整，形状和content也应不同，比较会抛`REVIEW_EVIDENCE_INVALID`。反之，不提供`mechanical_observations`时，该helper自动注入原始正文，不按Claude语言门槛检查。

独立探针位于`independent-evidence-83236d88/observations.json`，实际调用当前`phase_prompt_text`，其结果为：

| 合同/输入 | 实际结果 |
| --- | --- |
| GPT＋原proof | 接受；保留原语言，符合GPT路径 |
| Claude＋Workflow相同的英文视图字段形状 | 拒绝，`REVIEW_EVIDENCE_INVALID` |
| Claude＋省略视图字段 | 接受并注入含中文自然语言的原proof |

探针的QA字段是明确标记的合成形状，用来隔离对象比较合同；它没有假装取得真实翻译质量或生产身份资格。该结果也不表示真实适配器已经接收Claude请求。

当前范围限制由三处直接证据确认：`PhaseBridge._binding`要求合同`model_family == 'gpt'`；`_provider`只接受codex/gpt或zcode/glm；`build_native_backend`生产身份映射不允许Claude。真实Claude因此先被拒绝，不能走到上述helper分支。

最小修复应二选一：显式把该提示词helper限定为当前GPT适配器并对Claude给出明确不支持错误；或建立独立受信的Claude视图验证合同，核验真实job/QA、源/译文hash及保护项后使用英文content。不能仅取消对象比较后信任模型提供的译文元数据。应增加helper层的Claude英文视图或明确拒绝反例，使fixture与原生适配边界一致。

## 修复后独立复验

实现者采用显式GPT-only边界，并增加`test_native_text_bridge_explicitly_rejects_unimplemented_claude_route`。审查者再次以相同独立helper探针检查：GPT原语言证据保持可用，Claude英文视图形状与省略视图两种输入均被明确拒绝；原件不再回灌。实际结果另存`independent-evidence-83236d88/observations-postfix.json`，原始发现文件保留。该复验不是重新执行实现者测试批次，也没有外部请求。

本文件只记录发现与独立复验；审查者没有修改所审实现或降低语言/发布/身份资格门槛。
