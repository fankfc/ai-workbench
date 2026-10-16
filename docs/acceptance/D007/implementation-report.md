# D007 实施报告

日期：2026-10-13（Asia/Shanghai）；合同版本：1.0。实施与本地复核：Codex。人类签字：未声称。未提交、未修改任务板/原计划/依赖锁，未调用真实模型。

已实现旧 4/7/5 字段 frozen dataclass 的兼容构造、独立 Pydantic 记录、冻结 A 路由快照、七种严格 PublicEvent、翻译/文档完整记录、Adapter Protocol 和两份由 Python 生成的 JSON Schema。--strict 拒绝缺失、损坏及漂移，只有 --write 修改 Schema。文件为本任务授权范围；没有写 API、真实适配器、翻译服务或发布服务。

测试先于实现：可执行宽松 stub 下出现 56 个业务反例失败；绑定关系 5 个失败；schema 漂移 1 个失败。复核追加完成引用/路由拷贝和取消整数布尔转换反例，先观察失败再修复。主协调代理指出通用 Bundle 对译文/配对/QA 数组非空的初版条件误伤 native 路径；新增 native 发布回归先观察失败，再移除三项无条件非空检查（字段仍 required）。历史 red-completeness 的三个数组负例为被否决的通用假设，不算最终需求。保留 red*.log，不用依赖/导入缺失作为业务失败。临时 schema 漂移仅发生于 pytest 临时目录。

最终实际命令使用 `services/orchestrator/.venv/Scripts/python.exe`：

| 命令 | 实际结果 | 证据 |
| --- | --- | --- |
| `-m pytest tests/contracts/test_schemas.py -q --color=no` | 163 passed，0 failed，退出 0 | green.log |
| `scripts/check_contracts.py --write` | 显式生成两份 Schema，退出 0 | schema-generation.log |
| `scripts/check_contracts.py --strict` | CONTRACTS_OK:version=1.0;schemas=2，退出 0 | strict.log |

测试用合法/非法 fixture 同时验证 Pydantic 和 JSON Schema（含 FormatChecker），覆盖必需/nullable、未知身份可记录不可执行、模型路由/连接证据绑定、extra、错误 kind/payload、缺 attempt、非法 sequence/visibility、批准引用、嵌套附件、事件流乱序、完成状态引用与严格漂移。单个事件不检测历史，流校验必须显式提供上下文。

环境：Python 3.13.0、Pydantic 2.14.1、pytest 9.1.1、jsonschema 4.26.0、PowerShell 7.6.5。冻结时 HEAD 不存在，`git rev-parse --verify HEAD` 退出 1；不虚构提交。契约、Schema 哈希、实际命令和日志见 contracts-report.json，字段/兼容审阅见 contract-review.md。

根独立最终评审后补时间/哈希/整数三项修复：red-time-hash.log 实际 16 failed/27 passed，red-json-integers.log 实际 6 failed/18 passed；修复后边界集 green-boundaries.log 为 67 passed，完整集为 151 passed。时间统一为 RFC3339 wire 字符串或合法 Python aware datetime，拒绝数字/数字字符串/naive/空格/非法日期；JSON Schema 使用 format 和精确结尾 pattern。日期检查测试显式要求 date-time registered，D002 锁负责人已加入仅测试使用的 rfc3339-validator 0.1.4 与 six 1.17.0，生产校验只用标准库。

Sha256 显式固定 64 字符长度，拒绝尾换行/非 hex。共享整数按 JSON 数学 integer 语义接受并规范化有限整值数值（1.0→int），拒绝 bool/字符串/非整值/无限值，保留 minimum/maximum；Python dict 与 JSON 模式均验证。AgentEvent 的 frozen 属性及字段顺序不变，sequence 保存为规范化 int。修复未更改其它模块或锁，也未恢复 native 路径的双语数组非空要求。

同一 I1 的最后聚焦修复：标准库会将 offset `+00:60` / `+00:99` 规范化，现由共享正则在解析前拒绝。显式限制时间及 offset 的小时 00–23、分钟/秒 00–59，保留合法 `+23:59`。三字段回归先记录 6 failed/6 passed（red-offset-range.log），修复后 12 passed（green-offset-range.log）；最新完整集 163 passed、--strict 退出 0。Schema 和全部实施哈希已刷新；源码停止编辑，等待主协调代理鲜跑及独立聚焦复验。

required-but-nullable route_policy 决定由主协调代理确认：unknown/mismatch 可以显式 null；verified A 只能 Claude bridge/GPT native，身份来源和连接版本均有绑定校验。所有专门规格字段显式 required，pending/null 与 READY/PUBLISHED 的通用引用要求分开。native PUBLISHED 可显式空 translation_version_ids/format_pairs/qa_ids，不能强制双语；Claude 配对完整性须按已绑定路由由后续 D035 核实。

字段合法不等于发布批准：非空 approval_id/a_response_ref 仍可能指向未验证记录。D018 须核对真实批准、版本、路由、翻译和取消状态；D031 等后续卡须捕获实际完整 A 正文及来源，文档发布须验证文件、哈希、语义/渲染与原子配对。本卡没有这些服务，也不能以 Schema 中的 verified/PUBLISHED 字段声称真实接入、A 作者或交付已经通过。B 来源可如实登记，不能用 B 撰写/A PASS 代替 A 原件。

后续须核实真实模型身份、安装版本及工具能力；翻译/GUI/质量/发布仍独立验收。旧 dataclass 属性冻结不等于内部 payload dict 深层冻结，真实事件快照由后续持久层承担。主协调代理的独立复核由其记录，本子代理不更新任务状态。
