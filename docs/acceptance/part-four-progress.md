# 阶段四运行时集成与验收记录

日期：2026-10-15（Asia/Shanghai）。范围由用户明确确认为[04-runtime-sop.md](../superpowers/plans/2026-10-13-execution/04-runtime-sop.md)：S01–S40，以及追问和切换、文档、业务检查、综合任务、异常、发布核对、上下文和返修交接。

本轮保留前三阶段历史冻结和前60张开发卡，以阶段四独立目录交付运行修复及当前版本验收装置。已完成本轮本地运行集成修复与所选机械验收；最终统一批次通过，完整SOP终验、正式发布、质量与token目标仍保持开放。

下表中Claude本地行为采用明确的模型fixture与真实产品模块；不构成真实Claude生产接入资格。

## 最终统一验证

最终有效批次为[final-v4](part-four/final-v4/verification.json)，同一冻结版本执行以下检查：

| 检查 | 实际结果 |
| --- | --- |
| Python默认本地回归 | 1595通过，0失败、0跳过；1项真实提供方测试按默认标记排除 |
| 桌面单元测试 | 88通过，0失败、0跳过 |
| 实际Electron流程 | 35通过，0失败、0跳过或重试 |
| 严格契约、类型检查、生产及测试构建 | 全部退出码0 |
| S01–S40及第5–12节的所选机械检查映射 | 48/48本地通过，完整步骤验收均未提升为通过 |

装置自身44项及修复关联测试已包含在上述Python回归中，不叠加计数。该批产品、测试装置、映射与规程哈希前后一致；[证据清单](part-four/final-v4/evidence-manifest.json)的110个文件已重新逐件校验，见[完整性复核](part-four/final-evidence-integrity.json)。[历史哈希复核](part-four/preserved-final.json)确认154份冻结、开发卡及阶段三记录无变化。本轮真实模型调用为0。

| 标识 | SHA-256 |
| --- | --- |
| 产品源码 | `f5807a69331c3a2ee9108d527b6923e54f55b2219de35cd56cd01935534a0e7a` |
| 产品及验收装置源码 | `5333fe6669cd1e3e8c6b81142d71edacc6991bd3be992bc9561467f4bbb8c436` |
| 所选检查映射 | `47e74ebdc52378b7ebd5e4d059ce5cb8b5baf31aa91b19977999c47548e856f9` |
| 原运行规程 | `c62590793932ee97c6a88f07b27062433e4dcbeab8093d42178ad22c6837c311` |

机器结果为`local_sop_passed=true`、`full_sop_accepted=false`。真实提供方、人工、功能发布及优化目标均独立保持未通过；[汇总JSON](part-four-progress.json)列出同一结论。

## 运行集成修复

| 位置 | 修复及实际行为 |
| --- | --- |
| [桌面后端生命周期](../../apps/desktop/src/main/backend.ts) | 恢复日志写入失败仍终止实际受管进程树；启动过程中停止使旧启动失效，避免关闭后重新产生后台进程。关闭整个生命周期内的新启动和并发停止另以独立关闭操作约束。 |
| [持久调度和取消](../../services/orchestrator/app/runtime/supervisor.py) | 用户取消后终止挂起的本地等待，后续任务可继续；清理任务按attempt共享，关闭时等待正在进行的清理。远端未确认停止仍保持待确认，不能自动重发。 |
| [启动发布恢复](../../services/orchestrator/app/runtime/startup_publication.py) | 已持久化的READY成果通过原批准、当前attempt、路由、源字节、机械证据和依赖版本复验后继续发布；Claude复用已有合格中文译文，完整文件组与答案仍同事务提交。恢复不再次调用模型或译者。 |
| 恢复拒绝边界 | 缺批准、改证据/原件、取消、旧attempt、未知当前远端、事故冻结或错配文件组均不能发布。未知owner保留其lease并推迟；坏checkpoint保留原始字节并隔离，重复重启不拖垮所有会话；演示成果不能在真实模式启动时发布。 |
| [A验收的实际证据](../../services/orchestrator/app/runtime/workflow.py) | 给A提供真实C检查正文，核对源SHA、成果版本、验收项及布尔结果。Claude通过QA和ContextGateway取英文视图，代码与数字保持保护；GPT不调用强制翻译。原生文本桥显式维持现有GPT范围，不能把Claude英文视图替换为原文。 |
| [失败请求的底层计量](../../services/orchestrator/app/providers/scoped_codex_worker.py) | stdout错误先于stderr中的SSE身份记录读取时，失败路径先完整关闭和读取，再确定唯一started引用；stdout用量收据严格绑定该引用。缺失/冲突身份、重复收据、未结束reader或输出截断均保持未知，失败任务不产生业务capture。同步源码pin，旧源资格不继承。 |
| [Windows备份目录提交](../../services/orchestrator/app/storage/directory_commit.py) | 备份、导入与恢复只对Windows的`winerror 5/32/33`进行最多5次同路径重命名，额外等待合计0.30秒；每次重验目录身份、父目录、reparse与目标不存在。持续占用或归属变化时保留暂存目录，原数据不变，不重做快照或外部请求。API返回中文占用提示，恢复失败解除存储冻结。 |

每项修复都先保留实际失败反例，再实施和复验。独立审查发现的相邻竞争和损坏记录边界也单独保存原始发现和后续结果。

