# 候选发布核对

当前决策 NO-GO。内部未签名包和本地回归存在；正式签名、安装、更新、真实模型和独立人工证据尚未导入。release-decision.json 与 candidate-evidence.json 是机器可读入口。

| 门槛 | 检查器和要求 | 当前发布状态 |
| --- | --- | --- |
| 最终字节、源提交、锁依赖 | create-manifest.py；最终哈希、本次 commit、干净 source tree | 源库尚无提交，不能冻结发布身份 |
| SBOM 与许可证 | sbom.py 锁清单 + 实际 staged runtime/tool/license audit | 仅锁清单和内部文件/许可证元数据，不是已复核包 SBOM |
| Authenticode | verify-installer.ps1 原生再观察；生产 thumbprint allowlist、链、时间戳 | 当前候选未签名；allowlist 空 |
| D043 翻译 | 60 golden + 60 独立 holdout，双盲双语评审、关键错误零、仲裁 | 独立真实人工报告缺失 |
| D047 安全 | 强制案例全部执行，skipped 空、critical_findings 空 | 本地回归与外部发布报告分别记录 |
| D049 人工 GUI | 实际 Windows IME、Narrator、多屏三项 raw evidence | 人工签署缺失 |
| D050 性能、24h | 注册阈值、真实机器/样本/指标、完成 86400 秒并复验检查点 | 长时和最终候选报告未取得 |
| D051–D053 恢复、安装、更新 | 一致备份、隔离恢复、签名候选干净非管理员账户、完整断点矩阵 | 本地恢复/打包 smoke 不替代签名安装更新 |
| D055 真实四域 | Claude+ZCode native receipts、真实交付物、独立人工评审 | 0 真实调用，无可声明 scope |
| D056 试用 | 实际用户、成果检查、缺陷复验和观察窗口 | 未开始；空台账不代表零缺陷 |
| 三方发布批准 | product/qa/release 三个独立评审，P0/P1 已关闭；R03–R15 功能通过，R01/R02 独立状态已评审 | 未签署 |
| 优化批准 | evaluate_eligibility 真实数据与完整 configuration；scope 带 qualification_key | evidence_insufficient，保持 A 主导且整体目标未完成 |
| D060 交接 | 未参与开发者干净机器操作、用户签署、离线哈希索引 | 本地文件齐备不代表验收完成 |

禁止用 passed 标签、未执行的人工项 N/A、skip、旧构建报告、内部未签名包或 TEST_ONLY fixture 放行。functional_release 和 optimization_goal_met 独立计算；功能成立时仍可能优化未完成。实际分发须另有用户授权，本次没有分发。

