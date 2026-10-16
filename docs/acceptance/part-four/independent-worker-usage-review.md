# 失败任务晚到SSE身份与用量：独立复核

日期：2026-10-15。审查者未实现此worker修复，未修改源码或测试。复用`scoped-usage-race-probe.py`，以本地内存队列改变事件到达顺序，再独立构造五种缺失/歧义身份；不重复实现者220项关联集、不请求真实模型、不访问账号。

结论：限定修复范围内未发现剩余阻断缺陷。stdout错误先于stderr身份时，原始已验证响应引用和33-token fixture收据现在能够保留；缺失或歧义身份仍保持未知，不以零替代。失败路径不产生`capture`，不把部分日志当成完整成功。

## 原缺陷与实现边界

原始探针`scoped-usage-race-probe.log`保留：身份先到时有一份33-token用量，身份在错误后的drain才到时，先发出的`started(None)`把请求引用锁死，导致已收到的完整用量丢失。

现在`Worker.run`失败分支先中断/清理，再执行`failed_usage`；只有完成drain之后仍无法核实真实请求引用时才发None fallback。`failed_usage`先关闭本地peer，要求读取线程均已结束，拒绝队列error、无效SSE和坏/重复收据，再调用`maybe_started`及原`bound_usage`。没有新增等待时限或重复启动请求。

`bound_usage`仍要求唯一created/completed响应、实际模型恰好等于预期模型、原始收据恰好一份，且请求/thread/turn引用全部一致。父`ScopedCodexRuntime`仍拒绝重复started、引用不一致、实际模型/来源不符及重复bill；仅在失败中交付`PhaseUsage`，不会将计量包升格为`PhaseCapture`。`interrupt_ack`在started前到达只更新诊断，不放宽上述绑定。

输出超限及读取线程仍活时采用保守未知处理：此时不能证明drain完整或没有后续重复收据。相关实现者负例保留；独立审查确认了对应failclosed分支。

## 独立实际检查

原始结果及执行前后源码SHA位于`independent-worker-usage-observations.json`。7例均实际执行当前worker模块，退出均为失败1，且每例只发一份started、没有capture或PRIVATE_CANARY：

| 调度/变形 | 已知用量结果 |
| --- | --- |
| 身份先于错误 | 33 tokens；引用为resp_fixture/turn_fixture |
| 身份在错误后清理drain才到 | 33 tokens；同一稳定真实引用 |
| 缺失全部SSE身份 | 未知，null |
| completed响应缺model | 未知，null |
| model/model_id字段冲突 | 未知，null |
| created与completed响应ID不同 | 未知，null |
| 缺少created记录 | 未知，null |

未把“没有usage包”解释为已知0。正例中的33来自明确合成收据，不代表真实供应商账单已核验。

worker实际SHA为`92fd9440c70307c9c5b7e2c9be30489ea2c4454c760b086f06478d4f1b7210ab`，与`native_scope.WORKER_SOURCE_SHA256`一致。worker、父runtime与native_scope执行前后SHA完全一致。该pin只绑定当前文件字节，不授予历史真实接入/沙箱/模型资格；生产资格及真实逐请求账单验收仍开放。

本复核证明本地失败调度和信任边界，不能替代全量回归、真实模型生命周期、真实账单或完整故障矩阵。
