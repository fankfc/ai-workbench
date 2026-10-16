# D012 重启恢复与 provider 事件去重

实现 Recovery.recover 与 Recovery.ingest，34 项测试通过。已有远端请求先查询状态再决定观察、核验或阻塞；unknown 不自动重发。真正未启动的本地任务保留原状态并记录 local_pending；已接受但缺远端引用的任务保持 unknown。provider 连续序号与本地 outbox 序号分开，重复、旧版本、取消、缺口和乱序决定均持久保存。

## 十项核对

| 卡项 | 实现/证据 |
| --- | --- |
| 01 未终结读取 | 查询当前未终结 attempt，保留 external_request_id/external_execution_id、checkpoint、lease；取消且远端待确认的任务仍对账。 |
| 02 四类远端状态 | running/completed/failed/unknown；查询异常按 unknown 记录异常类型。真实远端查询由调用方注入，测试回调提供确定状态，不冒称模型已验证。 |
| 03 恢复动作 | running 只观察已有执行；completed 使用 verifier 回调并最多进入 VALIDATING；failed 保持原请求引用并失败；unknown BLOCKED，保留原外部标识。无 model-start 回调。 |
| 04 去重与审计 | task/attempt/provider sequence 的 fingerprint 和 provider_event_id 语义键持久在 checkpoint；原始事件/重复接收决定写 internal outbox。 |
| 05 旧版本与取消栅栏 | 旧 attempt、合同、显式旧 route、FAILED/PUBLISHED、取消后的完成均只记拒绝审计，不接受 PASS，不公开。 |
| 06 缺口与乱序 | provider_event_buffer 保存 gap；连续序号到达后依次排空，完成前缺口不越过核验；历史缺少的乱序不应用。稳定键重复可关闭序号缺口，但不重复应用。 |
| 07 过期租约与 unknown | 实际 SQLite 任务使用过期租约，两个新 Recovery 实例均查询同一已有请求并 BLOCKED；一 attempt、零新步骤。remote-unknown-trace.json 保存调用与事件。 |
| 08 取消/迟到 | 查询中发生取消时不调用完成 verifier；取消远端已停止则 external_stop_confirmed=1，仍 CANCELLED；缓冲 provider.error 后停止 drain，后续 completed 不能将 FAILED 改成 VALIDATING。 |
| 09 崩溃一致性 | D010 三个真实进程崩溃窗口验证共享事务/outbox。D012 事件 INSERT 故障回滚 checkpoint/sequence/state；重建 Recovery 后从持久 gap/history 继续，原文件和用量不重写。 |
| 10 决策与对账 | consumer-interface.md 定义 callback 约束；unknown trace 和 recovery-report.json 提供人工对账的原 task/attempt/外部标识、顺序与拒绝原因。 |

Windows 11、Python 3.13.0、SQLite 3.45.3，本地真实数据库和故障装置，无外部模型调用。commit 为 null，source-hashes.json 保存源码哈希。

| 验证阶段 | 结果 |
| --- | --- |
| 可导入 stub 的业务反例（red.log） | 16 failed，exit 1。 |
| 初版 | 16 passed，exit 0。 |
| 迟到/重复关闭缺口/缺路由反例（red-late-events.log，包含 D010 gate） | 3 failed、33 passed，exit 1。 |
| 未启动本地任务反例（red-local-pending.log） | 5 failed、18 passed，exit 1；包括两个尚未修正的迟到/缺口问题。 |
| 独立审查反例（red-independent-review.log） | 4 failed、23 passed，exit 1；查询/核验期间终态被恢复覆盖及未来稳定键重复丢序号。 |
| 独立审查修复（green-independent-review.log） | 27 passed，exit 0。 |
| 当前步骤引用变更前的本卡核验（green-independent-review.log） | 27 passed，exit 0；后续 green.log/recovery-tests.xml 已更新为 34。 |
| 当前步骤引用跨卡 RED（red-current-step-reference.log） | 7 failed、27 passed，exit 1；包含错误 provider/旧 main 引用、accepted 缺引用及查询时步骤变更。 |
| 当前步骤引用 GREEN（green-current-step-reference.log/recovery-tests.xml） | 34 passed，exit 0。 |
| 当前步骤引用变更前的 D008/D010/D012 合并回归（lane-regression.log） | 212 passed，exit 0；此历史命令不包含最后七个新增反例。 |
| 当前步骤引用最终他人只读复核 | 16/16 实验通过，零真实模型启动、零公开答案；101 冻结源码与锁无变化。 |
| D010 证据重建脚本 | exit 0，同时输出 1,2,2,1,3 的实际决策与 unknown 的持久轨迹。 |

```powershell
services/orchestrator/.venv/Scripts/python.exe -m pytest tests/integration/test_recovery.py -q --junitxml=docs/acceptance/D012/recovery-tests.xml
services/orchestrator/.venv/Scripts/python.exe docs/acceptance/D010/reproduce_evidence.py
```

checkpoint.provider_last_sequence 默认从 0 开始；task_runs.last_sequence 只分配本地 outbox。测试明确先写 API message.accepted/response.pending（本地 1/2），再接 provider 1/2，均接受且本地事件序号继续为 3/4。observe callback 必须只接续既有执行，不能启动新请求；执行前重查当前 attempt 与取消。完成核验回调不构成发布授权，READY/PUBLISHED 仍经过 D010/D018 的当前版本门槛。

独立审查 lane 的两个 HIGH 形成四个有效 RED。修复在查询后、verifier 前及最终写事务核对 FAILED/PUBLISHED，查询或 verifier 中发生的终态改变均保留；稳定事件键重复的未来序号存入 no-effect buffer，缺口闭合后推进这些序号再处理完成，不二次应用 payload。原独立复现 JSON 保留，复核由该 reviewer 执行。

D014 多步骤的权威 active_external_request 由真实步骤记录交叉校验。Recovery 对当前 B/A 模型的实际 profile 和远端引用查询，而不是用冻结 A profile 与历史首次请求；accepted=True 但无 refs 时不查询旧 main 列，保持 BLOCKED unknown。查询、核验或观察前后切换步骤会拒绝旧响应。七个新增业务反例已先 RED 后 GREEN；生产与测试已冻结。

其他作者的最终独立只读复核已完成 16/16 实验，remaining-recovery-current-reference-review.json 保存实际临时 SQLite/callback 与 D014 stream 数据重放。覆盖当前 B profile/refs、仅 request/仅 execution 引用、accepted 无引用拒绝旧 main fallback、role/contract/execution/mirror 损坏时无 callbacks，以及 query/verify 期间换 step 的 external_reference_changed。没有模型启动或公开答案，源码/测试前后相同且匹配根代理的 101 文件冻结快照。该审查独立于本卡作者；不把局部复核称为 formal merge APPROVE。完整接口见 consumer-interface.md，公开 D007 合同未改变。
