# 本地运维手册

维护负责人：指定的维护工程师，人员尚未确认。当前不创建自动计划。指标未知保持 null/unknown；不以零代替缺失。诊断与用量只在独立设置/诊断页展示，主聊天保持面向用户的结果和中文状态。

OperationsController 将运维配置写入既有 desktop_settings 的 operations JSON，复用数据库事务、保守 storage.cleanup 和不可变 GlossaryStore。它不创建另一套任务状态机。手动 CLI：
```powershell
services/orchestrator/.venv/Scripts/python.exe ops/manage.py --database <现有数据目录/workbench.sqlite3> view
services/orchestrator/.venv/Scripts/python.exe ops/manage.py --database <现有数据目录/workbench.sqlite3> retention-preview
```
把预览 JSON 保存到本地文件后，复核所列文件，仅显式确认才执行 retention-apply --spec <预览文件> --confirm。CLI 不替用户确认、不自动排期、不操作模型或账号。

提议 TTL 为诊断 14 天、事件 90 天、用量汇总 365 天；可用 retention-policy --spec <JSON> 配置这三个类别的正整数天数，配置重启仍保存，不能把会话或交付物加入年龄清理。仅检查数据根下 diagnostics/diagnostic_logs、runtime_events、usage_summaries 的 JSON。活跃/待核对任务使清理整体阻塞；诊断 pins 保留事故和备份引用，数据库所有引用保留 blob。任务、聊天、交付物、备份不在年龄清理范围。执行前在同一数据库 writer 中重检哈希、年龄、设置版本和引用快照，变更就拒绝。非法路径、reparse 和 hardlink 被拒绝。故障先停止清理，核验最近完整备份再隔离恢复，不覆盖现场。

本地指标包括任务成功/失败/阻塞/恢复、翻译拒绝、队列、磁盘及真实用量完整率。阈值须建立实际机器/工作量基线，当前没有捏造数值阈值。每日人工检查最近备份哈希；每月按 backup-restore-runbook.md 在新目录恢复并记录真实结果。已有源材料和包资格改变必须复验。

术语修改由 glossary-change --spec <JSON> 执行，字段 task_id、version、domain、entries(source/target/sense)、reason、reviewer。旧 GlossaryStore 行和翻译 job/历史不改写；相关任务的实际 translation_cache.valid 清零，新的版本/内容哈希改变 cache key。重要专业术语仍需真实双语复核；CLI reviewer 字符串本身不是已批准证据。变更记录持久保存旧历史及新内容哈希；ops/glossary-change-log.jsonl 当前为空，表示没有生产术语变更。

诊断导出复用 /v1/diagnostics/export 严格 allowlist；不包含原文、附件、凭证、incident reason 或整个 preferences JSON。当前未实现正文附加 consent UI，CLI include_content 不能冒充授权。每周记录实际健康、未关闭事故、恢复日期和待办；供应商/术语/策略改变后移除旧资格。

