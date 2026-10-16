# 阶段三本地实施与验收记录

本轮按用户澄清“暂无，先完成本地工程并列出阻塞项”交付 D041–D060 的本地实现、验证工具和内部测试构建。第一、二部分历史冻结保留。完整阶段三终验、正式发布及质量/token优化目标继续开放；没有真实模型调用、账号操作、正式安装或分发。

本地交付包括可隔离运行的20个场景、真实服务/SQLite/文件证据、质量与身份资格审计、同一A主导的保守生产路由、桌面备份恢复、可恢复更新协调器、内部Windows包、CI/依赖清单、持久事故与保留/术语控制器及离线交接。更新协调器使用私有可信端口，外部签名/安装边界由测试端口替代。生产原生部署适配器及D051备份的更新联动、未来合格配置的优化启用仍待接入和范围验收；本轮交付不等于全部产品工程或真实更新已完成。

## 最终实际验证

Python 1489 项通过，0失败、0错误、0跳过；默认规则排除1项 real_provider。桌面单元 84 项、实际Electron 35 项通过，0失败/跳过/重试。类型检查、正式/测试构建和严格契约检查均退出0。全部统计来自本轮日志/JUnit，而不是相加各lane的重叠用例。

统一结果：[verification.json](part-three/final-v3/verification.json)。构建哈希 `cb98eed03df6bd4ffaa551d66a54c77198911cf5b3e763a1ef3c055f5ee54ca4`；验证装置哈希 `be235c533d31cb6f4d79585d028c8da25cedd8d109edd022d33aa00bebcebe95`；验证前后源码一致。实际命令、UTC时间、退出码和原始输出同目录保留。

20个注册场景在独立目录复跑，进程退出后全部run-manifest再次校验通过，汇总见 [scenario-executions.json](part-three/scenario-executions.json)。退出0表示实际审计或故障验证完成；其中安装、真实旅程、统计资格及发布审计仍返回未通过，不能折算为20张卡终验完成。任务板当前为12项in_progress、8项blocked、0项done。

GUI覆盖了真实回环服务、用户提问、公开回放、脚本不执行、合成composition、缩放、文件保存，以及备份ZIP全部文件哈希、真实后端PID重启和恢复后历史。合成composition不计作实际Windows IME，脚本键盘不计作Narrator/多屏人工审核。性能保留200次输入、发送/持久状态原始样本、短生命周期与短持续运行记录；30次完整冷启动、100次完整生命周期、全负载和24小时记录尚未取得资格。

## 当前性能缺口

以下是本轮实际Electron短样本的p95，单位ms；建议值尚未正式预注册，全部结果仍未取得完整负载与硬件基线资格。发送确认、状态可见和启动高于建议值，需要性能分析、优化及固定环境复测；取消反馈尚未采集。

| 指标 | 样本数 | 实测p95 | 建议p95 | 观察 |
| --- | --- | --- | --- | --- |
| 输入回显 | 200 | 18.50 | 100 | 短样本内满足 |
| 发送确认 | 10 | 862.00 | 200 | 高于建议值 |
| 取消反馈 | 0 | 未测 | 500 | 未测 |
| 状态可见 | 10 | 1206.60 | 1000 | 高于建议值 |
| 启动 | 3 | 3405.26 | 3000 | 高于建议值 |

原始来源和阈值摘要见 [performance-observation-summary.json](../../artifacts/qa/D050/performance-observation-summary.json)。短持续运行 [summary.json](../../artifacts/qa/D050/soak-smoke-final-v2/summary.json) 为4个实际本地任务、0失败、进程已清理，full_24h=false。

内部包：[AIBroker-Setup.exe](../../dist/windows/AIBroker-Setup.exe)。包内Python实际导入/服务健康/检查点/进程清理已验证，签名为NotSigned；没有在系统中安装或对外发布。最终字节及源码树对齐见 [packaged-runtime-report.json](../../artifacts/qa/D052/packaged-runtime-report.json) 和 [authenticode.json](../../artifacts/qa/D052/authenticode.json)。

## 独立代理审查和修复

已关闭备份缺原件/来源清单仍被接受、恢复哈希使用迁移前值、GUI缺字段误报通过、身份角色错配、资格扩展到整个领域、私有事故配置破坏偏好保存、提交后恢复任务失败误记REJECTED等问题。精确负例、修复前记录和复验独立保留。

核心审查：[independent-core-review.md](part-three/independent-core-review.md)；更新协调器：[independent-update-review.md](part-three/independent-update-review.md)。审查限制与真实签名/安装端口边界写在各自报告中。中间失败和中断记录均保留；它们不作为最终通过证据。

本轮独立审查由其他代理完成，不代替双语、领域或无障碍人工评审。额外修复了进程退出时SQLite checkpoint导致归档清单失效的问题：实际checkpoint并关闭后才hash，busy/硬链接拒绝归档。原始 [失败记录](part-three/archive-manifest-red.json) 和最终 [20场景退出后复验](part-three/archive-manifest-green.json) 均保留；[独立归档复核](part-three/independent-archive-review.md) 另有5项实际检查通过。

