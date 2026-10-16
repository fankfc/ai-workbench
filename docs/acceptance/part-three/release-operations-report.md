# D052–D060 本地发布与运维工程报告

记录日期：2026-10-15。工作目录：`C:/Users/asd15/Documents/ChatGPT/ai`。本报告交付本地工程、可执行验证器和实际运行证据；没有执行安装、分发、真实模型调用、账号操作、采购、外部消息或自动排期。没有创建提交；本lane未修改计划卡片，逐卡本地进展由根任务最终统一汇入任务板。

当前正式发布决定为 **NO-GO**：`functional_release=false`、`optimization_goal_met=false`、`overall_goal_complete=false`。`files_complete=true` 只表示交接文件存在，不表示用户验收或整体目标完成。真实模型调用数为 0，没有任何可声明的质量或 token 节省范围。

## 最终本地候选与来源

| 项目 | 本次实际记录 |
| --- | --- |
| 候选 | `dist/windows/AIBroker-Setup.exe`，内部未签名 NSIS 包 |
| 大小 | 171,309,226 bytes |
| SHA-256 | `5618db4686a6b889a95f45b92820c31337c07f995f30b3e208ebb3f689b795ac` |
| 最终打包 | PowerShell 7 执行 `release/build-windows.ps1 -InternalUnsigned`，session 37902，退出码 0 |
| source_build_id | `cb98eed03df6bd4ffaa551d66a54c77198911cf5b3e763a1ef3c055f5ee54ca4` |
| verification_source_id（打包时记录） | `51df6765348340de2c7853cfb71ee4b2df7aa952d7b2fa3cafdf64de67a417a2` |
| 包内与工作区服务源码 tree SHA-256 | 均为 `38f83dbb7e793c4587fa78164f88e9458989d28c5fe26d7badecf076c72b5437` |
| bundled Python executable SHA-256 | `62ebc90a2884bb63a0cd67e789cafdd51e771eee043587e2354327b4ccc9bb05` |
| 原生 Authenticode | `NotSigned`，发布者为空，验证命令按预期退出 2 |
| Git 发布身份 | 尚无可核验提交；未创建提交，不能把内容指纹冒充正式发布 commit |

最终包内保留了 `UpdateCoordinator` 主进程导出。修复了原有开发路径不能用于安装目录的问题：打包启动使用 `process.resourcesPath/python/python.exe`，服务 cwd 为 `resources/services/orchestrator`；开发路径继续使用既有环境。没有运行 NSIS 安装器。

运行时通过 `stage-runtime.py` 从本地精确 Python 3.13.0 与 uv.lock 的 23 个生产包生成，记录 2,316 个文件哈希、许可证元数据及 notices，独立 interpreter import smoke 退出 0。它没有把开发 venv 当作可重定位运行时。该清单标记为 `internal_hash_inventory`，不能当作已经完成独立许可审核的生产包 SBOM。OCR 未打包；Word-compatible COM 和 CJK 字体是当前格式能力的外部系统先决条件，不能假设干净用户机器已经具备。

## 已执行的命令与证据

所有命令使用本项目 `services/orchestrator/.venv/Scripts/python.exe`，不使用未锁定的临时依赖。下表中的失败退出是有明确业务含义的阻塞结果，没有计为通过。

