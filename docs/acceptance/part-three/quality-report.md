# 阶段三 D042–D046 本地质量工程记录

状态：本地验证工具已实现并测试；第一/二部分冻结记录保持不变。阶段三逐卡本地进展汇入任务板，完整终验保持开放。没有新增真实模型请求、人工签字或正式优化资格。R01/R02 及整体目标仍未完成。

| 卡片 | 已实现的本地内容 | 原门槛尚缺材料 |
|---|---|---|
| D042 | 从 D001 原记录保留 R01–R15 原文、来源和责任角色；映射 T01–T20；版本/矩阵哈希；自动、人评、真实接入证据分类；删 T13、缺文件、skip/xfail、缺哈希证明均不能算完成 | 全部人工/真实验收证据仍未导入，15 项当前均有未验证强制项；矩阵的人类签署尚无 |
| D043 | 60 个双向草案，代码/论文/文档各20；保留原3个ID；每例明确 unreviewed_draft；现有产品 segment/protect/evaluate 运行记录；已知否定/数值/不确定性负例；实际 TranslationService 的 GPT 原语言分支调用数0；审核表与独立 holdout 空清单 | 两位独立双语领域评审、60例真正独立保管holdout、全块/高影响语义裁决、真实 Claude 首问/追问/澄清及 GPT 接入资格。故意注入的语义 findings 为测试夹具，只验证产品拦截行为，不证明自动识别所有误译 |
| D044 | 十二领域/难度层协议草案；六维量表、失败成本规则、零质量折扣、单次分析与全84比较 Bonferroni/Hoeffding方法；注册哈希、holdout污染和篡改检查 | 60个真实独立试点、方差/功效分析、正式样本量、各层事前A成本上限、实际配置、独立评审及三方冻结签署。当前 status=draft，formal_sample_size/max_a_tokens=null，不允许 frozen 结论 |
| D045 | 现有 UsageLedger 实际 SQLite 请求账本重放；120重复为1请求；累计100/180/250总量250；失败/取消/翻译/审查/接管/定稿成本；unknown=null、估计分开、0合格交付成本=null；原始事件与派生账本 | 真实 Claude/GLM/GPT 原始计量回执、逐提供方口径审核与对账；当前全部wire样本明确 synthetic，real_usage_verified=false |
| D046 | 六质量维度与A token差联合下界，84个比较修正；实际模型/领域/难度/配置/翻译/术语/调度/协议资格键；候选字节、实际干净Git提交、原始样本/身份/盲评/提交日志/计量哈希及相互匹配检查；缺证据路由a_led | 真实被冻结协议和独立配对样本、全部人评/身份/用量证明、源提交和签名候选。当前资格为空，优化启用接口未开放；未来实证合格配置的运行启用需对应范围验收 |

D046 生产安全路由已接入 `runtime/native_backend.py` 和 `runtime/workflow.py`。私有 production assembly 将初始候选交给同一实际 A，A 获得原资料并输出完整正文；再经已有 C 验证、A 审查及发布门槛。租约恢复、取消、原语言/Claude 英文定稿约束和用量记录保留。当前固定fixture仍运行原B/A路径；真实生产模型尚未接入验收，不据这些回归宣称真实可用。A接管预算缺失时保持阻塞，不能借回退忽略用量。

统计方案仍为提议草案。有限样本的分布无关下界很保守；观察到相同平均质量本身不足以令其下界达到零。正式试点和功效分析必须在看正式结果前审核该方案和所需样本数，不能为了出具通过结论事后换方法或降低质量目标。

已实际执行的验证：

- 新验证器初始负例：`python -m pytest tests/acceptance/test_requirement_coverage.py tests/translation/test_release_corpus.py tests/quality tests/usage -q`，21失败，原因均为尚未实现的能力/样本扩展。记录 `quality-red.log` / `quality-red.xml`。
- 原始证明防伪负例：`python -m pytest tests/quality/test_optimization_gate.py -q`，新增3项失败，原13项范围中10项通过；记录 `quality-proof-red.log`。
- A主导路由负例：`python -m pytest tests/quality/test_conservative_native_route.py -q`，1失败，明确暴露旧代码仍启动B；记录 `quality-route-red.log`。
- A主导路由与既有核心工作流：`python -m pytest tests/quality/test_conservative_native_route.py tests/integration/test_agent_workflow.py tests/integration/test_native_backend_bindings.py tests/integration/test_prepared_workflow.py -q`，92通过，0失败；记录 `quality-route-green.log`。
- 翻译、用量和质量相邻回归：`python -m pytest tests/acceptance/test_requirement_coverage.py tests/translation tests/quality tests/usage tests/unit/test_usage_ledger.py tests/integration/test_input_translation.py tests/integration/test_output_translation.py -q`，95通过，0失败；记录 `quality-green.log` / `quality-green.xml`。
- 最终本 lane 验证（包含5个经正式scenario CLI的probe）：`python -m pytest tests/acceptance/test_requirement_coverage.py tests/translation/test_release_corpus.py tests/quality tests/usage -q`，30通过，0失败；记录 `quality-final.log` / `quality-final.xml`。
- `python docs/acceptance/part-three/run-quality-evidence.py`，五个实际场景CLI均退出0，产出JSON报告、实际数据库/QA记录及文件哈希manifest。记录 `quality-evidence-runs.json` 与 `artifacts/qa/D042` 至 `D046`。退出0表示审计程序正常执行，各报告仍准确给出功能/优化未完成。

上列测试均使用 `services/orchestrator/.venv/Scripts/python.exe`，真实提供方调用数0。pytest报告1个既有Starlette/httpx弃用警告，没有用skip替代验收。不同测试组有重叠，不能相加为不重复用例数量。

最终独立复核追加了实际身份角色门槛：A 仅允许 Claude/GPT 对应适配器及家族，B 仅允许 ZCode/GLM；身份报告与哈希原始回执均必须具有 native_connection 来源、verified 状态、匹配家族和实际模型版本，角色恰好各一份。新增5个文件哈希负例先观察到5失败/14通过（`quality-role-identity-red.log`），修复后的本lane全套为 **35通过、0失败**（`quality-role-identity-green.log` / `.xml`）。此前30通过记录保留为历史，不覆盖。

独立评测样本正文没有伪造或放入仓库，相关清单的实际样本数为0。所有项目角色只是职责标签，没有声称获得真人签字。当前仓库无可解析提交；正式候选、签名、真实连接、人评和上游D004/D005/D020/D024/D040资格仍需补齐。

原始证据契约见 `quality/eligibility-evidence-contract.md`。继续时先补真实接入资格，再采集独立双语/领域人评和正式预注册样本；本报告与历史冻结证据均保留，不覆盖或改写原验收结论。
