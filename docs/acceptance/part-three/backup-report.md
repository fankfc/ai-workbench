# D051 本地工程与验证报告

日期：2026-10-14。结论：备份/恢复引擎、认证 API、桌面 IPC 和存储设置入口已实现；本地存储回归通过。完整 D051 发布资格仍需非作者隔离演练和匹配旧 schema 的签名程序回滚证据。未变更 D001–D040 冻结记录或任务卡状态，没有真实模型调用、安装、分发或发送消息。

实现包含 `storage/backup.py`、`storage/restore.py`、`api/backups.py`，以及 `application.py` 的备份状态/路由接入。桌面 `main/backup-ipc.ts`、`preload/backup.ts` 通过现有 `main/ipc.ts`、`preload/index.ts`、`shared/validation.ts`、`shared/desktop-bridge.ts` 和 `renderer/settings/Storage.tsx` 提供用户入口。

用户只会从系统对话框选择保存/导入文件；renderer 的白名单调用没有路径参数。导入 ZIP 经过受限路径、重复名字、大小、链接、SQLite schema 对象、外键、哈希、成果引用和双语配对校验。备份使用 SQLite 在线 backup 与数据库写入栅栏，冻结对应文件引用；副本验证后原子提交。派生翻译缓存仅从副本删除并清理空闲页，系统凭证和根目录临时缓存不进入备份。恢复先写独立同级目录、迁移、重建索引、再验证；只有主进程完成托管服务重启才更新存储目录选择，原目录保留。

## 实际执行

| 命令 | 结果 | 证据 |
| --- | --- | --- |
| `& services/orchestrator/.venv/Scripts/python.exe -m pytest tests/storage tests/integration/test_storage.py tests/integration/test_storage_settings.py tests/integration/test_storage_relocation.py tests/integration/test_phase_two_migration.py -q` | 102 passed，121.57 秒 | `docs/acceptance/part-three/backup-pytest.log` |
| `npx vitest run tests/desktop` | 7 文件、31 tests passed | `docs/acceptance/part-three/backup-desktop-tests.log` |
| `npm run typecheck:desktop` | exit 0 | `docs/acceptance/part-three/backup-typecheck.log` |
| `& services/orchestrator/.venv/Scripts/python.exe -m pytest tests/storage/test_backup_restore.py tests/storage/test_schema_migration.py -q`（最终哈希报告修正后） | 33 passed；恢复报告返回迁移后的实际数据库哈希，单独保留原备份哈希 | `docs/acceptance/part-three/backup-final-storage.log` |
| 同一专项命令（独立审查的任务输入完整性修正后） | 48 passed，31.14 秒；覆盖重算外层/原件 manifest 仍缺失或换掉数据库声明原件的 15 个负例 | `docs/acceptance/part-three/backup-source-closure.log` |
| `npx playwright test tests/e2e/backup-restore.spec.ts --list` | 发现 2 个真实 Electron 入口测试；最终全量运行中两项均通过 | `tests/e2e/backup-restore.spec.ts`；`docs/acceptance/part-three/final-v3/desktop-e2e-report.json` |

Python 的 6 条 warnings 来自已安装 FastAPI/Starlette 测试客户端和 PyMuPDF SWIG 依赖弃用提示；没有测试失败或 skipped。首轮缺实现的 14 个测试失败已确认，随后通过；额外缓存排除测试也先观察失败，再实现并通过。

`artifacts/qa/D051/restore-report.json` 汇集六个新鲜真实产品场景的原/恢复哈希、schema、体积、用时、引用文件数、暂停任务、多版本原件和源码 SHA-256。一个正例和五个故障场景均读取实际产物；模型消息是明确的假外部响应，成果渲染、作者来源、存储和配对检查是实际产品流程。

持久证据正例用时 16.767 秒，备份数据 624,956 字节，核验 37 个文件，包含两代原件和一个暂停任务。最终总验收 Python 1489 项、桌面单元 84 项、实际 Electron 35 项均通过，含本卡两项 Electron 测试，验证前后产品和装置源码一致；统一证据为 `docs/acceptance/part-three/final-v3/verification.json`。引擎恢复结果的 `hashes` 是迁移后实际文件 SHA-256，`original_hashes` 单独保留导入包哈希；schema 升级前后的数据库字节本来就不同。