| 实际命令 | 结果 | 留存证据 |
| --- | --- | --- |
| `python -m pytest tests/release tests/operations tests/acceptance/test_real_journey_evidence.py -q` | 冻结前集中验证 50 passed，1 条既有 Starlette/httpx 弃用警告；无失败或 skip | `docs/acceptance/part-three/release-operations-pytest.log` |
| `node node_modules/vitest/vitest.mjs run tests/release` | 53 passed，3 个文件；含协调器 40、前置器 12、打包路径 1 | `docs/acceptance/part-three/release-operations-vitest.log` |
| `npm run typecheck:desktop` | 退出 0；最终打包前再次检查 | `artifacts/qa/D052/build-windows-final.log`；独立协调器日志 `update-coordinator-typecheck.log` |
| `python release/stage-runtime.py` | 23 个生产包、2,316 个文件，native import smoke 退出 0 | `release/staging/tool-inventory.json`、`release/staging/runtime-smoke.txt` |
| `python release/check-prerequisites.py` | 当前 Windows 11/Python 3.13.0 上实际 PDF 与 DOCX native render 成功；SimSun 哈希留存 | `artifacts/qa/prerequisites/format-prerequisites.json` 及对应 render 目录 |
| `& './release/build-windows.ps1' -InternalUnsigned` | 最终构建退出 0；未安装、未分发 | `artifacts/qa/D052/build-windows-final.log` |
| `python release/probe-packaged-runtime.py` | 本轮恢复后新执行，退出 0；实际包内 Python 启动服务、health、checkpoint、退出清理均成功 | `artifacts/qa/D052/packaged-runtime-smoke.log`、`packaged-runtime-report.json` |
| `& './release/verify-installer.ps1' -Installer dist/windows/AIBroker-Setup.exe` | 本轮新执行，`NotSigned`，预期退出 2 | `artifacts/qa/D052/authenticode.json` |
| `python release/create-manifest.py --ledger-output release/candidate-evidence.json` | 本轮新执行，预期退出 2；最终候选哈希匹配，但缺签名/外部报告/完整 SBOM/发布 commit | `artifacts/qa/D054/create-manifest.log`、`release-manifest.json`、`release-manifest-audit.json`、`sbom.json` |
| `python release/write-audit.py` | 本轮新执行，退出 0；如实生成未完成决定 | `release/release-decision.json`、`release/final-acceptance.json`、`release/offline-evidence-index.json` |
| `python release/verify-offline-index.py` | 生成报告后的最终结果以同目录 `release-operations-offline-index.log` 为准 | 只验证链接和字节哈希；`release_qualified=false` |

包内 smoke 直接查询了 `/v1/settings`：`available_connections=0`；Claude、GPT、GLM 均为 `identity_status=unknown`、`available=false`、`enabled=false`。这不是用常量代替连接查询。服务 PID、协议、随机 instance、包内/workspace 源码树相等、检查点成功和进程终止均有实际观察。它不证明干净机器安装、单 taskbar、卸载或真实模型能力。

Windows PowerShell 的现有执行策略曾拒绝 `.ps1`；后续使用本机已经允许本地脚本的 PowerShell 7 执行，没有修改策略或使用 Bypass。首次 npm 获取遇到官方 registry TLS reset，正常有限重试后完成；`electron-builder=26.15.3` 已精确写入 workspace 依赖和 package-lock，未关闭 TLS 校验。构建日志中的 “signing with signtool.exe” 不当作成功签名证据，最终字节重新核验为 NotSigned。

## 各卡工程结果及未完成动作

