# D010 状态转换、批准门槛与事务 outbox

实现 StateMachine.transition、register_release_gate、enqueue_event 和 Outbox；状态和内部状态事件在一次 BEGIN IMMEDIATE 事务提交。92 条已声明合法转换逐一用实际 SQLite 验证，关键非法路径、当前版本批准、取消、stale 标记及三个真实子进程崩溃窗口均有测试证据。没有新增表或更改 D008 生产迁移链。

## 十项核对

| 卡项 | 实现/证据 |
| --- | --- |
| 01 显式状态表 | 主路径 RECEIVED→INPUT_PREPARING→PLANNING→EXECUTING→VALIDATING→REVIEWING→OUTPUT_PREPARING→READY→PUBLISHED，六个异常分支和有界恢复边；state-matrix.json 保存全部边和正常路径实际事件。 |
| 02 绑定校验 | task/attempt 必须存在且为最新 attempt_number，合同版本和 expected_state 精确匹配。旧 attempt、旧合同和并发预期状态不匹配均拒绝。 |
| 03 原子状态与 outbox | 状态 UPDATE 和 enqueue_event 同事务；事件 INSERT 故障和真实提交前退出均恢复原状态，没有半提交。 |
| 04 稳定标识与去重 | event_id、deduplication_key、task/attempt sequence、会话 conversation_sequence；重复同键同内容返回原记录，内容不一致拒绝。 |
| 05 派发确认 | 仅 send 返回后 acknowledge；失败保留 PENDING 和尝试次数。重发相同 event_id，接收端按此键去重。internal 不发送，public 使用 D007 完整验证。 |
| 06 发布门槛 | READY/PUBLISHED 查询 checks 中的 release.approval 与 checkpoint.current_revision_id，比较同 task/attempt/contract/hash/frozen route；EXECUTING→PUBLISHED 非法，payload PASS/approval 声明无效。 |
| 07 取消与失效 | CANCELLED 设置 cancel_requested，移除 release_registry；stale/publication_blocked 阻止批准登记和发布转换。后续状态不能撤销取消。 |
| 08 三个崩溃点 | 实际子进程 os._exit(81/82/83)，分别为提交前、提交后派发前、发送后确认前。 |
| 09 恢复结果 | 提交前保持 RECEIVED/0 事件；提交后保持 INPUT_PREPARING/2 事件（内部状态+公开 pending）；发送后未确认仍保留相同公开 event_id，持久接收器最终一条记录。见 crash-traces.json 及 fixtures。 |
| 10 独立复核交接 | consumer-interface.md 定义消费接口，root 对取消、序号隔离、stale、恢复边界提出的检查已转为反例并修正；整体 API/发布接入及独立审查由主代理继续汇总。 |

## 验证与证据

Windows 11、Python 3.13.0、SQLite 3.45.3；全部为本地隔离 SQLite/文件/子进程，没有外部模型调用。仓库无 HEAD，commit 为 null；source-hashes.json 保存当前源码哈希。

| 命令/阶段 | 结果 |
| --- | --- |
| 可导入 stub 的业务 RED（red.log） | 21 failed、1 passed，exit 1；失败由状态/事件/批准未实现引起，不使用 missing-import。 |
| 初版 GREEN | 22 passed，exit 0。 |
| stale/publication_blocked 登记反例（red-stale-fence.log） | 2 failed、32 passed，exit 1。 |
| 公开授权跨卡反例（red-public-authority.log） | 3 failed、10 passed，exit 1；schema-valid unapproved answer 泄漏和模板覆盖被实际触发。 |
| 完整当前 GREEN（green.log/runtime-tests.xml） | 129 passed，exit 0；其中 92 条声明的合法边全部提交真实状态与一条事件。 |
| reproduce_evidence.py（evidence.log） | exit 0；92 合法边、129 测试、实际崩溃退出 81/82/83。 |

```powershell
services/orchestrator/.venv/Scripts/python.exe -m pytest tests/integration/test_state_machine.py tests/integration/test_outbox.py -q --junitxml=docs/acceptance/D010/runtime-tests.xml
services/orchestrator/.venv/Scripts/python.exe docs/acceptance/D010/reproduce_evidence.py
```

公开事件的 sequence 使用 conversation_sequence；内部 sequence 独立于 provider 输入序号。StateMachine 的状态转换不生成公开答案，D018 需要读取已批准不可变原件并执行发布投影。接收端的持久 event_id 去重是发送后确认前崩溃窗口的必要组成部分。本实现没有模型启动入口，派发失败不会触发模型重跑。

主代理的跨卡审查指出 PublicEvent schema 声明不构成发布授权。修复后所有 Outbox.dispatch/replay 都调用 D018 的 server-owned project_event，读取实际 turn/blob/可信出版登记；不直接发送声明中的 text。无批准的 answer canary、假的用户消息内容和模型错误字符串均被新的三个反例捕获并阻断。
