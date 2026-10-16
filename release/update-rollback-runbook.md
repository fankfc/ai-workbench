# 签名更新和回滚手册

已实现主进程 UpdateCoordinator 和更新前置拒绝器，具备真实文件暂存/哈希、认证 manifest、持久阶段 journal、原生签名私有端口、检查点/一致备份、安装/迁移/健康检查与兼容前任恢复流程。协调器通过私有可信端口调用 native installer、D051 备份/恢复和 backend；没有 renderer 能提供授权布尔值。40 个真实文件系统测试使用明确 test-only 的原生签名/安装端口验证本地事务逻辑；实际签名安装、原生安装器/后端部署适配器与干净机器更新演练仍须真实外部留证。

正常更新 manifest 必须符合 update-channel.schema.json。桌面主进程的 evaluateUpdate 检查频道、递增 sequence、严格版本、最低兼容版本、最终包 SHA-256、由 Windows 原生核验获得的签名链/时间戳/允许发布者、非测试证书、已核验一致备份和任务检查点。结果 READY_FOR_EXTERNAL_INSTALL 只允许进入后续受控安装演练，不意味着已经安装或可以发布。renderer 和网络 manifest 不能提供签名权威。

下载必须进入独立暂存目录。拒绝未知发布者、未签名、篡改、重放和普通网络降级。允许回滚只能来自预先保存且可信的 N−1 包及其对应 schema 备份；不能用授权回滚标志允许网络下发旧版本。

UpdateCoordinator 将 candidate、已可信 predecessor 与对应 backup 复制进单独 transaction 目录并 fsync，阶段 journal 在每次副作用之前原子保存。native verifyManifest 回执必须绑定排序规范 JSON 的 manifest SHA-256 与包 SHA-256，防止将旧签名包改称新版本。安装和迁移回执要匹配目标；首次健康通过才提交 authoritative version/schema/sequence。中断从 journal 有界恢复，失败重验前任签名、备份哈希和 schema 再回滚；恢复受阻保持停止并要求人工处理。成功 commit 或 rollback 后若 resume 失败，仅有界重试恢复接收任务，不能再次覆盖用户新数据。journal 大小、记录数、恢复次数和事务数有明确上限；原证据保留。

实际演练由发布和存储工程师在隔离干净账户执行：下载、解包、文件替换、迁移及首次健康检查分别中断；保存检查点和一致性备份；首次健康失败时恢复匹配的旧 schema 和旧包，复验任务与文件哈希。兼容窗口之外保持阻塞，保留原数据库和事故证据。逐项报告必须绑定本候选和源提交。

所需报告 fields：invalid_signature_rejected、unknown_publisher_rejected、tamper_rejected、replay_rejected、downgrade_rejected、consistent_backup_verified、checkpoints_saved、all_interruptions_tested、health_failure_rollback、compatible_schema_restored；另有 active_version、previous_version、expected_schema 与 restored_schema。所有布尔值必须附哈希绑定的实际原始观察，不能由 CLI fault 标志生成。

