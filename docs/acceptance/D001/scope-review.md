# D001 需求范围复核

日期：2026-10-13（Asia/Shanghai）。需求版本：v1。复核者：Codex；类型：代理文档审阅与结构/逐字对照。范围责任角色：产品负责人 + 技术负责人。人类审批/用户签字：未声称。产品验收：全部未验证。

结论：D001 文档基线具备十五项原文需求、来源路径/行号、验收定义、验收责任角色、非目标、硬约束、未知事实及决策责任。未发现阻止 D002 的未决实质范围冲突；能力未知项只阻塞各自依赖的后续功能/发布。此结论不代表真实连接、GUI、双语文档或优化资格通过。

## 输入与来源

全文读取主计划（427 行）、翻译规格（175 行）、质量计划（249 行）、基础手册（653 行）及原工作流（276 行）；长输出分段补读，使用 `rg -n` 定位需求和冲突。源文件未修改，冻结 SHA-256 在 `docs/decisions/requirements-v1.json`。

R01–R15 来源：`docs/superpowers/plans/2026-10-13-industrial-agent-workbench-plan.md` 第 40–54 行。源需求栏、完成证据栏和完整表格行逐字保存；验收定义为由专门规格细化的独立字段，不能冒充原需求引文。

本轮实施授权由主协调代理转交：用户要求阅读全文并开始实现部分一。基础手册旧“本轮只写文档”说明按历史编写轮次解释，见 DEC-001。未声称拥有本子代理不可见的历史用户逐字聊天原文，也未新增真人批准。

## D001 十项审阅

| 操作 | 结果 | 可核对位置 |
| --- | --- | --- |
| 01 原样摘录 R01–R15，保留来源与责任 | 已复核，15/15 一致 | JSON `requirements`：id/statement/source/original_completion_evidence/acceptance_owners |
| 02 Windows 11 x64、本地单用户、PDF/DOCX/Markdown | 已复核 | scope-v1 首版范围；JSON `scope` |
| 03 四项非目标 | 已复核 | scope-v1 NG01–NG04；JSON `non_goals` |
| 04 A 质量优先、核心推理、不固定两次调用 | 已复核 | HC01/HC02；scope-v1 规则 1–2；DEC-002 |
| 05 Claude 全输入、中文输出、追问同规则、GPT 零强制翻译 | 已复核 | R07/R08/R10；HC03/HC04；scope-v1 规则 3–5 |
| 06 A 亲自产出完整英文定稿、双语同版本 | 已复核，独立硬约束保留 | R09；HC05/HC06；scope-v1 规则 6–7；DEC-003 |
| 07 内部过程不进入聊天、真实失败不冒成功 | 已复核 | R11；HC07；scope-v1 规则 8–9；DEC-008 |
| 08 GPT 入口和 ZCode 桌面/CLI 事实缺口及角色 | 已复核，保持 unknown | JSON U01–U06；scope-v1 未知表；DEC-005/006 |
| 09 逐项对照需求、排除项、已确认目标及当前授权；登记冲突 | Codex 文档复核完成，无人类签字声明 | 主计划/原工作流已确认目标；DEC-001–009 |
| 10 需求版本、复核人/时间、变更升版 | 已复核 | JSON 元信息/change_control；decision-log 头部及升版规则 |

## 逐项需求核对

| 需求 | 原文源行 | 原文/原证据 | 验收定义及角色 | 产品实测 |
| --- | --- | --- | --- | --- |
| R01 | 40 | 一致 | 有，QA-01 质量基准 | not_verified |
| R02 | 41 | 一致 | 有，完整用量及资格 | not_verified |
| R03 | 42 | 一致 | 有，实际身份/分支 | not_verified |
| R04 | 43 | 一致 | 有，真实 ZCode/GLM | not_verified |
| R05 | 44 | 一致 | 有，四域成果/领域验证 | not_verified |
| R06 | 45 | 一致 | 有，实际聊天 GUI 操作 | not_verified |
| R07 | 46 | 一致 | 有，全上下文输入翻译 | not_verified |
| R08 | 47 | 一致 | 有，检查后中文输出 | not_verified |
| R09 | 48 | 一致 | 有，A 完整原件/同版配对 | not_verified |
| R10 | 49 | 一致 | 有，零强制翻译 | not_verified |
| R11 | 50 | 一致 | 有，服务端公开白名单 | not_verified |
| R12 | 51 | 一致 | 有，恢复/去重/取消/隔离 | not_verified |
| R13 | 52 | 一致 | 有，签名/迁移/恢复 | not_verified |
| R14 | 53 | 一致 | 有，请求/累计量归一化 | not_verified |
| R15 | 54 | 一致 | 有，忠实语义/歧义门槛 | not_verified |

验收责任人均为角色，没有捏造姓名、人员已任命或人类批准。各项 `planned_evidence` 明确为后续预定证据，不把路径存在与否或本文生成当作产品通过。

## 实际核验

环境：Windows PowerShell 7.6.5；仓库根 `C:/Users/asd15/Documents/ChatGPT/ai`。模型标识仅知当前工具身份为 Codex，不推断底层版本。git 提交未知/不存在（`git rev-parse --verify HEAD` 退出 1）；源文件用哈希定位。

1. D001 指定解析命令的等效带显示字段版本实际运行：

   ```powershell
   Get-Content -Raw -LiteralPath 'docs/decisions/requirements-v1.json' |
     ConvertFrom-Json |
     Select-Object -ExpandProperty requirements |
     Select-Object id, statement, product_validation_status |
     Format-Table -AutoSize
   ```

   退出 0；解析出 R01–R15，十五项产品实测均 `not_verified`。

2. 执行内存中的文档一致性核验（完整命令见 implementation-report）：检查 15 个连续且唯一 ID、源表格行、需求栏/证据栏逐字一致、角色/验收/预定证据非空、15 个细化来源位置有效、5 份来源哈希与行数、6 个 unknown、9 个硬约束、Codex 复核及未声称人类签字。退出 0，结果 `PASS`。

3. `rg -n` 与源段落逐条审阅核对验收含义和冲突优先级。发现 R06 验收来源段落原定位过窄，已修正为主计划 337–361 行后再次核验。

没有建立业务单元测试、安装依赖、调用外部模型或测量产品性能。上述 PASS 仅针对文档一致性。

## 拒绝冻结条件与未知项

D001 负例的文档审阅结论：若删去 A 亲自产出完整英文定稿、将 B 全文加 A PASS 视为合格原件，或将质量改为基线 95%，违反 HC01/HC05 及 DEC-002/003，必须拒绝冻结。此次未改坏真实文件来制造业务失败，也没有把源代码缺失作为负例。

未实测：GPT 入口；Claude/ZCode 真实模型及工具/取消/恢复/用量；ZCode 桌面/CLI 会话、登录、额度（三项分别）；文档/OCR；质量、翻译 holdout 与节省；签名安装/更新/迁移/恢复和 SLO。它们在 JSON U01–U06 均有责任角色、解决任务和阻塞范围，详情见 scope-v1。不存在以默认值替代这些实测的记录。

后续实质变更必须升版，保留 v1 与来源，重新审阅受影响任务；此次未修改任务板、原计划或源码，未提交。
