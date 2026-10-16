# Claude 机械证据译校预算回归

2026-10-15。最终回归发现综合旅程在新增完整 C proof 译校后被预算门槛阻断；本次仅排查该失败，没有扩大业务验收范围。

只读检查默认短临时目录 pytest-517 的失败数据库发现：`review-evidence` job 的 `clarification` 是 `TRANSLATION_BUDGET_EXHAUSTED`，译者调用已完成，但独立 checker 尚未发送，因此没有 QA 结果。这不是语义 QA 误判。原 proof 为 789 字节完整 JSON；数字保护占位符和 checker 同时携带源文、候选，使按既有规则计算的 checker 请求估值达到 9468 tokens，超过原 10000 总额保留 2000 A 预算后的额度。

离线比较保留全部字段的轻量减负：紧凑 JSON 的 checker 估值为 9272；仅加入完整 SHA256 保护为 8736；二者合并仍为 8540，均不足以在原合同下放行。全局保护规则又会影响历史已保存候选与缓存，因此没有修改保护规则、策略版本或缓存，也没有降低预算估值。

最终处理：

- 保留实际 B 翻译、独立语义 QA、ContextGateway 字节与语言检查；没有仅凭 Latin 字符检测授予语义 QA 的 shortcut。
- 综合正常旅程 fixture 显式将总预算从 10000 改为 20000，A 保留额仍为 2000。该旅程验证完整交付，不验证 10000 token 预算资格。
- 新增数字密集 proof 的双分支回归：10000 时真实阻断，A review 不启动；30000 时实际完成 translate 与 check，取得 READY job 和 QA，且观察内容与 proof 原字节/哈希相符。
- 译校是新增的必要 B 请求与成本，不能计作 token 节省。真实模型、人工质量与优化验收状态不变。

证据：`delivery-proof-budget-red.log` 保存正常综合旅程的实际失败；`delivery-proof-budget-green.log` 保存 composite、agent workflow 与 Claude native 三个关联文件的最终通过。先前 `delivery-english-proof-first-green.log` 来自已撤销的尝试，不属于最终实现的验收证据。