| 卡片 | 已落实的本地动作 | 仍未完成及其边界 |
| --- | --- | --- |
| D052 | 固定产品 ID/包名；锁打包器；staged runtime/tool inventory；原生签名验证脚本；包内真实 backend/settings/source-tree/退出 smoke；保留用户数据的 NSIS 配置；缺签名阻止正式发布 | 动作 3 的生产证书/服务；5 的干净非管理员 Windows 安装；8 的真实升级/卸载保留；9 的安装录像/进程/文件收据；10 的可信签名候选冻结。当前不是已验收安装包 |
| D053 | manifest schema；认证 manifest 与最终包哈希绑定；原生签名私有端口；真实文件暂存/fsync；可信前任/兼容备份；任务静默检查点；有界持久 journal；安装/迁移/健康后才提交；失败/中断回滚；完成后 resume 失败仅重试 resume | 生产 native signing/installer/backend/D051 ZIP 端口的部署接入及真实签名 N−1 包尚未取得；没有实际执行安装。40 个明确 test-only 原生端口的文件系统测试不能代替动作 9/10 的签名干净机器演练与兼容窗口公告 |
| D054 | Node/npm/Python/uv/packager 与依赖锁；CI 顺序和 prereq/contracts 硬门槛；桌面两种 build 后才 E2E；外部报告缺失即失败；CycloneDX 锁清单；候选/依赖/报告 SHA 绑定；跳过/篡改/旧构建/fixture 负例；PR 不接签名凭证 | CI 尚未远端执行；动作 4 的两次独立干净构建可重复性比较未执行；完整生产 runtime/tool/license SBOM 与独立许可复核未完成；没有正式 commit 或不可修改的正式发布归档。当前多次本地构建不冒充双干净构建 |
| D055 | 四域/入口的真实证据 inventory 与可运行审计器；检查 provenance、A 原件/B 译文、原始 provider receipt、所有尝试用量、来源与文件哈希；缺证据返回空范围/未验证 | 真实素材固定、Claude+ZCode 连接、四域成果、纠正、取消/恢复、译文失败止发、GPT 原语言演练、客户截图、人工审查与签署均未执行。没有捏造论文、数据、模型或客户成果 |
| D056 | 试用指南、反馈 schema、P0–P3 分级与空 triage；复用真实 allowlisted diagnostics；实际 ZIP/canary 测试；默认无正文/附件/凭证，CLI 布尔值不能伪装本次用户 consent | 5 工作日提议观察窗口、真实用户反馈、缺陷回归/复验和试用结束评审未发生。空台账不代表零缺陷。当前没有正文附加 consent UI，正文附加保持拒绝；没有上传或通知 |
| D057 | 可运行 go/no-go；候选/源提交/签名原生再观察；十类强制报告逐类语义检查；R03–R15 功能与 R01/R02 优化状态独立；三角色独立批准；优化调用真实 D046 evaluator、精确 scope；当前输出 NO-GO | 三方签署、最终候选完整外部报告、实际缺陷关闭、正式发布 commit 和生产归档未取得。缺项没有改为 N/A。临时 sealed fixture 只验证功能 true/优化 false 的分离，实际候选审计拒绝该 fixture |
| D058 | 既有 settings JSON 持久运维配置；诊断 TTL 14/90/365 可配置并重启保留；实际年龄/哈希/引用快照预览与确认清理；活跃任务与 pins 保留；真正 translation_cache.valid 失效；不可变 glossary/job/history 保留；settings 公共偏好过滤、PATCH 保留私有配置 | 日常负责人、实际日/周检查、月度恢复长期记录、基线告警阈值、真实双语专业术语批准待落实。没有自动排期。只清理三类 diagnostic JSON，聊天/交付物/备份不进入年龄删除 |
| D059 | 持久 incident domain/task/qualification freeze；共用 release gate 和 BundlePublisher transaction 检查；旧 key 永久无效；仅完全匹配的服务自有 configuration/key 可按新资格放行，easy 不解锁 hard；事故 blob 真正阻止 collector 删除；实际取消/发布拒绝；新样本真实 evaluator 后才允许精确 scope | 实际桌面+模型变更/误译 canary、生产签名回滚、独立新资格、用户影响说明发送和人工复盘尚未进行。没有默换 provider、自动复启全域或仅靠 CANCELLED 状态制造通过；域 wildcard 仍保持冻结 |
| D060 | 本地候选、使用/更新/备份/事故/维护手册、单独功能/优化机器结论、具体开放项责任角色/下一证据、离线 SHA 索引及可运行验证 | 非开发人员干净机器终验、真实两语保存与用户签署未取得；整体目标不能关闭。`final-handover.md` 逐项列明责任、下一动作、证据和原计划工程量 |

## 守卫与回归的实际含义

发布证据只接受限定相对路径和字节哈希；拒绝逃逸、绝对/drive-relative/ADS/backslash、symlink/reparse、hardlink、重复 JSON key、非有限数值、旧候选/旧 commit 和显式 test fixture。外层 external 标签也不能洗白带 fixture 标签的 raw JSON。完整发布还须实际干净源提交和对最终候选重新调用 Windows 原生 Authenticode；CLI 的 `signed_candidate`、`functional_checks`、`optimization_complete` 等名字不产生成功事实。

