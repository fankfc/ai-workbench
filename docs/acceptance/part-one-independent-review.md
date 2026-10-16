# 首批 D001 / D002 / D003 / D007 独立范围评审

评审日期：2026-10-13。评审对象是本次四卡交接，不是完整部分一完成、生产发布或 Git merge-ready 声明。仓库无初始提交，以新增文件 diff 和证据文件审查；不修改源码、索引或分支。未创建提交遵循主协调代理集中复核安排，不是人类拒绝提交。

## 最终结论

| 范围 | 规格符合性 | 质量 | 依据 |
| --- | --- | --- | --- |
| D001 | approved | approved | 引用此前 foundation_review 独立结论；此次核读 scope-review 的冻结范围和真实验收边界 |
| D002 | approved | approved | 引用此前 foundation_review 独立结论；本 lane 另复核 v3 最小测试依赖修复及重建证据 |
| D003 | approved | approved | 本 lane 完整源码、四文件 diff、只读报告及 manifest 核查 |
| D007 | approved | approved | 时间、SHA、整数三个 Important 均已修复并独立聚焦回验；协议范围无未闭环问题 |
| 四卡交接 | approved | approved | 需求基线、工程环境、只读探测及合同 v1 的首批集成边界一致 |

当前未闭环 Critical：0。Important：0。Minor：0。历史 Important：3，全部闭环。

最终复核基于 `.superpowers/sdd/D007-final-review.diff`。本 lane 对 RouteSnapshot.locked_at、MessageRecord.created_at、DeliveryBundle.published_at 分别重新检查 `+00:60`、`+00:99`、`+24:00` 两侧拒绝，`+23:59` 两侧接受，12 个聚焦组合全部通过。共享正则在标准库解析前限制时间及 offset 小时 00–23、分钟/秒 00–59，原 I1 规范化绕过已关闭。先前 SHA、整数及 native 空数组的闭环结论保持有效。

`contracts-report.json` 中 2 个 Schema 与 8 个源码/测试文件 SHA-256 已由本 lane 逐项核对当前字节，10/10 匹配。主代理最终 fresh 根测试证据为 **217 passed in 3.63s**，严格检查为 **CONTRACTS_OK:version=1.0;schemas=2**，均退出 0；D007 完整合同集为 163 passed。根 JUnit 和两个 root 日志已更新。本 lane 没有重复全套测试。

本结论仅批准 D001、D002、D003、D007 首批工程交接；不代表 D001–D020 全部完成、GUI/真实模型接入/翻译与交付产品通过，也不是 merge-ready。没有创建 Git 提交。

## 历史记录：稳定修复第一次回验

审查 `.superpowers/sdd/D007-fixed-review.diff` 与 `.superpowers/sdd/D002-format-fix.diff`。D002 仅在 test extra 新增固定 rfc3339-validator 0.1.4，传递依赖 six 1.17.0；生产代码使用标准库，没有导入测试依赖。运行手册和 v3 独立快照证据已更新，主代理已核对 15 个文件和两锁哈希。

主代理 fresh 总体证据更新为 205 passed / 3.91s 与 CONTRACTS_OK:version=1.0;schemas=2。本 lane 单次聚焦回验确认：原日期数字 0、数字字符串、naive、空格时间双边拒绝；正常带时区日期双边接受；SHA 尾换行双边拒绝；sequence 1.0 双边接受、bool/字符串/非整数双边拒绝；native PUBLISHED 空翻译/配对/QA 数组双边接受。以下旧反例表保留为审查轨迹，不能解读为修后仍存在。

首次回验时 I1 剩余反例位于当时的 `providers.py:15-16`、`:28`：`2026-10-13T19:00:00+00:60` 被 Python 接受并转换成 +01:00，而注册 date-time 检查器的 Schema 拒绝。时区分钟 `[0-9]{2}` 容许 60，datetime.fromisoformat 又会规范化它。随后按建议限制时分秒/偏移小时分钟合法范围并增加三字段反例；最终闭环结果见上，无新增依赖。

## 已闭环 Important I1：日期输入和实际 Schema 测试装置不一致

原始受检版本位置：`services/orchestrator/app/contracts/providers.py:148`、`services/orchestrator/app/contracts/events.py:54`、`services/orchestrator/app/contracts/artifacts.py:78`；测试装置 `tests/contracts/test_schemas.py:68`、`:76`。

原版本 `AwareDatetime` 允许 JSON 数字时间戳，Python 与 JSON Schema 的类型定义不同。当时项目环境 `FormatChecker().checkers` 不含 `date-time`，所以实例化 FormatChecker 没有实际校验日期时间格式。原实施报告将该装置描述成跨语言格式验收，证据不足；最终版本已修正。

只读聚焦复现使用项目虚拟环境 Python，导入现有 route_sample 并分别运行 `RouteSnapshot.model_validate_json` 与 `Draft202012Validator(RouteSnapshot.model_json_schema(), format_checker=FormatChecker())`：

| locked_at JSON 值 | Python | JSON Schema 当前装置 |
| --- | --- | --- |
| `0` | 接受，转换成 1970-01-01T00:00:00Z | 拒绝 |
| `"0"` | 接受，转换成 1970-01-01T00:00:00Z | 接受 |
| `"2026-10-13 19:00:00+08:00"` | 接受 | 接受 |
| `"2026-10-13T19:00:00"` | 拒绝无时区 | 接受 |

