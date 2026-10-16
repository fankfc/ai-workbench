# 事故响应手册

触发：关键误译、错误双语配对、来源/用量缺口、跨任务泄漏、模型身份改变、质量或 token 优化退化。负责人为指定事故工程师与独立领域/安全评审；实际人员和通知渠道未配置，本次不发送消息。

1. 用 ops/manage.py incident --spec <JSON> 持久记录 domains、qualification_keys、reason、evidence_blobs 与可选 task_ids。领域为 code/paper/document/composite；task_ids 必须属于同一数据库。证据 blob 先核验，保存其哈希到 settings 引用，现有清理器会保护。
2. 重启仍保持受影响领域/任务的 publication freeze 和旧 qualification_key 失效。Native/Answer 的共用 release gate 与 BundlePublisher transaction 均检查同一配置。无关已合格领域可继续；未知 domain 在事故期间保守阻塞。route_for 只给既有独立资格路由附加冻结规则，不生成资格、不改变 provider snapshot。
3. 对受影响任务按产品取消/检查点/远端核对流程止损。质量/token 退化退回 A 主导；关键译文错误仍停止交付。保存构建、模型、术语、完整用量、公共事件与原件哈希，禁止清理事故原现场。
4. 根据已交付文件形成中文影响说明和用户行动草稿，使用 incident-template.md。消息发送需单独授权。数据问题只用已可信且 schema 兼容的签名版本及核验备份恢复；当前签名回滚引擎未取得执行证据。
5. 最小复现区分供应商变化、上下文缺口、策略回归和装置误报。修复样本用于回归，不代替新的独立评测。
6. requalify --spec <JSON> 必须提供 incident_id、registration、evidence、configuration。调用真实 evaluate_eligibility，核验注册、来源、所有尝试用量与盲审；observed_at 必须晚于事故、configuration domain 必须属于影响范围、新 qualification_key 不得等于旧值。仅完全匹配的 configuration 和重新计算的 qualification_key 可以解除该精确 scope 的发布阻塞；easy 不解锁 hard，不同 profile、模型、术语或策略仍冻结。任务必须携带服务自有的完整资格 checkpoint，当前没有任何真实资格可写入。域级 wildcard freeze 保持开放，此接口不会关闭整个事故；旧 key 永久失效，证据 pins 保留。
7. 完成时间线、影响、修复、实际验证、责任人与防复发项。没有真实资格时保持停用，禁止仅提高重试或自动全域复启。

本地 drill 有持久配置/重启、实际取消和原生发布拒绝的回归；真实桌面+模型变更+误译 canary 演练、签名回滚、独立复资格和人工通知尚未执行。

