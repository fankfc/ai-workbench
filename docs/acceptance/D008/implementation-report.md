# D008 数据库迁移与不可变原件存储

已实现 SQLite 十张业务表、顺序迁移和内容寻址原件存储。成果登记只在文件完成写入、fsync 与实际哈希校验之后提交；文件故障不产生可见成果，数据库回滚允许留下安全的完整孤立 blob。

环境为 Windows 11（10.0.26200）、Python 3.13.0、SQLite 3.45.3，解释器为 services/orchestrator/.venv/Scripts/python.exe。仓库当前无 HEAD 提交，报告的 commit 为 null；实际源码哈希保存在 source-hashes.json。没有外部模型调用。测试使用真实 SQLite/文件系统/子进程；ENOSPC、EIO 和 KeyboardInterrupt 是在文件操作边界注入的故障。

## 实现与验收

| 卡项 | 实现与证据 |
| --- | --- |
| 01 十张业务表 | conversations、turns、task_runs、steps、provider_profiles、artifact_revisions、translation_units、checks、usage_entries、outbox_events；另有 schema_version 元数据表。字段及消费约定见 .superpowers/sdd/storage-interface.md。 |
| 02 唯一与外键 | conversation/client_request、task/attempt、provider/external_request、事件 task/attempt/sequence、conversation_sequence、deduplication_key 均有唯一约束；任务、轮次、成果、来源、步骤引用有外键。已测重复与不匹配拒绝。 |
| 03 顺序迁移 | 对全部待迁移版本使用一次 BEGIN IMMEDIATE，不使用 executescript；版本、SQL 哈希、连续历史、FK 均校验。失败整体回滚，未知新版本和未登记非空库拒绝。 |
| 04 原件存储 | SHA256 路径；临时文件写入、flush/fsync，再 atomic hard-link create-if-absent，随后登记事务。 |
| 05 实际字节校验 | 同一哈希重复写只复用已核验原件，已有坏字节不覆写；read/verify 和成果读取重新计算实际哈希。 |
| 06 来源信息 | ArtifactVersion 的角色、原件与规范内容哈希、版本、来源版本、依赖、A 回复引用、作者/评审/渲染者，加 provenance_json 与 source_request_json。来源和依赖在登记时验证引用及 blob。 |
| 07 写入规则 | sqlite3.Row、外键 ON、WAL、synchronous FULL、busy_timeout；明确单写者事务及每操作独立连接，拒绝嵌套事务。 |
| 08 故障 | 磁盘故障、部分写入、fsync 中断、link 失败、真实写锁超时、重复登记回滚、缺 blob、坏 hash、并发 put、真实 os._exit(78) 提交前崩溃。见 storage-faults.json。 |
| 09 旧库升级 | 实际 schema 1 旧库十张业务表各一条记录，关闭后重开应用 additive schema 2 测试迁移；原列数据哈希/数量相同，integrity_check=ok，foreign_key_check=[]，原件哈希相同。见 migration-report.json 及 fixtures 中的旧库副本/升级库/blob。生产迁移链仍为版本 1，版本 2 仅在隔离演练中提供。 |
| 10 备份边界 | docs/runbooks/storage-backup-boundary.md 规定一致 SQLite 快照 + 匹配 blob + SQL/hash 清单；完整产品恢复留给后续发布任务。本卡不提交。 |

## 红绿与可重放命令

所有测试先有可导入的接口装置，失败没有依赖 missing-import。新增生产行为分别在以下三个阶段取得失败证据；其余约束检查用于验证完整配置和已实现边界。

| 阶段 | 日志 | 结果/退出码 |
| --- | --- | --- |
| 可导入 stub 的基础反例 | red-foundation.log | 19 failed，exit 1 |
| 基础实现 | green-foundation.log | 19 passed，exit 0 |
| 原件登记/读取边界反例 | red-artifact-boundary.log | 14 failed、19 passed，exit 1 |
| 原件登记/读取实现 | green-artifact-boundary.log | 33 passed，exit 0 |
| 完整 SQL 约束与旧库演练 | green-schema-contracts.log | 52 passed，exit 0 |
| 外部请求键覆写反例及额外崩溃/并发检查 | red-final-edges.log | 1 failed、55 passed，exit 1 |
| 首次赋值后外部请求键不可变 | green-final-edges.log | 56 passed，exit 0 |
| 最终卡验收 | green.log、storage-tests.xml | 56 passed，exit 0 |
| 证据重建 | evidence.log | schema 1→2、十表原列保持、哈希校验通过，exit 0 |
| 既有包/探测/D007 合同加 D008 定向回归 | regression-stable.log | 273 passed，exit 0 |

```powershell
services/orchestrator/.venv/Scripts/python.exe -m pytest tests/integration/test_storage.py -q --junitxml=docs/acceptance/D008/storage-tests.xml
services/orchestrator/.venv/Scripts/python.exe docs/acceptance/D008/reproduce_evidence.py
```

报告生成器在独立的新 fixtures 子目录构建旧库并保存快照，再执行升级，不删除旧证据。报告里保存运行时间、配置、工具版本、确切命令、结果和源码哈希。

regression.log 保留一次开发中的目录级回归被终止的记录（exit -1，含其它 lane 当时未完成的测试）。随后改为明确既有测试文件的定向回归，273 项通过；该中间记录不作为卡完成证据。

硬件断电、物理填满磁盘、完整产品备份/恢复尚未执行。进程退出可验证 SQLite 回滚和不产生半成果，但不代替 NTFS 目录元数据的断电持久性测试。上层发布、翻译语义质量和批准权限归后续卡；SQL 白名单仅限制公开 kind，完整 PublicEvent 校验/发布授权由 D007/D018 执行。
