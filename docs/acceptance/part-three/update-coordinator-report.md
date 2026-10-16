# D053 本地主进程更新协调器

日期：2026-10-14。本地更新协调器及故障恢复机制已实现；真实发布者、供应商签名 manifest、签名安装包、实际安装/迁移适配器与干净账户演练仍须外部证据。本次没有实际安装、分发、供应商调用或消息发送。

`apps/desktop/src/main/update-coordinator.ts` 在主进程提供私有 `UpdateCoordinator`。`main/index.ts` 显式导出它，使主进程构建保留实现。没有增加 renderer IPC，也没有改变依赖或打包配置。调用方必须注入主进程拥有的可信端口，renderer 与网络 manifest 无权提供签名、备份、检查点或健康检查权威。

## 实现边界

1. 从可信当前状态端口读取已提交版本、频道、schema、manifest sequence 和已保存包 SHA-256。网络候选只允许来自专用下载目录；路径链接和文件硬链接拒绝。
2. 在独立事务目录复制候选、匹配的可信前一版本和备份，逐份重新计算真实文件 SHA-256，并对副本执行文件 `fsync`。保存候选哈希、完整前一版本快照和备份相对路径/哈希/schema 绑定。
3. 候选必须经可信原生签名端口检查签名状态、链、时间戳、发布者 pin 和非测试证书。独立的可信 manifest 认证端口必须把精确 canonical manifest SHA-256 与包 SHA-256 绑定；仅有 Authenticode Valid 不能给旧包换版本标签。
4. 复用 `evaluateUpdate` 检查版本/sequence 递增、频道、兼容窗口和回滚 schema。先拒绝不可信候选；随后要求停止新增/活动工作、保存检查点，并核验一致备份，才进入安装。
5. 固定阶段日志在效果发生前写入临时文件、同步内容并原子 rename。日志最大 64 KiB/64 个事件，最多保存 32 个事务目录，每个恢复最多三次尝试。单个包上限 512 MiB，备份上限 256 MiB。桌面单实例锁负责进程唯一所有者，协调器另外排除同进程的并发事务。
6. 可信安装、迁移、首次健康检查端口返回的版本、包哈希和 schema 必须匹配候选。只有健康通过后才原子提交当前版本/schema/sequence；拒绝不会修改这些权威字段。
7. 安装/迁移/健康或提交失败，先重新核验已保存前一版本签名与 SHA、旧 schema 的备份 SHA/完整性，再恢复程序和对应数据。回滚只使用事务保存的可信本地前一版本，不接受网络降级授权标志。
8. 持久化 `resumePending` 与真实终态独立记录。已经 `COMMITTED`、`ROLLED_BACK` 或 `REJECTED` 后，调度恢复失败不会改写事务结论；下一次仅重试 resume，不重新安装或再次恢复历史数据。未恢复调度前禁止新的更新，超出三次尝试保持阻塞并保留事故证据。

## 实际执行

| 命令 | 实际结果 | 证据 |
| --- | --- | --- |
| `npx vitest run tests/release/update-coordinator.test.ts` | 40 passed，2.83 秒；无失败或 skipped | `docs/acceptance/part-three/update-coordinator-tests.log` |
| `npm run typecheck:desktop` | exit 0 | `docs/acceptance/part-three/update-coordinator-typecheck.log` |

首次缺实现测试失败已观察；终态 resume 缺陷又由独立审查明确复现，新增四个负例在修复前失败，修复后完整矩阵通过。独立审查者另外用显式断言复验：提交后 resume 失败保留 `COMMITTED` 和目标 schema；回滚后 resume 失败保留 `ROLLED_BACK` 和旧 schema；新协调器仅调用 resume 并恢复相应终态。复验记录为 `docs/acceptance/part-three/independent-update-review.md`。

40 个用例读取实际暂存包、日志、程序文件、数据文件和当前状态文件，包括正常提交，坏签名、未知发布者、篡改包、未认证标签、认证过的重放/降级/错误频道/不兼容 schema，检查点及备份失败，安装/迁移/健康失败，八个顶层阶段中断，可信安装端口内解包后/文件替换后两个实际文件断点，回滚过程中断，前一版本或备份篡改，坏日志，并发事务排除，提交指针已写入后失败，以及三种终态 resume 失败、resume 中断和重试耗尽。

## 证据与待外部验证范围

`artifacts/qa/D053/coordinator-report.json` 绑定本协调器、测试及日志 SHA-256。最终主进程/资源包已重建并确认协调器符号保留；包内/工作区服务源码树相同，证据见D052 packaged-runtime-report.json。根任务final-v3全量回归通过，真实部署适配与签名安装联动仍开放。

测试中的 manifest 使用临时 Ed25519 测试密钥执行真实签名/验签；这不是供应商公钥或发布资格。原生 Authenticode 观察来自明确的测试端口，程序替换和数据迁移端口操作隔离目录中的实际字节/JSON schema 数据夹具，未执行 EXE 或生产安装器。存储端口契约可适配 D051 的创建、校验、ZIP 导出与匹配旧 schema 恢复，但这些测试不冒充生产 SQLite 安装联动；D051 的真实 SQLite、WAL、双语成果恢复有独立证据。

实际更新前必须使用经发布审核的主进程实现注入这些端口：独立原生签名/供应商 manifest 认证，D051 一致性备份与准确旧 schema 恢复，受控安装/迁移、独立首次启动健康检查、原子当前状态提交和可确认的任务静默/恢复。适配器 Promise 必须在其拥有的原生工作退出后才能返回，不能在原生安装仍运行时开始回滚。当前协调器有意没有默认假安装器或自动触发更新入口。

真实安装器中断、签名链/时间戳、可信供应商 manifest、干净账户恢复和电源故障持久性演练仍未执行；文件 fsync 与原子日志 rename 的本地测试只证明进程中断恢复机制。以上外部限制不改变“本地协调器已经实现”的结论，也不将 D053 全卡或功能发布资格标记完成。
