# D001 实施报告

日期：2026-10-13（Asia/Shanghai）。需求版本：v1。实施与文档复核：Codex。人类签字：未声称。提交：未创建；冻结时 HEAD 不存在。状态：D001 文档基线已生成并完成代理审阅；主协调代理已独立核对十五条原文及五份源哈希并审阅范围/决策；产品验收全部 `not_verified`。

## 文件

| 文件 | 结果 |
| --- | --- |
| `docs/decisions/requirements-v1.json` | R01–R15 原文、完整源行、来源位置/哈希、原完成证据、简洁验收定义、角色责任、9 个硬约束及 6 个未知项 |
| `docs/decisions/scope-v1.md` | Windows 11 x64、本地单用户、PDF/DOCX/Markdown、四非目标、语言/来源/质量/发布边界与升版规则 |
| `docs/decisions/decision-log.md` | 9 项冲突/解释决策、优先级、结论、角色、冻结版本/时间与变更控制 |
| `docs/acceptance/D001/scope-review.md` | 十项操作及十五需求对照、实际命令/退出码、负例拒绝条件、未知范围 |
| `docs/acceptance/D001/implementation-report.md` | 本报告与可重复文档核验命令 |

仅写上述五个授权文件；未修改任务板、源计划或源码，未安装依赖、运行业务测试、调用模型、发布或提交。并行代理可能修改其他任务文件，本报告不将其列为 D001 变更。

## 验证证据

PowerShell 7.6.5，在仓库根运行。`git rev-parse --verify HEAD` 实际退出 1：`fatal: Needed a single revision`。因此来源绑定 SHA-256 而非虚构提交号；模型底层版本不可从当前工具确认，标未验证。

D001 JSON 解析命令实际退出 0，输出十五项 R01–R15。下列一致性命令实际退出 0；完整输出为 `{"requirements":15,"verbatim_rows":15,"source_hashes":5,"acceptance_locations":15,"unknowns":6,"hard_constraints":9,"reviewer":"Codex","human_signoff":"not_claimed","result":"PASS"}`。这不是产品测试通过声明。

```powershell
$ErrorActionPreference = 'Stop'
$baseline = Get-Content -Raw -LiteralPath 'docs/decisions/requirements-v1.json' | ConvertFrom-Json
$expected = @(1..15 | ForEach-Object { 'R{0:D2}' -f $_ })
if ($baseline.requirements.Count -ne 15) { throw 'Requirement count must be 15' }
if (($baseline.requirements.id -join ',') -cne ($expected -join ',')) { throw 'Requirement ids must be R01-R15 in order without duplicates' }
foreach ($r in $baseline.requirements) {
  $line = (Get-Content -LiteralPath $r.source.path)[$r.source.line - 1]
  if ($line -cne $r.source.original_row) { throw "Source row mismatch: $($r.id)" }
  $cells = $line.Split('|')
  if ($cells[1].Trim() -cne $r.id -or $cells[2].Trim() -cne $r.statement -or $cells[3].Trim() -cne $r.original_completion_evidence) { throw "Verbatim requirement mismatch: $($r.id)" }
  if ($r.acceptance_definition.Count -lt 1 -or $r.acceptance_owners.Count -lt 1 -or $r.planned_evidence.Count -lt 1) { throw "Missing acceptance/role/evidence: $($r.id)" }
  if ($r.product_validation_status -cne 'not_verified') { throw "Unmeasured claim: $($r.id)" }
  $aLines = Get-Content -LiteralPath $r.acceptance_source.path
  if ($r.acceptance_source.lines[0] -lt 1 -or $r.acceptance_source.lines[1] -gt $aLines.Count) { throw "Invalid acceptance source location: $($r.id)" }
}
foreach ($s in $baseline.source_documents) {
  $hash = (Get-FileHash -LiteralPath $s.path -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($hash -cne $s.sha256) { throw "Source hash mismatch: $($s.path)" }
  if ((Get-Content -LiteralPath $s.path).Count -ne $s.line_count) { throw "Source line count mismatch: $($s.path)" }
}
if ($baseline.reviewer -cne 'Codex' -or $baseline.human_signoff -cne 'not_claimed') { throw 'Reviewer/signoff mismatch' }
if (($baseline.unknowns | Where-Object status -ne 'unknown').Count -ne 0) { throw 'Unmeasured capability is not unknown' }
if (($baseline.hard_constraints | Where-Object id -eq 'HC05').statement -notmatch '完整英文定稿') { throw 'Missing A canonical hard constraint' }
if (($baseline.hard_constraints | Where-Object id -eq 'HC01').statement -notmatch '禁止.*质量折扣') { throw 'Missing quality priority hard constraint' }
[pscustomobject]@{requirements=15;verbatim_rows=15;source_hashes=5;acceptance_locations=15;unknowns=$baseline.unknowns.Count;hard_constraints=$baseline.hard_constraints.Count;reviewer=$baseline.reviewer;human_signoff=$baseline.human_signoff;result='PASS'} | ConvertTo-Json -Compress
```

`rg -n` 与源段落审阅另外核对了含义、角色、排除项和冲突。R06 的细化来源已修正为主计划 W4 第 337–361 行。人工双语评测、真实模型与产品验收均未执行，不把 Codex 文档审阅写成人工评测。

## 未决项与风险边界

没有阻止 D002 的首版范围冲突。GPT 入口、ZCode 桌面/CLI 会话/登录/额度、真实模型/工具/用量、文档/OCR、质量/翻译/节省、签名/恢复/SLO 均 unknown；对应 U01–U06 指定角色与后续 D/QA 卡，阻塞相关能力启用、声明或发布。

旧“本轮只写文档”按历史编写轮次解释，当前实施授权优先（DEC-001）；A 质量优先和完整英文定稿未降级（DEC-002/003）。冻结不等于用户批准新增需求、不等于软件工业化完成。主协调代理独立复核反馈未见阻断范围冲突；本子代理不改任务板状态。