新增的Claude机械证据译校会增加B请求与预算预留。综合旅程原fixture合同的10,000总token、2,000 A预留不足以通过新增checker请求的保守预检查，正常旅程fixture明确改为20,000总token、保留2,000 A。另有数字密集proof回归：10,000预算时阻断，30,000时实际完成fixture译者、独立checker及READY QA。产品预算守卫和QA条件没有放宽；这些是测试合同额度，不代表实际消耗或token节省。见[预算分析](part-four/delivery-proof-budget-analysis.md)。

## 验收装置

入口为[scripts/phase_four_verify.py](../../scripts/phase_four_verify.py)，映射为[quality/runtime-sop.json](../../quality/runtime-sop.json)。它为40步及第5–12节建立共48项所选本地机械检查映射，逐项核对本轮pytest、Vitest及Playwright的精确测试标识；缺失、失败、跳过、重复或重试不算通过。类型检查、构建和严格契约检查也纳入统一结果。

每批输出是新目录，拒绝覆盖既有目录，保存实际命令、退出码、日志、JUnit/JSON、产品与装置源码哈希、规程及映射字节。映射中的`local_status`仅代表所列本地机械检查；`full_step_accepted`、真实提供方、人工、优化及完整SOP验收分别记录，不能由本地测试通过自动提升。

测试原始SQLite、proof和artifact使用短临时目录，路径单独写在报告中。这些测试临时产物没有纳入sealed manifest；manifest封存本轮命令、测试报告、观测映射和源码标识，不能称为同一次真实全链路交付的逐件归档。

首个全量诊断批次[final-v1](part-four/final-v1/verification.json)保留28项Python失败，其中暴露了装置临时路径过长和综合测试预算不足。该批次在后续修复期间源码变化，报告的`source_unchanged=false`，不能计作最终版本通过证据。

第二批`final-v2`使用短目录，仍复现底层失败用量竞态，因此也作为诊断批次保留；不能用该用例的单独通过替代全量失败。stdout/stderr不存在跨流先后保证，已用确定性延迟入队探针隔离，不通过加长sleep或放宽身份/计量检查处理。

第三批`final-v3`的Python结果为1项失败、1576项通过：创建备份时，Windows将暂存目录重命名为提交目录返回`WinError 5`。错误发生在备份内容篡改检查之前；独立运行同一用例通过，不能据此覆盖本批失败。[实际Win32占用探针](part-four/windows-directory-commit-probe.json)证明不允许删除共享的文件句柄可稳定产生同一错误，释放后同一目录可提交；本批实际占用者尚未确定，不能归因于某个扫描程序或后台模型。

持续占用留下的受管`.pending-*`目录不注册为可用备份，也不视为已恢复。占用释放后可从界面重新执行备份或恢复；本轮没有新增自动扫描、自动发布或强行关闭其他程序句柄的行为。

## 独立审查

- [启动发布恢复](part-four/independent-startup-review.md)：原批准/字节/版本/owner/文件组和损坏记录边界。
- [取消与桌面生命周期](part-four/independent-cancellation-review.md)：实际子进程及异步清理竞争。
- [A验收证据及语言路径](part-four/independent-evidence-review.md)：实际proof正文、Claude英文视图和原生桥范围。
- [worker失败用量](part-four/independent-worker-usage-review.md)：7个独立调度/身份变形探针；SSE身份早到和晚到均正确保留绑定收据，缺失或歧义保持未知。[修复记录](part-four/scoped-usage-race-repair.md)包含220项关联验证、原始失败和源码pin边界，重叠批次不相加。
- [Windows备份目录提交](part-four/independent-backup-commit-review.md)：独立实际共享锁验证释放、持续占用、目标出现和源目录替换；全部句柄关闭，原数据保留。[修复记录](part-four/backup-directory-commit-repair.md)保存原始反例与53项关联验证。

这些是其他代理的工程审查，不代替真实供应商、领域、双语或无障碍人工验收。

## 完整运行验收仍需的条件

| 范围 | 当前未结条件 |
| --- | --- |
| 真实接入及连续旅程 | 生产注册表和当前生命周期资格尚未补齐；Claude原生适配及生产装配仍未支持，GPT/ZCode缺完整真实四域证据。当前生产保守A主导策略保留，不能声称真实B委派已验收。 |
| 第5、9、12节 | 当前记录验证所列局部机制，尚不是一次真实提供方的连续追问/接管、限流/文件占用/远端取消、I-007至v3完整修复旅程。READY之外的外部任务仍保守阻断，真实远端查询与继续入口需随受支持适配器补齐。 |
| 文档及综合交付 | 简单受支持结构的真实本地渲染由测试验证；复杂DOCX、扫描OCR、关键公式/引用和多模态语义仍需各自能力与人评。不能扩大固定CSV及局部反例的适用范围。 |
| 第11节及优化 | 本轮修复实际证据可读性和来源绑定；未完成全部按差异选材、跨章节覆盖/汇总决策优化。独立基线、holdout、功效分析、盲评和完整真实计量仍缺，不能报告A质量等价或token节省。 |
| 工业化发布及人工操作 | 真实Windows IME/Narrator/多屏、签名安装与回滚、完整性能/24小时、试用与第三方交接继续按阶段三清单验收。 |

## 重跑

从仓库根执行：

```powershell
& .\services\orchestrator\.venv\Scripts\python.exe scripts/phase_four_verify.py --python --desktop
```

不传lane参数只检查映射，报告明确为`mapping_only`，不能计作测试执行或阶段完成。仅执行一个lane时，缺少另一lane的步骤保持未测。

桌面仍从仓库根执行`npm run build:desktop`和`npm run desktop`；演示模式为`npm run desktop:demo`。本轮没有重新生成或安装Windows安装包，阶段三旧内部安装包不包含本轮修复。