风险：同一持久化记录在 Python 和跨语言消费者之间有不同合法性，原始错误时间可能被规范化掩盖；现有绿色测试不能证明所报告的日期边界。

建议：明确共享时间字符串/时区合同，拒绝 JSON 数值及数值字符串时间戳；确保 Schema 一侧真的验证该合同（显式 schema 约束及实际注册的格式检查器均可），在三种记录上加入数字、数字字符串、无时区、合法带时区样本的双向对照反例。无需启动任何真实模型或改变其他业务范围。

## 已闭环 Important I2：SHA 正则尾部换行两侧接受行为不同

位置：`services/orchestrator/app/contracts/providers.py:10`，以及 `translation.py:36` 的 READY 目标 SHA 条件。

主代理提出反例后，本 lane 独立复现：64 个小写 `a` 两侧均接受；64 个 `a` 后追加换行，Pydantic 拒绝，而 Draft202012Validator 接受。原因是 Schema 消费端正则 `$` 可匹配最终换行前的位置。建议在共享 SHA 类型及条件约束显式加 `minLength=maxLength=64`，加入带换行、过长、大小写及正常长度的跨语言回归。

## 已闭环 Important I3：JSON 整值数字语义不一致

位置：`services/orchestrator/app/contracts/providers.py:11-12` 与 `translation.py:25`。

本 lane 独立复现：公开事件 `sequence: 1.0` 被 Python strict int 拒绝，JSON Schema integer 接受。JSON Schema 的整数语义按数值而非原始文本判断，跨语言输入不宜依赖 `1` 与 `1.0` 的序列化外观。建议统一接受有限整值数字并保留对 bool、字符串、非整数的拒绝，或明确记录兼容限制；当前不能把两侧输入集合描述为一致。相关 attempt_count 和 size_bytes 应采用同一策略。

## D003 已核查的边界

- `probe.py:99-112` 只允许已知工具版本/帮助参数，原生文件名检查、shell=False、关闭 stdin、超时、隐藏窗口和环境裁剪均存在。GUI/未知工具/脚本 shim 不从此入口启动。
- `probe.py:213-235` GUI 使用 PE 版本元数据；实际 trace 只有 Python/Node/Codex 版本和 Codex 帮助四条命令。
- `probe.py:175-209` profile 验证、默认只读、显式正数上限、生产 executor 未启用和调用前扣减上限均存在。模型族、适配器、所选连接与精确模型 ID 已绑定；失配立即终止。
- `probe.py:66-84` 明确可信适配器采集责任，哈希验证完整性而非真实性。假 executor 的启动次数边界不能替代以后真实适配器内部重试/单调用单请求验收。
- 实际安装报告：ZCode GUI `D:/zcode/ZCode.exe` 3.15.1.8093；Codex CLI 0.160.0；Claude 在受检位置未见。模型身份、会话/登录/额度共享均 unknown。无生产模型 executor。
- 现有 `probe-green.log` 为 53 passed；source-manifest 七项文件与工作区哈希全部一致。本 lane 未重跑整个 suite、未读密钥或用户配置、未调用真实模型。

## D007 其余已核查的边界

- ProviderIdentity / AgentRequest / AgentEvent 与主计划原定义一致，分别保留 4 / 7 / 5 个位置字段及 frozen dataclass。浅 frozen 不等于内部 dict 的持久化不可变，报告已准确说明。
- `ProviderContract.require_executable` 拒绝 unknown/mismatch；`RouteSnapshot.require_executable` 重新验证快照，并绑定 provider、实际模型/族、adapter、身份来源及连接版本。Schema 的 verified 字段不能证明真实鉴权。
- PublicEvent 使用七个判别联合分支；顶层、payload 和嵌套附件 extra=forbid。未知 kind、raw_response、错误 payload 不自动透传；取消必须 strict boolean true。
- 翻译规格第 8 节各记录必需字段全部显式保留；visibility、状态、SHA、attempt 与 sequence 有结构约束。乱序校验需要显式流上下文，不冒充单个 Schema 能感知历史。
- `DeliveryBundle` 通用 PUBLISHED 仅要求来源版本、批准引用和发布时间；native 可以显式空 translation_version_ids / format_pairs / qa_ids。这与 D001 的 GPT 零强制翻译一致；Claude 双语质量与配对完整性由后续真实绑定路由的发布层验收。
- A 原件的响应引用、批准引用、文件哈希都是结构条件，不能证明真实 A 作者、翻译忠实性或发布批准。D007 文档明确保留后续来源捕获、D018 发布门控与 D035 双语配对的责任。
- 主代理最终 fresh 总体证据：`docs/acceptance/root-foundation-tests.log` 为 217 passed；`root-contracts-check.log` 为 CONTRACTS_OK:version=1.0;schemas=2。本 lane 未重复整套测试，只执行有具体疑虑的聚焦反例与修后回验。

后续 API、GUI、真实 provider、翻译、持久化/发布服务尚未实现不是本批缺陷；当前批准范围不能扩展为这些后续能力已验收。
