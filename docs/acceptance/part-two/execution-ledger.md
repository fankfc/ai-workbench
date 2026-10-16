# 阶段二实施记录

日期：2026-10-14（Asia/Shanghai）。按已批准的 D021–D040 计划继续第一部分冻结成果。

第一部分保持冻结历史：17 done，D004/D005/D020 blocked；冻结回归 1143 passed / 1 failed。真实生产连接仍禁用，真实模型与双语人评资格不得用 fixture 替代。

仓库为未产生初始提交的 codex/part1-foundation，全部既有文件未跟踪。保留原 checkout 和冻结快照；不创建无基线 worktree、不提交用户既有成果。

文件所有权：
- desktop：apps/desktop、tests/desktop、tests/e2e、tests/support/electron-fixture.ts、package.json/package-lock.json/playwright.config.ts。
- translation：app/translation、app/runtime/answer_publication.py、0002_route_snapshots.sql、tests/translation、对应路由/翻译测试；不修改已有公共合同。
- documents：app/documents、app/api/artifacts.py、0003_delivery_bundles.sql、tests/artifacts、对应文档测试；文档依赖由该 lane 管理。
- root：API/settings/usage/storage/diagnostics、launcher/application/turns、0004_desktop_settings.sql、集成和最终证据/状态。

接口约定：Electron 主进程连接 authenticated loopback。GET /v1/health 返回 protocol_version=1.0、instance_id、pid、provider_mode；POST /v1/checkpoint 返回 saved=true。实例 ID 由主进程环境 WORKBENCH_INSTANCE_ID 提供。后端 launcher 接受 --port 动态端口（0）、--host 127.0.0.1、--provider-mode real|fake；stdout 仅 JSON 启动握手（kind=backend.ready, port,pid,instance_id,protocol_version）。令牌从 WORKBENCH_API_TOKEN 环境读取。

设置：GET /v1/settings -> {version,preferences,connections}; PATCH /v1/settings -> {expected_version,preferences}；POST /v1/settings/connections/{id}/probe。连接返回 id/role/family/model_id/identity_status/enabled/available/provider_mode/connection_version/capabilities，无密钥/命令/路径。默认 real 注册表为空。preferences 字段 theme=system|light|dark,font_size=14..22,send_shortcut=enter|ctrl-enter,close_behavior=quit|minimize。
会话沿用现有 API，PATCH /v1/conversations/{id} 管理 title/pinned/archived；GET 接受 query/archived。turn 兼容增加 connection_version。文件下载由发布后的 artifact_id + bundle_id + conversation_id 校验，无任意路径 API。
GET /v1/usage 返回 items,next_offset,summary（未知保持 null，无基准 savings=null）。GET /v1/storage，POST cleanup-preview、cleanup(version/token)，POST /v1/diagnostics/export。其余接口若未装配必须返回明确不可用状态，不能 fake success。

测试：先业务反例，再实现；红绿日志写入本目录各 lane；真实试验禁止自动调用。fake 服务可用明确演示专用外部响应，存储/调度/投影/翻译/GUI 使用产品代码。每项卡片只有满足全部门槛才 done。局部实现标 in_progress，上游及真实验收缺口明确 blocked。

## 集成更新（16:30，尚非最终验收）

- HTTP 增加不可变会话附件、置顶/归档/改名/字面搜索、版本化偏好、实际注册连接状态、脱敏诊断、分岗位用量、受引用与任务状态约束的垃圾清理。
- 目录迁移先预检空目标/路径边界/磁盘空间/未决任务，执行时暂停服务写入、SQLite backup、逐文件 SHA-256 校验。成功须主进程以新目录重启；失败继续原目录，原数据保留。4 个业务负例与成功场景通过。
- 用量提供输入/输出/缓存的原提供商口径；缓存为输入子集或额外输入明确区分，缺失保持 null。未提供对照基准，节省值保持 null。
- 追问规划保留完整同会话原始历史、批准回答与附件；翻译 lane 接手 planner/workflow/executor/backend/supervisor/conversation_context 实际 Claude 门槛装配。域 profile optional metadata 已在 turn 创建时冻结，缺项直接 NEEDS_INPUT，不启动 A。
- 文档 API 与公开附件投影已装配；发布必须验证 canonical 实际 A 完整响应、全文翻译 QA、同一 bundle 字节与审批。新版失败历史 v1 不得消失，已发现并修复该反例。
- 实际 Electron 首轮 14 项 E2E 通过；文件保存、PDF 预览与目录迁移仍在加测，暂不把 D021–D037 整批标 done。
- Python 中间全量：1233 passed / 3 failed / 1 real_provider deselected（intermediate-all-python.log）。两个文档集成失败由 documents lane 修复；一个旧安装路径依赖的哈希单元测试改为明确测试文件，不改冻结真实资格。最终全量待源码稳定后重跑。
- scripts/phase_two_preflight.py 未启动模型，生成真实四域冻结输入与 real-readiness.json。默认 real 服务注册数 0；D004/D005/D020 与 GPT 当前生命周期资格仍缺，D040 blocked。未创建假 real profile ID。

## 最终本地交接（2026-10-14）

- 最终全量 Python 1318 passed / 0 failed / 0 errors / 0 skipped，1 real_provider 默认排除，231.05 秒；最后展示修正后重跑，原先批次和失败日志保留。后端及完整源码前后 hash 一致，记录于 final-*-source-*.json。
- 桌面27单元/28实际Electron E2E全绿；root类型/单元/正式和测试构建，以及最后正常任务profile的4项实际GUI复测通过。演示输出保留用户原文和自然字段，不回显内部profile引用；分析代码以代码块显示。
- 两条fresh-context审查共10个原问题已修复、复核通过。根额外修附件选择器支持范围与API一致，保留有限执行/解析能力，不扩大生产资格。
- D021–D040实际状态同步：18 in_progress，D024/D040 blocked；第一部分冻结、D041–D060及原计划历史保留。仅本地已支持功能得到验证，不宣称全部任务完成。
- 本次真实模型调用0，生产配置/注册0；实际提供方全链路、双语/领域人评、完整故障/人工矩阵和D040完整真实断言仍未完成。报告为 docs/acceptance/part-two-progress.md，结构化结果为 part-two/verification.json / task-results.json。

## 未完成部分冻结（2026-10-14T21:48:14.951505+08:00）

按用户‘冻结未完成的部分’及‘重试’指令，固化 D021–D040 当前实现、依赖与遗留，暂停继续开发。18 in_progress、D024/D040 blocked 状态保留；第一部分冻结文件、首20卡与其 execution_summary、D041–D060 未改动。未新增模型调用或 Git 提交。恢复记录：docs/acceptance/part-two-freeze-20261014/freeze.json；源码及证据逐件 SHA-256 与 ZIP 由独立工具校验。