强制报告不是只查 passed 字段：翻译要求 golden/独立 holdout 至少各 60、双盲双语评审、关键错误零及仲裁；GUI 必须有真实 IME/Narrator/多屏三项哈希引用；性能从哈希绑定 raw samples 重算五个 p95，要求 200 次输入、30 次冷启动、100 次生命周期和无孤儿；24h 单独要求完成 86,400 秒；真实旅程要求四域、实际 identity/receipt/usage 和配对文件。自动语义校验与哈希不能替代人的真实观察，独立签署仍是发布必需项。

OperationsController 使用既有 `desktop_settings` JSON 和数据库事务，不创建第二套任务状态机。`state_machine.register_release_gate`、`validate_release_gate` 和 bundle publish 调用同一事故守卫。回归实际证明：重启仍冻结；无关域可发布；受影响域拒绝；假/stale 重资格拒绝；一个 easy scope 不解锁 hard/其他 profile；事故 blob 不在既有 collector 可删除集合；缓存真实行失效、旧 READY job 保留、新 job 无 cache hit；日志变更使预览过期；TTL 配置持久化且不能把 conversations 加入清理。公开设置仅返回四个既有 preference，诊断导出也不包含私有 incident reason 或整个 operations 配置。

协调器的 40 项测试和实际边界详见 `update-coordinator-report.md`、`independent-update-review.md` 与 `artifacts/qa/D053/coordinator-report.json`。测试操作临时普通文件、JSON 数据迁移和 test signing fixtures，不执行 EXE，也不伪装 D051 的实际 SQLite/ZIP 生产端口集成。COMMITTED/ROLLED_BACK 后 resume 故障经独立复核，恢复只重试 resume，不重装或覆盖此后用户数据。

本地备份恢复已经有独立非实现者验证；`backup_restore_missing` 表示正式发布 ledger 尚未导入本候选/commit 的合格报告，不能解读为本地恢复代码没有实现。同样，`performance_missing` 等表示未取得完整发布资格，不能用已有短 smoke 自动补成 24h。

## 仍需完成的具体工作

1. **发布工程师**：在用户允许后接入既有合法生产签名身份和允许 thumbprint；完成 native 部署端口接入、可信 N−1 包、干净非管理员 Windows 安装/升级/卸载/回滚演练，提交最终字节、schema、过程和健康收据。没有证书时不采购或代办账号。
2. **构建/许可负责人**：创建经授权的正式源码提交与干净候选、两份独立干净构建比较、实际 runtime/tool/license SBOM 与许可复核；配置合法具备 COM/CJK/交互会话的 self-hosted CI runner。当前只有本地运行成功，不能宣称远端 CI 通过。
3. **产品/领域/双语/无障碍评审**：提供真实原始材料、真实模型权限与计费用量，执行四域和 GPT 已声明入口旅程、A 原件/B 译文、双语 holdout、实际 IME/Narrator/多屏及用户成果评审。
4. **性能/可靠性负责人**：完成最终构建的加载工作量和全部五项 SLO、固定硬件/电源基线及独立 24h 持续运行；短 runner 和本地服务响应不代替这些门槛。
5. **维护/事故负责人**：确认人工责任人与维护节奏、真实恢复/事故演练和独立新 scope 资格；不创建自动计划或发送未授权消息。
6. **产品/QA/发布与用户代表**：完成实际试用、已知缺陷复验、三方 go/no-go 和独立终验；功能与 A 质量+A token 优化分别签署。任何必要优化证据缺失时，整体目标继续未完成。

上述项目包含环境/权限和人工证据阻塞，也包含明确尚待完成的生产部署适配与集成工作；没有把它们统一包装成“只差外部证据”。最终 R01–R15 全量验证由根任务 `final-v2` 报告汇总，本报告的 50/53 项只覆盖本 lane，不替代全项目终验。

根任务随后修复SQLite验收归档工具，产品源码与候选字节不变；最新验证装置哈希为 `be235c533d31cb6f4d79585d028c8da25cedd8d109edd022d33aa00bebcebe95`。`final-v3`最终全量1489 Python、84桌面单元、35实际Electron通过，源码前后一致，20场景退出后清单复核通过。当前性能短样本发送/状态/启动超过建议阈值，仍需分析优化与完整验收；详见 `../part-three-progress.md`。
