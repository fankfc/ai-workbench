# D007 合同 v1 复核

日期：2026-10-13（Asia/Shanghai）；合同版本：1.0。复核：Codex。责任角色：后端架构工程师；后续消费角色：接入、翻译、文档与桌面工程师。未声称上述角色是真人已签字，也未声称真实模型已连接。

来源：主计划第 163–209 行旧接口；基础手册 D007（289–313 行）；翻译规格第 8 节（120–138 行）及路由/来源规则；D001 冻结基线。原历史“本轮只写文档”解释沿 DEC-001，不限制本次明确授权实现。

## 十项核对

| 操作 | 结果 / 实现位置 |
| --- | --- |
| 01 ProviderIdentity 保留 | frozen dataclass，`adapter, model_id, family, connection_id` 原构造顺序；扩展证据在独立 ProviderContract |
| 02 AgentRequest/AgentEvent 保留 | frozen dataclass 原 7/5 字段及位置构造；独立 Record 类型负责序列化校验，不加入轮次/快照必需位置参数 |
| 03 身份及路由 | verified/unknown/mismatch；未知可记录且执行检查拒绝；模型族严格 claude/gpt/glm/unknown；A 路由快照冻结 |
| 04 第 8 节数据字段 | RouteSnapshot、MessageRecord、TranslationJob、TranslationBlock、TranslationQA、ArtifactVersion、DeliveryBundle 必需字段逐一保留，无默认值静默补齐 |
| 05 内部与公开独立 | InternalEventRecord 允许内部 payload；公开事件为独立七分支模型，顶层、每种 payload 和嵌套附件均 extra=forbid |
| 06 白名单 | 只允许 message.accepted/response.pending/answer.published/artifacts.published/request.failed/request.cancelled/input.required |
| 07 payload 约束 | 按 kind 分辨具体结构；pending 仅通用等待，错误/澄清声明 zh-CN；答案必须带内容版本/批准引用，不透传 raw_response/log/prompt |
| 08 Python/JSON Schema | 生成 public-events/provider 两份 Draft 2020-12 Schema；provider `$defs` 同时保留路由、内部、翻译、文档记录；schema_version 固定 1.0 |
| 09 反例与证据 | 163 项本地合同测试：原身份/公开边界及 native 无强制双语，另含时间及 offset 范围、哈希长度、JSON 数学整数的跨层正负样本 |
| 10 逐项复核/冻结 | Codex 按来源审阅字段、错误码和兼容决定；合同可交主协调代理独立复核，未把角色责任表当真人批准或端到端产品验收 |

## 兼容及 nullable 决定

RouteSnapshot 的全部十四字段均 required；`identity_source` 与 `route_policy` 可以显式 null，以保存 unknown/mismatch 事实而不猜分支。此决定由主协调代理确认。verified A 仅 Claude→`claude_en_bridge`、GPT→`native`，来源必须非空；GLM 是合法 B 身份，但不是 A 的 verified 路由。执行前还须提供绑定 ProviderContract，核对 provider、实际模型/族、adapter、identity_source 与 connection_version。字段声称 verified 仍不证明真实来源已被可信接入层核验。

MessageRecord 的 parent_message_id；TranslationBlock 的 target_ref/target_sha256；TranslationQA 的 verifier_model/evidence_ref；ArtifactVersion 的 source_version_id/a_response_ref；DeliveryBundle 的 approval_id/published_at 均 required-but-nullable。待生成/待验收可以 null，但 READY 块必须有目标及哈希，A 定稿记录必须有响应引用，通用 PUBLISHED 包必须有批准/时间及至少一个来源版本。不能省略字段来代替 null。

主协调代理复核纠正了初版通用 PUBLISHED 对译文/配对/QA 数组非空的要求：Bundle 只有 route_snapshot_id，不能从该记录猜语言策略。三个数组仍是 required，但 GPT native 单语言或代码成果可以显式空数组；原状态不触发自动翻译。Claude 完整译文/同版配对/QA 门槛由 D035 等后续卡根据真实绑定 RouteSnapshot 和成果合同验收。新增 native 发布回归先观察失败后修复；历史 red-completeness 中的三个双语数组负例是被复核否决的错误通用假设，未作为最终验收要求。

字段类型补充决定：source_locator 为可追溯字符串定位；语义缺陷为有块、代码、严重性、说明、定位的严格记录；作者/审核者记录为角色字符串列表；依赖为版本 ID 和关系的严格记录；format_pairs 按规格显式包含五字段，格式为 pdf/docx/markdown。语言字段保留显式语言标签，GPT 用户原语言可由批准答案记录；错误、取消及必要澄清要求 zh-CN 标签。

