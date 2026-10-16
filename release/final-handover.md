# 本地工程交接

当前结论：functional_complete=false、optimization_complete=false、overall_goal_complete=false。内部构建和本地自动化证据可以交付审阅，正式安装/分发与用户整体目标尚未取得资格。机器结论见 final-acceptance.json；离线文件哈希见 offline-evidence-index.json；全 R01–R15 证据由根任务质量矩阵列明。

工程文件：apps/desktop/electron-builder.yml、build-windows.ps1、stage-runtime.py、probe-packaged-runtime.py、create-manifest.py、verify-installer.ps1；源 package-lock.json 和 uv.lock 锁定 Node/npm/Python/打包器与库。使用本地 Python 3.13.0 生成 portable runtime，生产依赖按 uv.lock 精确版本逐文件复制，保留许可证元数据和 notices。内部 NSIS 包路径 dist/windows/AIBroker-Setup.exe；没有执行安装或分发。独立 packaged backend smoke 是 no-install 测试，不能替代干净机器验收。

可离线阅读：beta-guide.md、known-limitations.md、customer-acceptance-record.md、backup-restore-runbook.md、update-rollback-runbook.md、../ops/operations-runbook.md、../ops/incident-runbook.md 与 ../ops/maintenance-calendar.md。当前记录没有客户签名或人工通过结果。

| 开放项 | 责任角色 | 下一动作与验收证据 | 工作量依据 |
| --- | --- | --- | --- |
| 生产签名与 publisher | 发布工程师 | 既有合法证书/服务、允许 thumbprint、Authenticode/链/时间戳绑定最终包 | D052 原计划 16h，外部权限另计 |
| 干净 Windows 安装/升级/卸载 | 非开发人员＋QA | 非管理员、中文空格路径、单 taskbar、静默 backend、退出和用户数据保留的原始观察 | D052 真实环境另计 |
| 签名更新与所有断点/schema 回滚 | 发布＋存储 | 本地主进程协调器/真实文件 journal 回归已完成；接入可信 native deployment ports、签名 N−1 包并取得干净机器 5 阶段演练收据 | D053 原计划 16h；没有实际安装 |
| 包 SBOM／许可与格式能力 | 发布＋安全 | 实际所有 runtime/tool/file 清单、许可复核、干净机器格式运行；OCR 不声明可用 | D054 原计划 12h |
| 真实 Claude/GLM/GPT 入口 | 模型接入负责人 | 用户授权合法连接、native identity/receipt、所有尝试用量；未就绪入口禁用 | 外部权限待提供；不采购/不绕过 |
| 四域真实成果与 A 原件/B 译文 | 产品＋领域专家 | 实际材料、纠正/取消恢复/误译止发、MD/DOCX/PDF 成果与专家签署 | D055 原计划 24h，模型成本另记 |
| 翻译与实际 GUI 人工验收 | 双语／无障碍评审 | golden60＋holdout60、独立盲审仲裁；真实 IME/Narrator/多屏 raw evidence | D043/D049 对应卡 |
| 最终候选性能和完整 24h | QA | 预注册指标、固定机器、全部持续过程与检查点 raw evidence | D050 独立 runner；不把短 probe 当 24h |
| A 质量＋A token 优化 | 独立评估负责人 | D046 注册配置、来源/盲审/完整成本，evaluate_eligibility 取得精确 scope | 当前 evidence_insufficient；不可因功能可用关闭 |
| 受控试用与三方发布批准 | 产品／QA／发布 | 实际观察与成果、P0/P1 关闭及复验、R03–R15 功能与 R01/R02 独立状态 | D056 12h、D057 8h 原计划 |
| 运维责任与真实事故/恢复 | 维护＋事故负责人 | 每月隔离恢复、真实桌面演练、独立重资格和人工复盘 | D058/D059 各12h 原计划；不创建自动计划 |
| 独立终验和用户签署 | 用户代表＋非开发人员 | 清洁机器按指南完成连接/提问/两语保存、离线哈希复核、分别签功能/优化 | D060 8h 原计划 |

时间数字是原计划工程估算，不是承诺完成日期或已投入工时。保留现有材料与原现场；未通过对应门槛前不签总体完成。当前无生产签名版本可作为已验证回滚包。

