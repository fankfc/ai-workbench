# 第四阶段独立审查：取消、桌面关闭与验收口径

审查时间：2026-10-15。审查者为 A review 证据修复子代理；本次只读审查其他代理实现，没有修改被审代码，没有重复执行已通过测试。额外运行两个临时状态、无模型调用的定向竞争探针；桌面探针在 finally 中清理其真实受管子进程。

## 发现

### P1：shutdown 会中断已经开始但尚未完成的取消清理

证据：`services/orchestrator/app/runtime/supervisor.py:200-209` 在清理开始时加入 `_cancelled`；第二个取消调用立即返回。`shutdown:288-293` 因此不等待 watcher 发起的清理，直接取消 `run_once`。后者在 `276-279` 取消 watcher，进而取消 watcher 正在等待的实际 cleanup。

独立探针时序：planner 在本地 Event 挂起；将当前任务置为已请求取消；等待 watcher 进入 cleanup；cleanup 用 0.2 秒等待模拟实际终止；此时调用 shutdown。实际结果：`cleanup_done=false, cleanup_aborted=true, diagnostics=[], runner_done=true`。这说明“已开始清理”被当成“已完成清理”，没有确认清理完成，也没有记录失败。

修复要求：每个 attempt 共享同一个清理 Task；重入应等待该 Task，取消 watcher/dispatcher 不能顺带中断清理。仍须保留真实远端未知和取消待确认，不可设置虚假停止确认。已告知 root 和原实施代理。

### P1：关闭完成后，挂起的启动仍可创建后台进程

证据：`apps/desktop/src/main/backend.ts:35-43` 在 mkdir 返回后直接 spawn，没有检查 stop 或启动代次。`stop:90-100` 在尚未创建 child 时会完成并返回。`apps/desktop/src/main/index.ts:45-46` 先显示窗口再等待 start，立即关闭窗口可进入这条竞争。

独立探针将原始 backend.ts 经 esbuild 在内存加载，只暂停真实 `node:fs/promises.mkdir` 的返回以模拟慢磁盘；调用 start 后、mkdir 返回前执行 stop，再恢复 mkdir。实际结果：`afterStop=offline, afterPendingStart=ready, managedProcessAlive=true`。finally 再次执行 stop 清理子进程。

修复要求：stop 应撤销未完成的启动，并与启动建立清晰的串行或代次边界；关闭返回后不得由旧 start 创建进程或覆盖状态。已告知 root。

## 已检查且未发现新增阻断的问题

- journal 两次写入分别捕获错误，写失败仍进入实际 terminate；清理未确认时保留进程关联并阻断重复启动。
- API 取消会先持久化取消并撤销 lease；当前 watcher 终止的是其自有 execution Task，不把取消待确认当成远端已停止。旧 attempt、外来 owner、发布取消 fence 保留。
- 新增用户取消测试覆盖正常返回与抛出异常的 cleanup，但未覆盖上述取消清理进行中再 shutdown 的竞争。

## 验收装置附加审查

只读检查了 `scripts/phase_four_verify.py`、`quality/runtime-sop.json` 与 `tests/acceptance/test_runtime_sop.py`。未发现将 fixture 成功提升为真实模型验收的通道：

- 映射固定字节哈希并绑定 SOP 字节；每个引用对应源文件中的确切测试定义。
- 每次输出必须使用新的仓库内目录；测试报告由本轮执行生成；缺失、重复、跳过、失败、重试或报告计数异常均不能取得完整本地通过。
- 源码和测试装置运行前后取摘要；发生变化会使本轮失败。
- `full_sop_accepted`、`functional_release`、`real_provider_accepted`、`manual_acceptance`、`optimization_goal_met` 均明确为 false；映射说明仅验证本地机制的选定检查。真实模型和人工验收继续开放。
- `local_sop_passed` 只表示当前映射下的本地机制检查，不证明同一次真实提供方连续运行 S01–S40，也不证明节省 A token。尤其 SEC11 引用的缓存/上下文/用量检查不等于实现了全部差异包与上下文清单规则；报告已有范围限定，最终交付应保留这一说明。

本报告的两个竞争问题需在原实施代理修复后独立复核；报告不宣称全回归或真实提供方终验通过。

## 修复后的独立复核

2026-10-15 再审：原两项定向探针对当前实现重新执行，未重复运行原代理整批测试。

- 原 shutdown 竞争已闭合：每 attempt 共用清理 Task，waiter 使用 shield，shutdown 等待其拥有的清理。独立结果为 `cleanup_done=true, cleanup_aborted=false, diagnostics=[], runner_done=true`。
- 原 mkdir 启动竞争已闭合：启动代次在 mkdir、handshake、health 后检查。独立结果为 `afterStop=offline, afterPendingStart=offline, spawnCount=0, cancelled=true, managedProcessAlive=false`。
- 附加 startup 审查发现的“坏 checkpoint 首次阻断后，第二次启动再次抛 CHECKPOINT_INVALID”已有 root 补丁：Recovery 在进入远端查询和发布前识别坏 checkpoint，保留原 bytes，按 attempt、终态和 owner 保守阻断或 defer。测试的重复启动断言已移回正确的参数化分支。本次只读检查未发现该补丁新增的越权发布通道。
- startup 的 provider_mode 防护、目标 bundle 的 task/attempt/VERIFIED 状态预检和提交后实际 task 状态确认均保留；fixture 不能经 real 模式启动恢复发布。

### 后续 P1：停止仍在进行时，旧启动异常处理会重新开放 start

原 mkdir 问题虽然修复，相邻 handshake 竞争仍可发生：`launch.catch` 在 stop 尚未完成第二次 journal 写入时无条件把 status 改为 offline；新的 start 仅依 status 是否为 stopping 拒绝调用。因此新的进程可能在原 stop 清理完旧树之后启动。

独立真实子进程探针：第一 start 创建一个尚未发 handshake 的本地 child；stop 终止它并暂停第二次 journal 写入；等待旧 start 拒绝后再调用新 start；恢复 journal。实际结果：`stateDuringStop=offline, spawns=2, secondStartError=null, afterStopAndSecondStart=ready, managedProcessAlive=true`。finally 已清理 child。此问题已交 root 和原实施代理；需要独立 stop-inflight 边界，或保证旧启动异常处理不能覆盖正在 stop 的状态。

### 第三项竞争的最终独立复核：已闭合

对 `apps/desktop/src/main/backend.ts` SHA256 `E47C0F6386DE4F9A88D5164202F56E4CFB5B1AC1DEB3388FC0E6B6F6BD3A4C6A` 复用上述真实 child、handshake 等待、第二次 journal 慢写探针；在 journal 暂停期间同时调用第二个 stop 与新 start。独立结果：

```json
{"stateDuringStop":"stopping","spawns":1,"journalWrites":2,"secondStartRejected":true,"afterStop":"offline","managedProcessAlive":false}
```

私有 `stopTask` 现在覆盖完整关闭生命周期；并发 stop 复用它，新的 start 在关闭完成前拒绝；旧启动异常处理不再把进行中的 stop 状态覆盖为 offline。没有创建第二个进程，journal 仅完成同一次关闭所需的两次写入。探针 finally 再次调用 stop 确认清理，未重跑整批测试。

截至本次限定范围复核，三项已报告的取消/桌面关闭竞争全部闭合，startup 边界审查的损坏 checkpoint 重启问题也已修复。没有遗留已复现阻断项。此结论不替代 root 对最新冻结源码的最终完整回归，也不授予真实模型或人工终验通过。
