# 优化资格证据导入契约

入口为 `app.quality.eligibility.evaluate_eligibility(registration, evidence, configuration)`。只接收已受控导入的文件索引；该接口不发送模型请求、不联系评审、不获取账号权限。所有相对路径均在 `evidence_root` 内，拒绝父目录、绝对路径、目录联接及硬链接；每份证明同时核对字节数与 SHA-256。

`configuration` 包含 `a_version`、`b_version`、`domain`（code/paper/document/composite）、`difficulty`（easy/medium/hard）、`task_profile`、`translation_policy`、`glossary_version`、`scheduling_policy`、`protocol_hash`。每一字段进入资格键。注册的 `scope.configuration` 包含相同字段但省略 `protocol_hash`，避免自引用哈希。注册哈希在删除 `registration_sha256` 后对排序、紧凑、UTF-8 JSON 计算；必须创建新版本而非覆盖已冻结协议。

`registration` 按 evaluation-registration.json 草案字段补齐十二层样本数与各层事前 A 总 token 上限、60 个真实试点、功效分析、单次分析时间、两位独立命名评审、第三裁决人、三方冻结签字、独立 holdout ID 和零失败丢弃规则后才能设为 frozen。当前草案不能据填入 frozen 一词放行。

`evidence` 必需字段：`source_kind=external`、`evidence_kind=real_evaluation`、`configuration`、`protocol_hash`、`observed_at`、`candidate_path`、`candidate_sha256`、`candidate_size`、`commit`、`source_root`、`evidence_root`、`samples_path`、`samples_sha256`、`samples_size`、`samples`、`identity_reports`、`review_reports`、`usage_reports`。候选文件在 evidence_root 内，源目录必须能解析同一个实际 Git HEAD 并保持干净；无提交的当前工作区无法获得正式优化资格。样本 JSON 文件内容必须逐项等于 samples。

三个 reports 字段均为 `{path,size,sha256}` 列表；不能填 true、字符串“verified”或普通对象替代真实文件。每个被引用 JSON 报告含 `source_kind=external`、实际 `candidate_sha256`、`commit`、带时区 `observed_at`，绑定同一候选与源身份。

身份报告每个 A/B 角色恰一份，字段 `role`、`actual_version`、`identity_status=verified`、`identity_source=native_connection`、`family`、受支持 `adapter`、`wire_receipt`。A 的 adapter 只允许 claude_code/claude-code（family=claude）或 codex/gpt（family=gpt）；B 只允许 zcode（family=glm）。后者亦为哈希引用，原始身份回执包含 `source_kind=external`、`model_version`、`adapter`、`family`、`identity_status=verified`、`identity_source=native_connection`、`request_id`；家族和版本必须匹配角色、报告及实际配置。交换 A/B、重复角色、任一侧家族错误或用户自行声称的身份来源都拒绝资格。

每个正式样本恰好有一份盲评报告，包含 `sample_id`、`reviews`（至少两位互不重复的注册独立评审，reviewer_id、independent、blind、baseline_scores、collaborative_scores）、两种不同匿名 `blind_labels`、注册 `adjudicator`、`adjudicated=true`、裁决后的 `baseline_scores`、`collaborative_scores`、两臂关键缺陷数。六维分数均在 [0,1]；裁决分数及缺陷数必须对应样本。匿名标签不得含实际模型版本。

每个样本恰好有一份用量报告，含 baseline/collaborative 两臂，每臂包括 `all_attempts_included=true`、`submitted_request_ids`、`submission_log` 哈希引用、`requests`。提交日志包含 external 来源、sample_id、arm 和全部 submitted_request_ids。每请求为 request_id、role、function、provider、source=reported、status（completed/failed/cancelled）和 wire_receipt 哈希引用。原始回执含 external 来源、request_id、usage 供应商原始字段；由现有 normalize_usage 解释，父/子计量不重复相加。两次重复回执去重，有冲突立即拒绝。请求集合必须与真实提交日志一致，每臂全部 A token 必须恰等于样本中的成本。

每个样本字段为 id、source_kind=external、configuration、blind_review_complete=true、randomized_order=true，以及 baseline/collaborative 的 scores、a_tokens、critical_defects、usage_complete=true、usage_source=reported、all_attempts_included=true、qualified_delivery 布尔值。失败交付六维全部记零；未知或估计用量、缺盲评、超越事先成本上限、新增关键缺陷都拒绝资格。

返回 eligible、optimization_goal_met、route、blocked_reasons、qualification_key、quality_bounds、token_savings_lower_bound、qualified_scope。缺证据或未获资格均为 a_led。哈希审计证明已导入字节的一致性和相互关联；真人身份及原始供应商回执的真实性仍必须由受支持采集流程和发布/评测负责人批准，不能由测试夹具或 AI 自签代替。当前没有任何真实已批准配置；实际生产 assembly 始终先由 A 执行，优化启用入口待正式独立证据与对应范围验收。
