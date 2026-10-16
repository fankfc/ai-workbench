# 本地开发工作单与交接

`scripts/work_order.py` 实现执行计划第五部分的单任务派工、开发交接、返修和阻塞报告。它离线运行，不连接模型，不更新任务板，也不把本地检查通过解释为真实接入或人工验收完成。

从仓库根目录使用已安装项目的解释器：

```powershell
$workOrderPython = '.\services\orchestrator\.venv\Scripts\python.exe'
& $workOrderPython scripts/work_order.py --help
```

## 单任务上下文

工作单要求精确任务 ID、显式合同版本和调用者批准的逐文件范围。`--allow` 支持尚不存在的新文件；不支持目录通配授权。任务卡里的路径是资料，不能扩大调用者的授权。

```powershell
& $workOrderPython scripts/work_order.py draft `
  --task-id D028 --contract-version 1 `
  --allow services/orchestrator/app/translation/input_pipeline.py `
  --allow services/orchestrator/app/translation/context_gateway.py `
  --allow services/orchestrator/app/translation/prompts/input_translator.txt `
  --allow services/orchestrator/app/translation/history.py `
  --allow tests/integration/test_input_translation.py `
  --output artifacts/work-orders/D028-draft-001
```

输出 `work-order.json` 包含原始 `task-board.json` 与 `data/tasks-*.json` 中选中的完整当前卡、指南中该卡的全部 checkbox/验收文字、合同版本、允许文件的初始字节哈希、当前成果索引，以及直接依赖的状态和成果/证据路径及哈希。目录证据使用递归文件清单摘要，不复制文件内容。它只把本任务和直接依赖的资料交给执行者，不展开传递依赖或载入历史交接报告。原始两份卡不同会报告 `SOURCE_CARD_DIVERGENCE`，原文同时保留。

权限、重复项和子集检查使用解析后的本机文件身份。Windows 大小写别名指向同一文件，不能用大写路径授权任务板、源任务数据或本机认证密钥，也不能把同一执行记录计为两次检查。Linux 保留其文件系统的大小写语义。交接的文件名沿用受信任允许清单，内容版本始终按实际字节计算。

缺失成果和未完成依赖保留为 `blockers`。生成草稿仍可进行，方便定位缺口和推进独立工作；它不会关闭依赖。任何写出的工作单、命令记录、交接、返修或阻塞报告都要求新的输出目录，已有目录会报错。

## 实际命令与交接

只有调用者在 `--` 后明确传入的 argv 才会运行。程序使用 `subprocess.run(..., shell=False)`；任务卡中的 `test_commands` 只是上下文，不会自动执行。参数中的 shell 字符不会被重新拼接解析。Windows `.cmd`/`.bat` 不直接运行；需要 shell 时必须由调用者明确传入 shell 可执行文件及参数。

```powershell
& $workOrderPython scripts/work_order.py record `
  --work-order artifacts/work-orders/D028-draft-001/work-order.json `
  --output artifacts/work-orders/D028-check-001 `
  --timeout 120 -- `
  .\services\orchestrator\.venv\Scripts\python.exe -m pytest tests/integration/test_input_translation.py -q
```

程序记录实际进程返回码、开始/结束时间、超时或启动失败、完整合并输出日志及其哈希和当前允许文件的哈希。检查会额外生成证据文件时，用重复的 `--evidence repository/path` 在同一调用中固定其实际输出哈希；文件缺失会被记录，交接验真将拒绝。命令失败时，CLI 保留记录并返回非零状态。

执行者应检查日志中的真实检查范围及失败原因。普通 `print('PASS')` 进程只能证明该进程实际返回，不能替代测试、语义判断或人工验收。测试缺依赖也不能冒充业务反例。

```powershell
& $workOrderPython scripts/work_order.py handoff `
  --work-order artifacts/work-orders/D028-draft-001/work-order.json `
  --record artifacts/work-orders/D028-check-001/record.json `
  --changed services/orchestrator/app/translation/input_pipeline.py `
  --unresolved '真实接入和人工验收尚未完成。' `
  --output artifacts/work-orders/D028-handoff-001

& $workOrderPython scripts/work_order.py validate `
  --work-order artifacts/work-orders/D028-draft-001/work-order.json `
  --handoff artifacts/work-orders/D028-handoff-001/handoff.json
```