归档修复后再由非实现者独立正向恢复，37文件、schema3→4、原目录与凭证隔离、退出后清单均通过，见 [non-author-final.json](../../artifacts/qa/D051/non-author-final.json)。

## 逐卡交付及开放验收

| 卡片 | 本地交付 | 尚待工作与验收 |
| --- | --- | --- |
| D041 | 验收 driver、真实服务和哈希证据 | D040真实运行资格及完整装置评审 |
| D042 | R01–R15/T01–T20覆盖审计 | 独立人工和真实供应商证据、矩阵签署 |
| D043 | 60例翻译草案与误译拦截验证 | 两名双语评审、60例独立holdout和真实双向翻译 |
| D044 | 十二层协议草案和污染审计 | 60例独立试点、功效样本量、正式评审及冻结签署 |
| D045 | 真实产品账本重放与unknown保留 | 真实逐请求供应商计量及口径审核 |
| D046 | 联合统计门槛与生产A主导路由 | 真实配对评分/用量、按配置优化资格及合格配置的运行启用范围验收 |
| D047 | API、路径、IPC和DOM隔离检查 | 完整链接攻击矩阵及人工安全评审 |
| D048 | 取消、千次重复、未知恢复和旧批准检查 | 全部崩溃断点、文件占用与真实远端取消 |
| D049 | 实际Electron合成输入法、键盘、缩放和瞬时泄漏检查 | 实际Windows IME、Narrator与多屏人工证据 |
| D050 | 原始延迟采样、有界持续运行和桌面生命周期runner | 短样本发送确认/状态可见/启动高于建议值，需分析优化；全部SLO样本/负载、硬件基线、完整24小时及资源矩阵 |
| D051 | WAL一致备份、原件闭包、迁移、API和实际桌面恢复 | 第三方独立手册执行、签名旧程序与匹配旧schema回滚验收 |
| D052 | 锁定打包、便携Python运行时和内部未签名安装包 | 合法签名、可信发布者及干净非管理员Windows安装 |
| D053 | 受控更新协调器、持久日志、签名/清单前检及回滚故障矩阵 | 生产原生安装/清单签名端口、真实签名包升级和兼容schema回滚演练 |
| D054 | Windows CI、依赖SBOM和候选清单审计 | 源码提交、干净构建复现、签名/许可证与完整外部证据 |
| D055 | 四域真实材料入口及严格证据审计 | 当前真实模型身份、完整四域执行及领域人评 |
| D056 | 反馈脱敏、格式和试用手册 | 5工作日真实试用、缺陷关闭与报告者复核 |
| D057 | 功能和优化分离的发布决策 | 全部发布硬门槛、无P0/P1及产品/QA/发布三方签署 |
| D058 | 持久保留/保护、术语历史和缓存失效控制器 | 实际长期保留观察、每日备份/月度恢复及双语术语复核 |
| D059 | 持久事故冻结、证据保护、发布阻断和重新资格检查 | 真实桌面事故演练、独立新样本资格及签名兼容回滚 |
| D060 | 离线证据索引、交接与维护日历 | 干净机器第三方交接、功能/优化终验和签署 |

所有卡的完整门槛仍未结清；逐项状态、责任角色、下一动作、命令与证据入口在 [task-results.json](part-three/task-results.json)。覆盖矩阵保留R01–R15与T01–T20，60条翻译参考仅为未审核草案；独立holdout实际数量为0。真实试点、正式统计注册、盲评与完整真实用量没有伪造。

正式发布账本中的backup_restore_missing、security_boundary_missing等，表示尚未导入绑定正式候选/源提交的合格终验报告；本地自动回归通过不自动满足这些范围更大的发布门槛。原生适配器接入、环境/权限、人工证据和长时运行分别在各卡及交接表中列明。

## 继续使用与复验

从仓库根运行 `npm run build:desktop` 后执行 `npm run desktop`；生产连接未就绪时界面显示不可用。`npm run desktop:demo` 是明确标记的本地演示。备份/恢复通过设置→存储进入，原目录保留。运维控制器、更新私有端口和真实签名接入办法见 release/ops 手册。

复验：`services/orchestrator/.venv/Scripts/python.exe scripts/phase_three_verify.py --python --desktop --output docs/acceptance/part-three/new-run`；逐场景执行 `scripts/phase_three_scenarios.py`；长时/大矩阵独立使用 `tests/performance/soak_runner.py` 和 `desktop_runner.py`，不把短测试冒充完整运行。

工程记录：[更新协调器报告](part-three/update-coordinator-report.md)、[quality-report.md](part-three/quality-report.md)、[backup-report.md](part-three/backup-report.md)、[release-operations-report.md](part-three/release-operations-report.md)。[最终交接](../../release/final-handover.md) 和 [离线证据索引](../../release/offline-evidence-index.json) 保持功能/优化/整体目标为false，并列明真实连接、人评、签名、干净安装、试用和长期观察的责任与下一动作。

前两部分冻结文件及前40卡未被改写，逐文件哈希证明见 [preserved-freezes.json](part-three/preserved-freezes.json)。当前仓库仍无初始提交，以源码哈希绑定验证；未提交Git、创建PR或宣称干净提交复现已完成。