独立审查发现，单纯扫描仍存在的 `.source-manifest.json` 无法发现“同时删掉它和原件、再重算外层 manifest”的缺口。已补上数据库到任务工作区的完整引用校验：持久化任务合同、规划哈希、材料/语言上下文、已完成输入准备的 profile、关联步骤/检查/未发布成果及翻译源引用都会要求原件与 manifest 存在，并与数据库已固定的哈希一致。原件目录不以 ZIP 文件清单为唯一依据。新增负例先观察失败，再修复并通过；裸 profile 引用没有独立原件哈希时只能证明材料存在，原字节的独立核对来自已有材料/合同/规划等持久化哈希。

## D051 十项证据

| 项目 | 本地证据与范围 | 状态 |
| --- | --- | --- |
| 1 引擎/API/IPC、schema/版本、排除凭证缓存 | API opaque ID、ZIP 字节导入；真实桌面白名单/设置入口；凭证 canary/缓存排除测试 | 本地通过 |
| 2 SQLite/WAL、冻结引用、校验/原子提交 | 持续打开 WAL 连接的已提交写入被恢复；单独 writer fence + online backup；全部引用哈希 | 本地通过 |
| 3 vN−1 样本、中文路径、双语多格式、暂停/多版本 | 产品双语 Markdown/PDF、两代原件与历史包、暂停任务中文输入装入真实 v3 schema；生产引擎仍完整验证 | 本地通过；不是旧版可执行程序运行证据 |
| 4 逐文件校验、暂停写入、独立目录、保留原数据/显示结果 | core restore writer fence/独立 sibling；4 IPC 测试；Electron 测试含实际 PID 重启与历史恢复 | 引擎/IPC/Electron 自动验证通过；完整正式候选验收开放 |
| 5 缺译文/数据库/哈希/空间拒绝 | six-case scenario + 复制故障、重签文件 manifest 的错误双语配对 | 本地通过 |
| 6 每个 schema 提交点故障 | v3→v4 全部 8 条 SQL 前/后边界、schema history INSERT、最终 COMMIT 故障；完整逻辑 dump 不变 | 本地通过 |
| 7 匹配旧 schema 回滚/禁止未来 schema | 原 v3 root 与备份保留；v3 migrate 调用拒绝 v4 并不写入 | 本地通过；实际签名旧程序回滚待验证 |
| 8 索引重建/重新连接 | 独立 root 事务 migrate + REINDEX；没有凭证文件；恢复后的无 runtime API 连接均 unavailable；中文重新核验提示 | 本地通过 |
| 9 用时/体积/校验/回退 | 六场景 `restore-report.json` 与日志、runbook | 本地通过 |
| 10 运维手册和非作者隔离复验 | `release/backup-restore-runbook.md` 可执行步骤；主代理从独立空目录运行正向场景 | 工程复验通过；第三方人工手册执行仍开放 |

## 限制与阻塞

备份格式 1 当前限制为 256 MiB 和 20,000 个数据文件；大库的流式导出/导入尚未实现。校验拒绝活跃工作租约和运行中远程任务，恢复还拒绝待调度任务；产品当前没有一键安全暂停所有任务的入口，因此用户须先结束或按已有流程暂停运行任务。已验证备份暂存副本会保留在同级专用目录，尚未配置自动轮替。

系统凭证存储从不进入备份；用户正文或附件中主动存入的秘密属于原件内容，备份保持原字节。只验证已知 schema 1–4；未来 schema、篡改历史与额外触发器会拒绝。当前 DOCX/Word 页面渲染不在 D051 场景范围，实际双语多格式证据为 Markdown 与 PDF。

主代理独立正向复验退出 0，证据在 `artifacts/qa/D051/non-author-9318bed4/non-author-result.json`：实际核验 37 个文件，备份 624,956 字节，schema 3→4，原目录保留，凭证未恢复，两代 Markdown/PDF 双语原件和一个暂停任务保留；本次用时 5.633 秒。外部模型响应仍为 fake，该记录只证明恢复工程行为。

剩余外部/人工证据是第三方独立手册执行、签名旧版安装/实际 schema 匹配回滚。它们不会由假响应测试或已写代码自动替代。D051 的完整完成门槛保留开放。

归档修复后以冻结验证装置再次独立正向恢复：`artifacts/qa/D051/non-author-final.json` 记录37文件、schema3→4、原目录保留、凭证未恢复，CLI退出后run-manifest复核通过；完整第三方人工手册执行仍开放。