`--changed` 必须与允许范围内相对草稿初始哈希的实际变化完全一致，包括新增或删除文件；重复或无关文件被拒绝。仅检查已有实现时不传 `--changed`。每条检查记录必须来自该工具，绑定同一任务和合同/工作单版本，并对应当前文件字节。代码改动后要重新运行检查；选中的任务卡、指南卡段或直接依赖的状态/成果引用变更后，要重新生成工作单。证据或日志缺失、被改写、进程返回非零、伪造 PASS、路径穿越、重解析点和硬链接均被拒绝。

验真结果 `local_handoff_accepted: true` 表示本地交接的版本、范围、实际记录和证据一致；`review_required: true`、`task_completion_changed: false` 同时保留。未完成依赖仍显示。A/人工的语义判断、真实模型验收及完整任务完成条件由后续正式流程处理。

## 返修和阻塞

查看严格 JSON payload 定义：

```powershell
& $workOrderPython scripts/work_order.py report-schema repair
& $workOrderPython scripts/work_order.py report-schema blocked
```

返修 payload 要求 `artifact_version` 和至少一个 `defects` 条目。每个缺陷包括 `defect_id`、`requirement_id`、`location`、`impact`、`failure_evidence`、`allowed_files`、`pass_condition`、`rerun_checks`。证据路径必须可取回；需求属于当前任务，修改范围不能扩大，重跑检查是 argv 数组。报告描述缺陷，不自动执行任何修复或检查。执行者先复现，再修改，再复验。

阻塞 payload 要求 `artifact_version`、`cannot_complete`、`direct_evidence`、`attempted_actions`、`external_conditions`、`independent_tasks`。不能推进独立任务时，最后一项用空数组。描述已经做过的有限动作和所需外部条件；不要把拟执行动作写成已完成。

```powershell
& $workOrderPython scripts/work_order.py report blocked `
  --work-order artifacts/work-orders/D028-draft-001/work-order.json `
  --payload artifacts/work-orders/D028-blocked-payload.json `
  --output artifacts/work-orders/D028-blocked-001
```

工具附加任务/合同/工作单绑定、实际证据哈希和允许文件的当前 `revision` / `revision_sha256`。`artifact_version` 是人类标签，当前字节版本由工具测得的哈希确定。下一位执行者读取当前工作单、未关闭缺陷、这些版本和证据索引即可接续。上游数据或公共合同变化仍需正式流程更新受影响任务及译文状态。

## 本地边界与已保存证据

`.omx/work-order-trust.key` 用于认证本工具生成的工作单、命令记录和报告。它由本机首次生成，已有 `*.key` 忽略规则覆盖，不能提交或当成交接内容复制。删失密钥后需在本机重新生成工作单/记录。这是同用户本地记录的完整性检查；拥有同一用户文件权限的程序可以读写密钥和仓库。它不提供操作系统沙箱，也不会监视声明范围之外的所有文件写入。

已保存一次 D028 的真实本地演练：`docs/acceptance/part-five/work-orders/D028-draft-v3/work-order.json`、`D028-run-v3/record.json`、`D028-run-v3/process.log`、`D028-handoff-v3/handoff.json` 和 `demo-results.json`。本次没有改 D028 实现，故 `changed_files` 为空。检查为 6 passed，另有原有 Starlette 弃用警告；D026/D027 未完成及缺失证据继续保留，没有改冻结状态。v1/v2 是加固和相邻依赖修复前的演练记录；当前依赖快照使用 v3。

开发测试的真实红/绿日志在 `docs/acceptance/part-five/work-order-tests/`。只运行工作单合同测试和上述 D028 定向检查，没有执行全量回归。