旧 dataclass 的 frozen 保证属性不可重新赋值；AgentEvent 的内部 dict 并非深层不可变存储。后续 D008/D010 须以不可变快照/事务保存真实事件，不将浅冻结当成磁盘原件保真。RouteSnapshot 本身由标量/时间组成且禁止赋值，执行检查还重新校验不受验证的 model_copy 更新。

## 字段许可与发布权

JSON/Pydantic 合法样本只证明字段、枚举和有限结构关系。伪造但非空的 approval_id/a_response_ref 仍可能通过结构检查；现有测试特意记录这种边界。D018 必须从真实批准记录读取回答，并核对路由、翻译质量、任务/版本/取消状态，不能将任意用户或模型文本包装成成功事件。本文未实现投影或发布 API。

ArtifactVersion 允许真实登记 B 撰写、A 审核，不能据此当成合格 A 原件。D031 等后续卡负责捕获真实 A 完整正文、模型/会话/请求和字节证据；文件哈希不能单独证明作者身份。双语包还需检查文件存在、哈希、源版本、翻译/渲染、配对原子切换及批准。Schema 不替代这些事实验证。

单个事件只能检查 task/attempt 非空、sequence 正整数等字段；`validate_event_sequence` 必须显式接收同一 task/attempt 的流上下文，才能拒绝重复/倒序。它不要求连续序号，不实现 D012 去重/缺口恢复，也不假称 schema 知道历史。

## 根独立评审后的边界修复

主协调代理证明了三处跨语言差异，追加回归先红后绿。red-time-hash.log 有 16 个实际行为失败、27 通过；red-json-integers.log 有 6 个实际行为失败、18 通过。新增边界选择集最终 67 通过，完整合同集 151 通过，--strict 退出 0。

- 时间字段共享 WireTimestamp：wire 只接受带时区的 RFC3339 字符串（T/t 分隔，Z/z 或 ±HH:MM，秒及可选小数），Python 可接受 aware datetime；数字、数字字符串、naive、空格时间及非法日期拒绝。标准库 BeforeValidator 检查词法及日历；Schema 同时保留 date-time 和精确结尾 pattern，包括 PUBLISHED 条件。测试辅助明确断言 date-time 已注册，不再只实例化 FormatChecker 后默认认为格式检查存在。rfc3339-validator 0.1.4/six 1.17.0 仅由 D002 锁负责人加入测试依赖，生产代码不导入它们。
- Sha256 增加 minLength/maxLength=64，继续只允许小写十六进制；消除 JSON Schema `$` 对尾换行的特殊匹配差异。正常 64 字符、尾换行、非 hex 在两层逐项对照。
- JSON Schema integer 指数学整值数值：共享整数将有限且整值的 float（如 1.0）规范化为 int；bool、字符串、非整值及非有限值拒绝，ge/le 继续导出标准 minimum/maximum。JSON 与 Python dict 模式相同；AgentEvent 保留 frozen 与五字段位置构造，并将 sequence 存成校验后的 int。没有改变发布/翻译服务职责或 native 空数组许可。

同根因 I1 聚焦复验发现 `+00:60` / `+00:99` 会被标准库规范化成其它合法 offset；共享 RFC3339_PATTERN 已在解析前显式限制小时 00–23、分钟/秒 00–59、offset 小时 00–23 和 offset 分钟 00–59。三个时间字段新增越界 offset、`+24:00` 拒绝及 `+23:59` 接受对照。red-offset-range.log 为 6 failed/6 passed；green-offset-range.log 为 12 passed；最新完整集 163 passed，Schema 重生成且 --strict 退出 0。完成后停止源码编辑，交主协调代理及同一独立评审再复验。

PublicEvent 的中文标签不证明正文已经忠实翻译；不使用汉字占比启发式拦截代码/引文。真实中文检查和内部英文瞬时泄漏测试留待翻译、D018 和 GUI 卡。真实接入、来源、质量及发布状态仍 unknown/not_verified。

## 版本规则

外部 envelope 的 schema_version 与 Schema 的 x-contract-version 固定 1.0。字段、枚举、必需性或 payload 语义变化应升合同版本并更新生成 Schema、消费者和样例；--strict 检查存档与 Python 生成结果的 JSON 语义一致，缺失、损坏或漂移返回非零。它不会静默重写；仅 --write 显式生成。未知版本与未知字段拒绝，不同时默许同名字段不同含义。

本次官方接口核对参考 [Pydantic 判别联合](https://pydantic.dev/docs/validation/latest/concepts/unions/)、[JSON Schema 生成](https://pydantic.dev/docs/validation/latest/concepts/json_schema/)与 [extra/frozen 配置](https://pydantic.dev/docs/validation/latest/api/pydantic/config/)，以实际锁定安装版本的本地测试结果为验收证据。
