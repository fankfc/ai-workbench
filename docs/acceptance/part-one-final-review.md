# 部分一最终复核记录

2026-10-13。复核对象为 backend-source-hashes.json 的101份源码及依赖锁；全量测试起点、最终CLI场景重放和最后路径审计的字节一致。原19份工作文件只更新任务板、部分一任务数据和索引，需求与规格保持原字节。

Root最终命令实际退出0：780 passed、1 real_provider deselected、0 failure/error，212.62秒。backend-junit.xml含780个用例。严格合同校验为1.0版、两个JSON Schema一致。单独选取真实接入检查得到1 skipped、16 deselected，未新增真实执行器启动。

已闭环的独立反例及证据：

- [存储与恢复](remaining-storage-recovery-review.md)：真实SQLite迁移、不可变原件、事件去重/乱序、终态保持和子进程崩溃窗口；原问题保留前后证据。
- [进程与作用域](remaining-process-scope-review.md)：真实Windows Job清理、未知远端阻断、查询失败后的真实清理状态，以及深度冻结的英文视图引用。
- [发布与调用边界](remaining-final-runtime-review.md)：原五种审查/合同重绑定均阻止发布；B走Claude启动0次，远端已接受后断流启动1次，FAILED后不新增调用。历史已发布版本和当前资格分别核验。
- [当前远端恢复关联](remaining-recovery-current-reference-review.md)：另一实现作者用临时真实SQLite独立检查16/16；核对实际当前A/B步骤、连接和标识，缺标识保持未知，查询/验证期间切换步骤时拒绝旧完成结果。
- [最终综合场景](remaining-final-d20-evidence.json)：独立8项定向验证通过；真实数据、代码、结果、SVG和报告五节点哈希/依赖一致，上游改版使下游失效，返修后预算保留45个fixture token及三个请求并阻止下一次调用。
- [交接一致性](remaining-handoff-consistency-review.md)：11/11检查通过，另一读者再次确认；20张卡片状态、证据路径、映射、780项结果与101份哈希一致。

这些复核使用实际本地模块和文件；外部模型响应、语义判断及用量样本明确为fixture。真实执行器仅有本轮记录的三次启动尝试（ZCode2、Codex1），并无已核验真实任务完成；真实账单请求数及缺失用量仍unknown。

最终状态为17 done / 3 blocked：D004需要Claude登录；D005需要选择并核验ZCode实际模型；D020需要必需真实A/B贯通。D006仅路线决策完成，连接未启用。部分一完整完成、功能就绪、质量/token优化资格均false；GUI、完整翻译、A原件来源和正式双语发布保留后续任务。

没有剩余的已记录可复现代码缺陷。本记录是限定范围的原生独立复核与root验收，不是正式合并/发布批准；未创建提交、合并或PR。
