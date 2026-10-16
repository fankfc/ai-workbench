# 质量验证、Windows 发布与长期运维 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把双模型工作台从可运行构建推进到有质量证据、可签名交付、可恢复且可长期维护的软件，独立验证 A 质量与 A token 优化目标。

**Architecture:** 本卷仅扩展 D001–D040 已有开发测试和产品实现。系统验收装置驱动真实本地服务、数据库与桌面，假外部适配器只用于确定性故障复现；真实模型、人工评审和签名安装分别留证据。功能发布资格与用户优化目标达成独立判定。

**Tech Stack:** Windows 11 x64、Electron/React/TypeScript、Python/FastAPI/SQLite；pytest、Playwright Electron、PowerShell、签名安装包和 SHA-256 证据索引。

## Global Constraints

- 本卷是执行手册，不代表程序、测试、签名、统计结果或真实模型接入已经完成。
- 根目录为 `C:/Users/asd15/Documents/ChatGPT/ai`；以下拟建路径均相对于根目录。
- D041–D060 共 20 张卡、每卡 10 个动作。卡内工程步骤由执行者按文件拆成短操作，遇失败先修复当前门槛。
- 只依赖更小编号；D041 是系统验收 fixture 扩展，不是 D001–D040 开发测试的前置条件。
- 全部示例 CASE 都必须调用实际产品或评估器并读取真实证据，不允许硬编码通过结果。
- 默认 A 为 Claude Code 中的 Claude、B 为现有 ZCode 中的 GLM，GPT 为可选 A；不静默切换提供商。
- Claude 中文输入和追问完整译英、最终英文回答完整译中；GPT 无强制翻译，主聊天不显示内部过程。
- Claude 文档完整英文定稿必须确由 A 输出，B 负责中文译文；不能用 B 写全文、A 仅 PASS 冒充 A 原件。
- 质量优先于节省；不能截掉必要 A 推理、审查或完整英文定稿成本制造节省。
- 安装包、模型调用、统计门槛均为待执行事项；本次不安装、不操作账号、不采购服务、不实际发布。
- 现有授权允许的受控真实测试仍应记录成本；无服务权限时保留明确阻塞，不设计地区限制绕过。
- 测试退出码 0 只证明所运行检查通过；缺证据、skip、装置异常与未验证不能算通过。
- 提议统计阈值需在看正式结果前预注册；95% 置信水平不意味着允许损失 5% 质量。
- A 主导 fallback 可以满足功能发布门槛，但不等于满足用户要求的“保持 A 质量并减少 A token”整体目标。
- 长时测试独立运行并保留进度；执行者持续汇报，不用阻塞式长等待妨碍沟通。

## 上游接口与文件责任

- 产品应用：`services/orchestrator/app/api/application.py:create_app(settings: AppSettings) -> FastAPI`。
- `AppSettings(data_root: Path, api_token: str, provider_mode: "fake" | "real", startup_recovery: bool)` 来自 D009。
- `POST /v1/conversations`、`POST /v1/conversations/{id}/turns` 驱动真实任务；发送携带 `text/provider_profile_id/client_request_id`。
- `GET /v1/tasks/{task_id}`、公开 messages 和带 `after_seq` 的 SSE 用于核验；取消请求 202 不等于远端已确认取消。
- Electron 主进程代理本地令牌，renderer 不持有服务或模型凭证；测试钩子仅存在于 tests/support。
- 每个场景模块 `tests/support/scenarios/<case>.py` 导出 `run(root: Path, options: dict) -> dict`，D041 registry 注册后供 CLI 调用。
- driver 启动隔离环境并在 finally 中清理；场景 schema 拒绝未知选项，真实 evidence manifest 校验后才返回。
- 每卡“Interfaces”列明该场景的结果字段；下方测试是可直接保存到拟建 Test 文件的完整代表性测试。
- 大文件、压力数据与匿名评估标签由固定 seed 生成；人工报告和真实账号结果不能由 fixture 自动捏造。
- 修改产品文件只为修复经复现的问题；对应模块责任人评审，QA 不另起第二套业务状态机。

## 完整通用 fixture：tests/conftest.py

将下列 fixture 合入已有文件，避免覆盖 D001–D040 的 fixture。产品包延迟导入留在场景 handler 中，不能因本卡未实现破坏前序单元测试收集。

```python
import json
import subprocess
import sys
from pathlib import Path
import pytest

@pytest.fixture
def probe(tmp_path):
    roots = []
    def invoke(case, **options):
        run_root = tmp_path / f"case-{len(roots):03d}"
        run_root.mkdir()
        roots.append(run_root)
        cmd = [sys.executable, "tests/support/scenario_driver.py", case,
               "--root", str(run_root), "--options",
               json.dumps(options, ensure_ascii=False)]
        completed = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            timeout=600, check=False)
        assert completed.returncode == 0, (
            f"QA infrastructure failed: {completed.returncode}; "
            f"stderr={completed.stderr[-2000:]}")
        result = json.loads(completed.stdout)
        assert isinstance(result, dict)
        return result
    return invoke
```

driver 未知 CASE 退出 2、handler/服务故障退出非零；预期的业务失败可正常返回 JSON，例如 `published=false`。上面 fixture 不把基础设施失败当成功负例。长时 soak 和安装重启不经 600 秒 fixture，以单独 runner、检查点与证据导入执行。

## 完整代表性翻译 fixture：tests/fixtures/translation/golden.jsonl

```jsonl
{"id":"en-zh-negation-number","direction":"en-zh","source":"Do not release when delta < -0.03.","approved_reference":"当差值小于 -0.03 时，禁止发布。","protected_spans":[],"required_facts":["prohibition","threshold=-0.03","comparison=less_than"],"ambiguities":[],"negative_candidate":"当差值小于 0.03 时允许发布。","expected_issues":["NEGATION_CHANGED","NUMBER_CHANGED"]}
{"id":"zh-en-code-and-condition","direction":"zh-en","source":"仅当 n >= 10 时运行；不要修改路径 C:\\data\\原始.csv。保留命令 python app.py --dry-run。","approved_reference":"Run only when n >= 10; do not modify the path C:\\data\\原始.csv. Preserve the command python app.py --dry-run.","protected_spans":["n >= 10","C:\\data\\原始.csv","python app.py --dry-run"],"required_facts":["necessary_condition","do_not_modify_path","preserve_command"],"ambiguities":[],"negative_candidate":"Run when n > 10 and modify the path C:\\data\\原始.csv.","expected_issues":["CONDITION_CHANGED","NEGATION_CHANGED","PROTECTED_SPAN_MISSING"]}
{"id":"en-zh-uncertainty-citation","direction":"en-zh","source":"The study did not establish causation [12]. The estimate was -0.03 (95% CI: -0.07 to 0.01).","approved_reference":"该研究并未确立因果关系[12]。估计值为 -0.03（95% 置信区间：-0.07 至 0.01）。","protected_spans":["[12]"],"required_facts":["causation_not_established","estimate=-0.03","confidence=95%","lower=-0.07","upper=0.01"],"ambiguities":[],"negative_candidate":"该研究证明了因果关系[12]，估计值为 0.03。","expected_issues":["CERTAINTY_CHANGED","NUMBER_CHANGED","FACT_MISSING"]}
```

上述文件是可阅读、可解析的示例起点；D043 扩展完整语料并由双语评审批准。受保护项的保护方式按片段类型定义，数字自然语言表达允许等义呈现，代码/路径必须逐字保留。第一例的数学表达可按实体和关系校验，不强迫中文句子照抄英文变量。

## 卡片执行与证据约定

所有卡按“读取输入 → 写负例 → 验证能复现 → 实现或修复 → 原例复验 → 保存证据 → 评审提交”执行。证据目录含构建、模型、时间、机器、seed、原始结果及哈希；正文和凭证遵循脱敏规则。卡片状态只在步骤和证据完成后由执行记录变更，本卷初始全为 planned。

### D041：扩展验收场景 driver 与可重复 fixtures

**目的/负责人：** 把已有开发测试扩展成能够驱动真实本地服务、导出可核验事实的系统验收装置。 / QA 自动化工程师。
**依赖/输入：** D007、D008、D009、D010、D012、D018、D040；D007 协议、D008 隔离存储、D010 状态机、D012 恢复、D018 公共投影及 D040 可运行构建。
**Files：** `tests/support/scenario_driver.py`；`tests/support/scenarios/registry.py`；`tests/support/manifest.py`；`tests/conftest.py`；`tests/acceptance/test_scenario_driver.py`；`tests/support/scenarios/driver_contract.py`。
**Interfaces：** CASE `driver_contract` 接收下方测试的 options，返回 `exit_code:int, service_pid:int, evidence_files:list[str], manifest_valid:bool, root_isolated:bool`；证据由真实运行产生。
**需求/预估：** R05/R12/R14；12 小时工程投入，外部执行和等待另计。

- [ ] 1. 创建 `tests/fixtures/acceptance/manifest.json`，固定 seed=4317、UTC 时间源、假适配器脚本版本及 UTF-8 编码。
- [ ] 2. 为每次 probe 分配 pytest 临时根目录，写入 task_id 与 run_id；拒绝已有非测试目录作为可写根。
- [ ] 3. 实现 `scenario_driver.py CASE --root DIR --options JSON`，stdout 只返回一个 JSON，诊断进入 stderr。
- [ ] 4. 在 registry 注册每个 CASE 的输入 schema、处理函数及结果 schema；未知 CASE 返回退出码 2。
- [ ] 5. 以参数数组启动真实本地服务，等待带超时的健康检查；记录真实 PID、端口与构建 ID。
- [ ] 6. 为外部模型安装可控测试适配器，只替换供应商边界，保留真实调度、数据库、文件和公开事件链。
- [ ] 7. 生成包含相对路径、字节数、SHA-256、构建、时间和 seed 的证据 manifest；拒绝越界路径。
- [ ] 8. 加入故意删掉成果文件的负例，确认 manifest 检查失败；装置导入失败单独归类为基础设施失败。
- [ ] 9. 运行本卡命令，确认成功场景含真实证据、未知 CASE 非零退出、所有子进程在 teardown 回收。
- [ ] 10. 保存失败前后记录，评审装置并提交本卡文件；后续卡逐个注册场景，不倒置前序开发测试依赖。

```python
def test_driver_requires_real_evidence(probe):
    r = probe("driver_contract", fault="deleted_evidence")
    assert r["service_pid"] > 0
    assert r["root_isolated"] is True
    assert r["manifest_valid"] is False
```
**运行：** `python -m pytest tests/acceptance/test_scenario_driver.py -q`。
**预期/负例：** 正常证据可复验；文件缺失不能出具通过结论；未知场景和未启动服务明确失败。 负例：直接返回硬编码 PASS、写入根目录外、stdout 混日志或装置失败被算成产品成功。
**证据：** `artifacts/qa/D041/driver-report.json`；`artifacts/qa/D041/evidence-manifest.json`。
**完成条件：** 装置可连续复跑三次，业务输出一致；每次根目录独立、进程清理完成、证据路径真实。
**失败回退：** 保留前序开发测试；停用不可信 CASE，修复装置后重跑，不改产品逻辑让伪装置通过。

### D042：需求覆盖矩阵与版本化回归集

**目的/负责人：** 让每个用户要求都关联可执行检查、证据与责任人，禁止用通过数量掩盖未覆盖要求。 / QA 负责人。
**依赖/输入：** D001、D041；D001 的 R01–R15 原文、翻译 T01–T20、D041 装置及 D001–D040 已有测试。
**Files：** `quality/requirements-matrix.json`；`quality/regression-manifest.json`；`tests/acceptance/test_requirement_coverage.py`；`tests/support/scenarios/requirement_coverage.py`。
**Interfaces：** CASE `requirement_coverage` 接收下方测试的 options，返回 `missing_requirements:list[str], unresolved_mandatory:list[str], release_complete:bool`；证据由真实运行产生。
**需求/预估：** R01/R02/R03/R04/R05/R06/R07/R08/R09/R10/R11/R12/R13/R14/R15；8 小时工程投入，外部执行和等待另计。

- [ ] 1. 建立 R01–R15 十五行需求记录，保存原文、强制等级和功能门槛/优化门槛分类。
- [ ] 2. 将翻译规格 T01–T20 逐一映射到 R03/R07/R08/R09/R10/R11/R12/R15。
- [ ] 3. 给每条测试赋唯一 case_id、路径、负责人、正反例类型及所需平台。
- [ ] 4. 区分自动检查、人工审核、真实供应商演练，不用同一假适配器结果替代三类证据。
- [ ] 5. 将 R01/R02 标记为优化目标验证，功能版发布不自动将其状态改为通过。
- [ ] 6. 给回归 manifest 固定版本和哈希；修改后创建新版本并写变更原因。
- [ ] 7. 删除一条 R09 强制场景作为负例，确认覆盖检查准确返回 R09。
- [ ] 8. 为 skipped、xfail、未采集人工证据设置未完成状态，拒绝折算成通过。
- [ ] 9. 运行覆盖命令并导出逐需求结果；对缺口创建带负责人和复验命令的缺陷记录。
- [ ] 10. 评审矩阵与用户原始需求的一致性，提交冻结版本及报告。

```python
def test_missing_mandatory_case_blocks_completion(probe):
    r = probe("requirement_coverage", remove_case="T13")
    assert "R09" in r["unresolved_mandatory"]
    assert r["release_complete"] is False
```
**运行：** `python -m pytest tests/acceptance/test_requirement_coverage.py -q`。
**预期/负例：** 十五项需求均有证据入口；删去强制来源检查立即产生缺口。 负例：测试不存在但填通过；把人工尚未完成、skip 或不支持入口描述为完整覆盖。
**证据：** `artifacts/qa/D042/coverage-report.json`；`quality/regression-manifest.json`。
**完成条件：** 每条强制要求都有实际可运行或可执行的验收步骤；R01/R02 仍保持独立判定。
**失败回退：** 恢复上一有效回归 manifest；新增要求暂列未完成，不删需求来使报告变绿。

### D043：双向翻译 golden、holdout 与人工复核

**目的/负责人：** 检验完整翻译、关键语义和双语文件忠实度，明确自动检查的边界。 / 双语领域评审＋翻译 QA。
**依赖/输入：** D026、D029、D030、D035、D041、D042；D026 路由、D029 翻译 QA、D030 输出、D035 文件配对和已冻结翻译规格。
**Files：** `tests/fixtures/translation/golden.jsonl`；`quality/translation-holdout-manifest.json`；`quality/translation-review-form.csv`；`tests/translation/test_release_corpus.py`；`tests/support/scenarios/translation_corpus.py`。
**Interfaces：** CASE `translation_corpus` 接收下方测试的 options，返回 `published:bool, issue_codes:list[str], reviewed_blocks:int, expected_blocks:int, translator_calls:int`；证据由真实运行产生。
**需求/预估：** R07/R08/R09/R10/R15；24 小时工程投入，外部执行和等待另计。

- [ ] 1. 建立 golden 60 个双向样本，编程、论文、文档各 20 个，覆盖否定、条件、数值、单位、代码和脚注。
- [ ] 2. 另建至少 60 个独立 holdout 样本，仅保管清单和哈希进入仓库，正文不进入 B 工作区或调参材料。
- [ ] 3. 为每例保存 source、approved_reference、protected_spans、required_facts、ambiguities 与严重度定义。
- [ ] 4. 把本文件代表性 JSONL 写入 golden，人工核对两个方向，不用回译作为金标准来源。
- [ ] 5. 指定两名双语领域评审盲审高影响块，对否定、范围、统计结论和数字逐项裁决。
- [ ] 6. 在结构层核对所有源块、脚注、表格、图注和附录覆盖；页数不同不判错，漏块必须判错。
- [ ] 7. 注入负号丢失、禁止变允许、未证明变已证明和占位串损坏，确认禁止发布。
- [ ] 8. 分别执行 Claude 首轮、追问、澄清和 GPT 原语言路径，GPT 强制翻译调用必须为零。
- [ ] 9. 运行测试并提交 golden 全通过、holdout 关键错误观察数、总样本量与人工分歧记录。
- [ ] 10. 对已发现误译修复并新增回归；holdout 已用于修复的样本移出未见集，补充新独立样本。

```python
def test_material_mistranslation_is_not_published(probe):
    r = probe("translation_corpus", case_id="en-zh-negation-number",
              candidate="当差值小于 0.03 时允许发布。")
    assert r["published"] is False
    assert {"NEGATION_CHANGED", "NUMBER_CHANGED"} <= set(r["issue_codes"])
```
**运行：** `python -m pytest tests/translation/test_release_corpus.py -q`。
**预期/负例：** 已知关键误译全部拦截；Claude 两方向忠实且完整；GPT 没有新增强制翻译。 负例：同一模型自评或回译一致被当作独立证明；60 例零错被宣传为未来绝对零错。
**证据：** `artifacts/qa/D043/translation-corpus-report.json`；`artifacts/qa/D043/human-adjudication.csv`。
**完成条件：** 提议门槛：golden 全通过、holdout 零观察到的关键错误、剩余问题有裁决；报告说明样本和漏检风险。
**失败回退：** 停用受影响术语/缓存版本；输入问题阻止 A 调用，输出问题保留英文内部稿但不成功发布。

### D044：A 独立基准与协作盲评冻结协议

**目的/负责人：** 建立可比较的质量基线，避免 A 自评、挑选成功样本或变更口径制造等效结论。 / 评测负责人＋独立领域评审。
**依赖/输入：** D038、D039、D040、D041、D042、D043；四类执行配置、D043 人工核对译文、实际模型/工具版本和相同交付要求。
**Files：** `quality/evaluation-protocol.md`；`quality/evaluation-registration.json`；`quality/holdout-manifest.json`；`tests/quality/test_protocol_freeze.py`；`tests/support/scenarios/evaluation_protocol.py`。
**Interfaces：** CASE `evaluation_protocol` 接收下方测试的 options，返回 `registration_valid:bool, reason_codes:list[str], test_set_disjoint:bool, blind_labels_valid:bool`；证据由真实运行产生。
**需求/预估：** R01/R02/R05/R15；24 小时工程投入，外部执行和等待另计。

- [ ] 1. 按代码、论文、文档、综合四领域与三档难度建立十二层任务池。
- [ ] 2. 每层先选 5 个独立试点估计方差；将这 60 个试点排除在正式 holdout 外。
- [ ] 3. 冻结正确性、完整性、推理、证据、一致性、可用性六维量表与关键缺陷定义。
- [ ] 4. 依据试点方差和预期检验功效登记各层正式样本量、一次分析时间和停止规则。
- [ ] 5. 预注册零质量折扣目标：配对质量差单侧 95% 下界不低于零，并冻结多重比较校正。
- [ ] 6. Claude 两路径使用经人工核对的等义英文需求与同一澄清结果；最终交付仍对照用户中文要求。
- [ ] 7. 确保双方资料、工具、格式和 A 完整英文定稿要求一致；预算策略和失败计入规则事先记录。
- [ ] 8. 随机化执行顺序与匿名标签，至少两位独立评审盲评，分歧由第三人裁决。
- [ ] 9. 将调参数据混入 holdout 作为负例，运行协议检查并验证注册哈希修改会失效。
- [ ] 10. 签署冻结记录；真实执行后追加结果不覆盖协议，改协议必须重登记并说明新适用范围。

```python
def test_holdout_contamination_invalidates_protocol(probe):
    r = probe("evaluation_protocol", fault="pilot_reused_in_holdout")
    assert r["registration_valid"] is False
    assert "HOLDOUT_CONTAMINATED" in r["reason_codes"]
```
**运行：** `python -m pytest tests/quality/test_protocol_freeze.py -q`。
**预期/负例：** 任务池、评审、译文和口径可复验；污染样本或事后换量表阻止出具资格结论。 负例：A 宣称自己同等智能、只展示成功个例、做到显著才停止、用 95% 当允许 5% 质量损失。
**证据：** `quality/evaluation-registration.json`；`artifacts/qa/D044/freeze-audit.json`。
**完成条件：** 正式样本量、置信方法、比较范围、盲评人员与全部失败处理规则已登记且不可覆盖。
**失败回退：** 撤销受污染批次资格，保留数据，改用新独立样本；不通过修改阈值追认旧结果。

### D045：真实 A/B 用量账本核对

**目的/负责人：** 把真实供应商计量、重试与文档定稿成本对齐到每个任务，杜绝漏算或重复累计。 / 后端工程师＋评测数据审核。
**依赖/输入：** D015、D040、D041、D044；D015 请求账本、实际适配器计量样本、D044 失败计入协议。
**Files：** `tests/fixtures/usage/provider-events.jsonl`；`tests/usage/test_ledger_reconciliation.py`；`quality/usage-reconciliation.csv`；`tests/support/scenarios/usage_reconciliation.py`。
**Interfaces：** CASE `usage_reconciliation` 接收下方测试的 options，返回 `a_tokens:int|None, b_tokens:int|None, reported_complete:bool, duplicate_count:int, source_kind:str, denominator:int`；证据由真实运行产生。
**需求/预估：** R02/R04/R14；12 小时工程投入，外部执行和等待另计。

- [ ] 1. 采集去密钥的真实单请求、会话累计、缓存、推理及 B 翻译/执行用量字段样本。
- [ ] 2. 逐提供方登记字段含义，明确是否已包含缓存/推理，禁止将父项子项再相加。
- [ ] 3. 把 120 token 的同请求事件重放两遍，只保留一条计费记录。
- [ ] 4. 把累计值 100、180、250 按会话归一，验证总量为 250 而非 530。
- [ ] 5. 加入失败、取消、质量返工、A 接管与完整英文定稿记录，逐项核对不被过滤。
- [ ] 6. 缺失用量写 null 并标 unknown；估算单列 source_kind=estimated，不能进入已证实节省结论。
- [ ] 7. 核对 A/B/翻译/执行明细之和与总体账本；服务发出的重复回调不得新增任务成本。
- [ ] 8. 令最终合格交付数为零，确认每次合格交付成本为空而非零或除零崩溃。
- [ ] 9. 运行核对测试，再对受控真实任务逐请求比对可用原始报告；差异必须说明计量口径。
- [ ] 10. 提交脱敏账本、差异表和计量版本；未能获取的提供方字段明确保留缺口。

```python
def test_cumulative_and_duplicate_usage_is_not_overcounted(probe):
    r = probe("usage_reconciliation", fault="cumulative_with_duplicate")
    assert r["a_tokens"] == 250
    assert r["duplicate_count"] == 1
    assert r["reported_complete"] is True
```
**运行：** `python -m pytest tests/usage/test_ledger_reconciliation.py -q`。
**预期/负例：** 重复与累计事件不多算；缺失不置零；所有真实尝试进入成本分子。 负例：只算成功请求、把会话累计逐轮相加、缓存再算一遍、把估算显示成供应商实测。
**证据：** `artifacts/qa/D045/usage-ledger.jsonl`；`quality/usage-reconciliation.csv`。
**完成条件：** 对有实际计量能力的路径实现逐请求可核对；无计量路径标记不具备节省验证资格。
**失败回退：** 保留原始事件并重建派生账本，暂停相关节省统计展示，不删除无法解释的记录。

### D046：联合质量/token 资格及保守路由

**目的/负责人：** 只有同时达到质量和用量证据门槛的特定配置，才启用并声明已验证优化。 / 评测负责人＋调度工程师。
**依赖/输入：** D038、D041、D044、D045；冻结协议、配对分数与重大缺陷、完整真实 A 用量、模型/领域/难度配置键。
**Files：** `quality/optimization-eligibility.json`；`services/orchestrator/app/quality/eligibility.py`；`tests/quality/test_optimization_gate.py`；`tests/support/scenarios/optimization_gate.py`。
**Interfaces：** CASE `optimization_gate` 接收下方测试的 options，返回 `eligible:bool, reason_codes:list[str], route_mode:str, product_goal_complete:bool`；证据由真实运行产生。
**需求/预估：** R01/R02/R03/R14；16 小时工程投入，外部执行和等待另计。

- [ ] 1. 定义资格键：A/B 实际版本、领域、难度、任务配置、翻译策略和评测协议哈希。
- [ ] 2. 在评估器中分别计算质量配对差及 A token 改善区间，按冻结的多重比较方法判定。
- [ ] 3. 要求每个必要质量维度下界≥0、无新增关键缺陷且 token 节省下界>0。
- [ ] 4. 用量不完整、样本不足、质量不确定或未经测试配置一律返回证据不足，不冒称已下降或等效。
- [ ] 5. 加入质量下降但节省 90% 的负例，必须拒绝优化资格。
- [ ] 6. 加入质量达标但 A 用量未减少的负例，功能可运行但用户优化目标未完成。
- [ ] 7. 未获资格配置采用 A 主导困难部分的保守路由，记录原因并保留用户选择。
- [ ] 8. 更换模型、术语/翻译策略或关键调度策略时使旧资格过期，安排对应范围复验。
- [ ] 9. 运行测试并生成按领域/难度分层报告；总体均值不能掩盖某领域质量损失。
- [ ] 10. 写清功能发布与优化目标结论两栏，只有完整证据支持的范围可表述达到用户目标。

```python
def test_saving_never_compensates_quality_loss(probe):
    r = probe("optimization_gate", quality_lower_bound=-0.2,
              saving_lower_bound=0.9, usage_complete=True)
    assert r["eligible"] is False
    assert r["route_mode"] == "a_led"
    assert r["product_goal_complete"] is False
```
**运行：** `python -m pytest tests/quality/test_optimization_gate.py -q`。
**预期/负例：** 负质量、高节省仍拒绝；A 主导可提供功能，但报告不把它冒充节省目标已达成。 负例：跨领域沿用资格、模型升级不复验、证据不足写同等质量、只凭平均节省率放行。
**证据：** `quality/optimization-eligibility.json`；`artifacts/qa/D046/joint-gate-report.json`。
**完成条件：** 每一已启用优化策略有可追踪资格；未知配置可回退；目标达成范围明确。
**失败回退：** 撤销问题资格并路由到 A 主导，保存原成果与用量；不静默换 A 提供商或降低质量门槛。

### D047：安全隔离、权限和日志泄漏验收

**目的/负责人：** 验证本地应用真实隔离、最小 IPC 与脱敏，防止文件和模型内容越权进入其他会话。 / 安全工程师＋桌面工程师。
**依赖/输入：** D008、D018、D021、D025、D037、D041；隔离工作区、公开事件白名单、Electron preload 与本地服务凭证接口。
**Files：** `tests/security/test_boundaries.py`；`tests/e2e/security-boundary.spec.ts`；`quality/security-review.md`；`tests/support/scenarios/security_boundary.py`。
**Interfaces：** CASE `security_boundary` 接收下方测试的 options，返回 `unauthorized_reads:list[str], secret_leaks:list[str], internal_public_events:list[str], executed_payloads:int`；证据由真实运行产生。
**需求/预估：** R11/R12/R13/R14；16 小时工程投入，外部执行和等待另计。

- [ ] 1. 建立 TASK_A_SECRET_47、API_CANARY_47、INTERNAL_ENGLISH_CANARY 三类不是真实密钥的测试标记。
- [ ] 2. 尝试跨会话同名路径、`..` 路径、符号链接/目录联接与编码路径，验证读取前检查真实解析边界。
- [ ] 3. 从不可信 renderer 调用未列入白名单的 IPC、任意命令和任意磁盘路径，验证拒绝且有脱敏记录。
- [ ] 4. 以外部 origin 和无本地令牌请求回环服务，验证 401/403，不把回环地址本身当认证。
- [ ] 5. 向 Markdown、PDF 链接和文档注释注入脚本及工具指令，确认内容无法提升工具权限。
- [ ] 6. 检查模型权限请求仍由受支持授权流程处理；测试模式不能关闭生产权限约束。
- [ ] 7. 收集 DOM、公开事件流、错误消息、日志、崩溃包与诊断导出，扫描三类 canary。
- [ ] 8. 对用户自己输入的英文代码作对照，确认不会因防内部泄漏误删合法内容。
- [ ] 9. 运行 Python 与 Electron 安全测试，人工复核浏览器配置、contextIsolation 与 renderer Node 权限。
- [ ] 10. 记录攻击路径、拦截证据和残余风险，所有密钥泄漏、跨任务读写、执行注入必须关闭后发布。

```python
def test_secret_and_cross_task_data_stay_private(probe):
    r = probe("security_boundary", fault="malicious_attachment_and_cross_task_path")
    assert r["unauthorized_reads"] == []
    assert r["secret_leaks"] == []
    assert r["internal_public_events"] == []
    assert r["executed_payloads"] == 0
```
**运行：** `python -m pytest tests/security/test_boundaries.py -q`；`npx playwright test tests/e2e/security-boundary.spec.ts`。
**预期/负例：** 越权行为被拒绝；内部英文与凭证不进入公开通道；合法英文附件仍可访问。 负例：仅用 CSS 隐藏内部内容、日志带授权头、字符串前缀验证路径、翻译附件指令变成系统命令。
**证据：** `artifacts/qa/D047/security-report.json`；`quality/security-review.md`。
**完成条件：** 已定义攻击面强制项全部通过；任何关键泄漏或越权缺陷未关闭则阻止功能发布。
**失败回退：** 撤回问题版本，关闭相应导出/预览能力并修复；凭证若真实暴露按事故程序处理，不在报告复写。

### D048：故障恢复、重复通知与取消乱序压力

**目的/负责人：** 在真实状态机上验证崩溃、未知远端状态、取消和晚到事件不导致重复调用或错误发布。 / 可靠性工程师。
**依赖/输入：** D010、D012、D018、D030、D035、D041；持久状态、恢复租约、公开投影、最终输出和原子文件配对实现。
**Files：** `tests/reliability/test_fault_matrix.py`；`tests/fixtures/reliability/event-orders.json`；`quality/recovery-matrix.csv`；`tests/support/scenarios/fault_matrix.py`。
**Interfaces：** CASE `fault_matrix` 接收下方测试的 options，返回 `external_starts:int, published_versions:list[str], task_state:str, cross_task_reads:list[str], orphan_pids:list[int]`；证据由真实运行产生。
**需求/预估：** R08/R09/R12/R14；16 小时工程投入，外部执行和等待另计。

- [ ] 1. 列出请求提交前后、远端启动后落盘前、译文写入、配对指针切换和公开事件发布断点。
- [ ] 2. 在每个断点通过测试钩子终止服务，重启真实服务并从数据库恢复。
- [ ] 3. 模拟远端已启动但本地超时，先查询外部状态；未知状态暂停，禁止盲目重发。
- [ ] 4. 重放 1,000 个重复通知，验证 attempt/request 去重且账本、聊天和文件不重复。
- [ ] 5. 生成固定 seed 的旧轮次、旧版本、晚到 PASS 与取消事件排列，验证只接受当前版本。
- [ ] 6. 模拟取消请求发出后远端仍运行，界面保持停止待确认；晚到成果不得自动发布。
- [ ] 7. 注入英文文件已写、中文文件未写和 Windows 文件占用，确认读者只见完整旧包或新包。
- [ ] 8. 用两个会话同名成果文件施压，检查零跨任务读写且进程树退出后无孤儿。
- [ ] 9. 运行故障矩阵测试并记录每个断点的数据库、事件及文件哈希快照。
- [ ] 10. 关闭复现缺陷并回归原 seed；对真实适配器不支持的取消/查询能力如实标注限制。

```python
def test_cancel_then_late_success_never_publishes(probe):
    r = probe("fault_matrix", fault="cancel_then_1000_duplicate_successes")
    assert r["task_state"] == "CANCELLED"
    assert r["published_versions"] == []
    assert r["external_starts"] == 1
    assert r["cross_task_reads"] == []
```
**运行：** `python -m pytest tests/reliability/test_fault_matrix.py -q`。
**预期/负例：** 取消、重复和旧结果不发布；未知状态不二次启动；恢复保持同一批准文件版本。 负例：进程退出码 0 当成功、取消按钮立即谎报停止、v3 英文/v2 中文混包、旧 PASS 批准新成果。
**证据：** `artifacts/qa/D048/fault-matrix.json`；`quality/recovery-matrix.csv`。
**完成条件：** 全部已列断点可复现且通过；未支持远端查询的路径有安全停等行为而非伪恢复。
**失败回退：** 禁用问题恢复捷径，暂停受影响任务，保留完整快照后修复；不可删除记录消除重复痕迹。

### D049：GUI 无障碍、输入法、多屏缩放与视觉验收

**目的/负责人：** 让中文聊天、文件交付和异常处理在 Windows 实际操作中可用，且始终隐藏内部过程。 / 桌面 QA＋可访问性评审。
**依赖/输入：** D021、D023、D024、D025、D036、D037、D041；DESIGN.md、真实 Electron 构建、聊天/设置/预览和公共事件流。
**Files：** `tests/e2e/accessibility.spec.ts`；`tests/e2e/ime-and-layout.spec.ts`；`quality/gui-manual-checks.csv`；`tests/acceptance/test_gui_evidence.py`；`tests/support/scenarios/gui_evidence.py`。
**Interfaces：** CASE `gui_evidence` 接收下方测试的 options，返回 `english_leaks:list[str], composition_submits:int, focus_lost:bool, unmet_checks:list[str]`；证据由真实运行产生。
**需求/预估：** R06/R08/R09/R10/R11；16 小时工程投入，外部执行和等待另计。

- [ ] 1. 固定 1440×900、1280×800、1024×768、浅色/深色和 100%/150%/200% 缩放截图矩阵。
- [ ] 2. 在双屏不同缩放比例之间移动窗口，检查输入框、菜单、预览和命中区域不偏移。
- [ ] 3. 使用 Windows 中文输入法实际输入并按 Enter 选词，确认 composing 时不发送；再按发送键仅提交一次。
- [ ] 4. 用纯键盘完成新建、附件、发送、停止、文件预览、双语保存与设置导航。
- [ ] 5. 用 Narrator 检查消息角色、文件语言、焦点顺序和完成通知，避免逐字重复播报。
- [ ] 6. 在 200% 字号/320 CSS px 视口测试正文重排，宽表和代码仅局部滚动。
- [ ] 7. 监听首次渲染、DOM mutation 与重连回放，内部英文 canary 任何时刻都不得进入聊天。
- [ ] 8. 覆盖等待、取消待确认、离线、翻译失败、文件失败及 GPT 原语言单文件情形。
- [ ] 9. 运行自动 E2E，并由人工签署输入法、屏幕阅读器与多屏三项实际证据。
- [ ] 10. 对比 DESIGN.md token、对比度、焦点与低动效要求，提交截图差异和缺陷关闭记录。

```python
def test_gui_does_not_submit_during_composition_or_leak(probe):
    r = probe("gui_evidence", fault="composition_and_internal_replay")
    assert r["composition_submits"] == 0
    assert r["english_leaks"] == []
    assert r["focus_lost"] is False
```
**运行：** `python -m pytest tests/acceptance/test_gui_evidence.py -q`；`npx playwright test tests/e2e/accessibility.spec.ts tests/e2e/ime-and-layout.spec.ts`。
**预期/负例：** 输入法不误发、键盘可完成核心操作、内部过程无瞬时泄漏、两语文件可明确辨识。 负例：自动脚本模拟键盘被冒充真实 IME/Narrator 测试；只拍最终截图漏掉英文瞬时闪现。
**证据：** `artifacts/qa/D049/screenshots/`；`quality/gui-manual-checks.csv`。
**完成条件：** 自动检查通过且三项人工证据齐全；无阻断中文输入、核心键盘操作或交付的缺陷。
**失败回退：** 恢复上个已审 UI 版本，保留稳定公开事件协议；问题预览可临时改安全保存但不能隐藏失败。

### D050：本地性能、持续运行与资源泄漏

**目的/负责人：** 确认单用户长任务运行保持交互响应，并把本地延迟与外部模型等待分开报告。 / 性能工程师。
**依赖/输入：** D040、D041、D048、D049；完整桌面构建、故障恢复能力、固定硬件与可控外部适配器延迟。
**Files：** `tests/performance/test_local_slo.py`；`tests/performance/soak_runner.py`；`quality/performance-profile.json`；`tests/support/scenarios/local_performance.py`。
**Interfaces：** CASE `local_performance` 接收下方测试的 options，返回 `input_echo_p95_ms:float, ui_ack_p95_ms:float, cancel_feedback_p95_ms:float, state_visible_p95_ms:float, cold_start_p95_ms:float, orphan_pids:list[int], latency_components:dict`；证据由真实运行产生。
**需求/预估：** R05/R06/R12；16 小时工程投入，外部执行和等待另计。

- [ ] 1. 登记 Windows 11、4 核/16 GB/SSD 的实测机器与电源模式，固定构建和后台应用清单。
- [ ] 2. 生成 10,000 条历史任务、100 MB 附件和 20 MB 日志场景，标注格式并验证可用能力。
- [ ] 3. 测量 30 次冷启动和至少 200 次本地输入确认；单独采集磁盘、UI、服务与模型等待。
- [ ] 4. 提议本地p95门槛：输入回显≤100ms、导航/发送确认≤200ms、取消反馈≤500ms、持久状态可见≤1s、冷启动≤3s，保存原始样本。
- [ ] 5. 用假外部模型进行 24 小时有界队列持续运行，每分钟一个短任务，避免无必要真实模型花费。
- [ ] 6. 每分钟采集进程树、RSS、句柄、线程、磁盘和待处理队列，区分主程序与第三方工具。
- [ ] 7. 预热后检查资源是否持续增长；提议主程序稳定峰值≤1GiB，持续增长异常必须定位并说明。
- [ ] 8. 执行 100 次窗口开关、取消、文件预览与断网恢复，退出后不得保留孤儿进程。
- [ ] 9. 运行快速 SLO 与单独的持续运行命令，记录 p50/p95、失败率和完整端到端耗时。
- [ ] 10. 修复瓶颈后重复受影响场景，保留前后原始样本；不得删除慢样本制造达标。

```python
def test_local_slo_and_process_cleanup(probe):
    r = probe("local_performance", history_tasks=10000, active_tasks=1)
    assert r["input_echo_p95_ms"] <= 100
    assert r["ui_ack_p95_ms"] <= 200
    assert r["cancel_feedback_p95_ms"] <= 500
    assert r["state_visible_p95_ms"] <= 1000
    assert r["cold_start_p95_ms"] <= 3000
    assert r["orphan_pids"] == []
```
**运行：** `python -m pytest tests/performance/test_local_slo.py -q`；`python tests/performance/soak_runner.py --hours 24 --seed 4317 --output artifacts/qa/D050/soak`。
**预期/负例：** 本地提议 SLO 达标且无未解释泄漏；外部延迟完整披露，不纳入本地可控上限承诺。 负例：只测空页面、隐藏模型翻译耗时、截去超时样本、以假适配器速度宣传真实模型响应。
**证据：** `artifacts/qa/D050/latency-samples.jsonl`；`artifacts/qa/D050/soak/summary.json`。
**完成条件：** 快速与 24 小时记录齐全；长任务、退出和恢复资源行为可解释，未达目标明确开缺陷。
**失败回退：** 关闭新增并行/缓存策略，恢复单任务队列；保留用户任务与文件，不通过无限扩大预算掩盖泄漏。

### D051：一致性备份、恢复与数据迁移

**目的/负责人：** 保证升级或损坏后能恢复任务、原件和译文的一致版本，凭证独立重新连接。 / 存储工程师＋可靠性 QA。
**依赖/输入：** D008、D012、D031、D035、D037、D041、D048；SQLite/WAL、不可变成果、配对 manifest、设置及已验证恢复状态机。
**Files：** `services/orchestrator/app/storage/backup.py`；`services/orchestrator/app/storage/restore.py`；`services/orchestrator/app/api/backups.py`；`services/orchestrator/app/api/application.py`；`apps/desktop/src/main/backup-ipc.ts`；`apps/desktop/src/preload/backup.ts`；`tests/storage/test_backup_restore.py`；`tests/storage/test_schema_migration.py`；`release/backup-restore-runbook.md`；`tests/support/scenarios/backup_restore.py`。
**Interfaces：** 产品引擎提供 `create_backup(data_root: Path, staging_root: Path) -> Path`、`validate_backup(bundle_path: Path) -> dict`、`restore_backup(bundle_path: Path, data_root: Path) -> dict`。注册 `POST /v1/backups` 与 `POST /v1/backups/{backup_id}/restore`；主进程文件对话框提供授权引用，renderer不能传任意磁盘路径。IPC `storage.backup.create` / `storage.backup.restore` 接入 D021 白名单及 D037 存储设置。CASE `backup_restore` 接收下方测试的 options，返回 `restored_hashes:dict, original_hashes:dict, restore_state:str, source_untouched:bool, credential_restored:bool`；证据由真实运行产生。
同时将上述IPC接入 `apps/desktop/src/main/ipc.ts`、`apps/desktop/src/preload/index.ts`、`apps/desktop/src/shared/desktop-bridge.ts` 和 `apps/desktop/src/renderer/settings/Storage.tsx`；不得只写孤立引擎测试而没有用户入口。
**需求/预估：** R09/R12/R13；24 小时工程投入，外部执行和等待另计。

- [ ] 1. 建立实际备份/恢复引擎、API与IPC，备份包括数据库一致快照、成果、manifest、schema和应用版本，排除凭证与临时缓存。
- [ ] 2. 使用 SQLite 备份接口并冻结对应成果引用集合；写入暂存包、校验、原子提交，禁止忽略 WAL 直接复制忙碌数据库。
- [ ] 3. 建立 vN−1 真实数据样本，包含中文路径、双语多格式包、暂停任务和多版本原件。
- [ ] 4. 逐文件核验哈希；恢复前暂停写入、在独立目录验证配对与引用，再受控切换并保留旧目录，设置页显示实际结果。
- [ ] 5. 注入缺失译文、损坏数据库、哈希不符与磁盘空间不足，恢复必须拒绝并保留原数据。
- [ ] 6. 在 schema 迁移每个提交点注入失败，验证旧数据可恢复且不留半迁移状态。
- [ ] 7. 设计回滚使用匹配旧 schema 的备份，禁止旧程序直接打开不兼容新 schema。
- [ ] 8. 恢复后让服务重建可派生索引；凭证缺失提示重新连接，不伪报已登录。
- [ ] 9. 运行恢复与迁移测试，记录总用时、备份体积、校验结果和故障回退步骤。
- [ ] 10. 提交运维手册并由非作者在隔离环境执行一次，确认无需依赖作者记忆。

```python
def test_corrupt_backup_preserves_current_data(probe):
    r = probe("backup_restore", fault="missing_chinese_artifact")
    assert r["restore_state"] == "REJECTED"
    assert r["source_untouched"] is True
    assert r["credential_restored"] is False
```
**运行：** `python -m pytest tests/storage/test_backup_restore.py tests/storage/test_schema_migration.py -q`。
**预期/负例：** 正确备份还原后哈希一致；损坏备份拒绝且原数据未改；迁移失败可回滚。 负例：只验证压缩包存在、漏 WAL、恢复英文和旧版中文混配、备份带密钥、旧程序强开新 schema。
**证据：** `artifacts/qa/D051/restore-report.json`；`release/backup-restore-runbook.md`。
**完成条件：** vN−1→vN 升级及匹配备份回滚完成，第三方执行者复验通过；无数据缺口。
**失败回退：** 停止写入并保留当前目录，恢复最近完整兼容备份；任何破坏性替换前先验证真实路径与备份。

### D052：Windows 安装、打包与代码签名

**目的/负责人：** 交付可安装、可验证发布者且正常启动本地服务的 Windows 11 x64 包。 / 发布工程师。
**依赖/输入：** D021、D024、D040、D047、D050、D051；可运行产品、能力报告、安全/性能证据、一致备份机制及已有合法签名条件。
**Files：** `apps/desktop/electron-builder.yml`；`release/build-windows.ps1`；`release/verify-installer.ps1`；`tests/release/test_windows_install.py`；`tests/support/scenarios/windows_install.py`。
**Interfaces：** CASE `windows_install` 接收下方测试的 options，返回 `install_ok:bool, publisher_valid:bool, backend_started:bool, user_files_preserved:bool, taskbar_windows:int`；证据由真实运行产生。
**需求/预估：** R03/R04/R06/R13；16 小时工程投入，外部执行和等待另计。

- [ ] 1. 固定安装包名 `AIBroker-Setup.exe`、产品 ID 与版本规则，打包桌面及 Python 本地运行时。
- [ ] 2. 将文件格式工具能力与许可证清单纳入包检测，不将开发机工具存在当成用户机器能力。
- [ ] 3. 以现有签名服务/证书完成签名，私钥留在安全存储；本任务不采购账号或提交个人资料。
- [ ] 4. 验证 Authenticode 状态、允许发布者、时间戳链和最终安装包 SHA-256。
- [ ] 5. 在干净非管理员 Windows 11 x64 账户安装，验证带空格/中文路径及首次启动。
- [ ] 6. 确认后台服务静默启动，无额外控制台窗口，退出后清理子进程且会话落盘。
- [ ] 7. 测试未连接 Claude/ZCode 时显示待连接，凭证与额度未知不能显示可用。
- [ ] 8. 测试升级安装与卸载保留用户数据的明确选择，不默认删除用户任务目录。
- [ ] 9. 运行安装测试及签名检查，提交干净环境录像、进程和文件结果。
- [ ] 10. 冻结签名候选包；缺少可信签名条件只允许明确标注的内部测试，不进入正式分发。

```python
def test_installer_has_valid_identity_and_backend(probe):
    r = probe("windows_install", fixture="signed_candidate")
    assert r["install_ok"] and r["publisher_valid"]
    assert r["backend_started"]
    assert r["taskbar_windows"] == 1
    assert r["user_files_preserved"]
```
**运行：** `python -m pytest tests/release/test_windows_install.py -q`；`powershell -NoProfile -File release/verify-installer.ps1 -Installer dist/AIBroker-Setup.exe`。
**预期/负例：** 发布者验证通过，普通用户可启动产品；用户数据保留，尚未配置连接显示真实状态。 负例：仅签了 EXE 未校验最终包、测试证书冒充可信发布、签名缺失仍对外正式发布。
**证据：** `artifacts/qa/D052/installation-report.json`；`artifacts/qa/D052/authenticode.json`。
**完成条件：** 候选包在干净机器安装/运行/卸载通过，签名链、发布者与哈希绑定最终字节。
**失败回退：** 保留上一签名版本，停止分发失败候选包；签名条件缺失登记发布阻塞，不重复采购。

### D053：签名更新与可恢复回滚

**目的/负责人：** 确保更新可验证、可中断、可恢复，安装失败时保持可用版本与兼容数据。 / 发布工程师＋存储工程师。
**依赖/输入：** D012、D051、D052；签名候选包、允许发布者列表、N−1 构建和匹配 schema 备份。
**Files：** `apps/desktop/src/main/updates.ts`；`release/update-channel.schema.json`；`tests/release/test_update_rollback.py`；`tests/support/scenarios/signed_update.py`。
**Interfaces：** CASE `signed_update` 接收下方测试的 options，返回 `update_state:str, active_version:str, previous_version:str, restored_schema:int, expected_schema:int`；证据由真实运行产生。
**需求/预估：** R12/R13；16 小时工程投入，外部执行和等待另计。

- [ ] 1. 定义签名更新 manifest，包含版本、渠道、最低兼容版本、包哈希和迁移要求。
- [ ] 2. 下载到暂存目录，先验证签名链、允许发布者和内容哈希，再允许安装。
- [ ] 3. 添加无效签名、未知发布者、篡改包、重放旧 manifest 和版本降级负例。
- [ ] 4. 区分授权回滚与网络下发降级；回滚只能使用预先可信且数据兼容的已保存版本。
- [ ] 5. 更新前保存一致性备份，活动任务先保存检查点并停止新增任务。
- [ ] 6. 在下载、解包、文件替换、迁移和首次健康检查阶段分别中断，验证可重试或回滚。
- [ ] 7. 首次启动健康检查失败自动进入受控回滚，恢复对应旧 schema 备份而非强开新库。
- [ ] 8. 记录当前版本、上一版本与恢复进度，用中文简单说明，不泄露签名或内部日志。
- [ ] 9. 运行更新负例与真实签名包演练，核对升级前后任务和文件哈希。
- [ ] 10. 发布更新回滚说明及已验证兼容窗口，超过窗口拒绝自动降级并说明恢复路径。

```python
def test_invalid_signature_keeps_working_install(probe):
    r = probe("signed_update", fault="invalid_publisher")
    assert r["update_state"] == "REJECTED"
    assert r["active_version"] == r["previous_version"]
    assert r["restored_schema"] == r["expected_schema"]
```
**运行：** `python -m pytest tests/release/test_update_rollback.py -q`。
**预期/负例：** 不可信更新拒绝；中断和迁移失败后仍可恢复上一可用版本及兼容数据。 负例：只校验下载 URL、不验包、更新失败丢任务、自动回滚程序但不回滚不兼容 schema。
**证据：** `artifacts/qa/D053/update-matrix.json`；`release/update-rollback-runbook.md`。
**完成条件：** 全部更新断点通过，普通用户能够恢复；受信签名和发布者验证不可被配置绕过。
**失败回退：** 关闭更新渠道当前候选项，保留本地工作版本，按已验证备份恢复；不可覆盖事故证据。

### D054：CI、锁定依赖、SBOM 与发布清单

**目的/负责人：** 把源提交、依赖、构建与验收证据绑定为可审计且可复现的候选发布。 / 构建与发布工程师。
**依赖/输入：** D002、D042、D047、D052、D053；工程脚本、回归 manifest、安全检查、签名安装和更新过程。
**Files：** `.github/workflows/windows-release.yml`；`release/release-manifest.schema.json`；`release/create-manifest.py`；`tests/release/test_release_manifest.py`；`tests/support/scenarios/release_manifest.py`。
**Interfaces：** CASE `release_manifest` 接收下方测试的 options，返回 `valid:bool, missing_evidence:list[str], skipped_mandatory:list[str], artifact_hash_matches:bool`；证据由真实运行产生。
**需求/预估：** R12/R13/R14；12 小时工程投入，外部执行和等待另计。

- [ ] 1. 锁定 Node、Python、npm 与打包器版本，提交 npm/Python 依赖锁文件和校验哈希。
- [ ] 2. 建立 Windows CI 顺序：静态检查、单元/契约、翻译/可靠性、安全、桌面 E2E、打包和签名校验。
- [ ] 3. 真实模型、人工无障碍和 24 小时持续运行结果以外部证据门槛接入，缺失不能写为自动通过。
- [ ] 4. 在隔离干净工作区构建两次，比较可重复部分；签名时间戳差异明确解释。
- [ ] 5. 生成 SPDX 或 CycloneDX SBOM，覆盖桌面、本地 Python、文档/OCR 工具与许可证。
- [ ] 6. 建立发布 manifest 绑定 commit、依赖锁哈希、包哈希、签名身份、测试与兼容 schema。
- [ ] 7. 加入缺 SBOM、跳过强制用例、包哈希变更和证据构建不匹配负例。
- [ ] 8. CI 凭证仅供签名步骤最小权限使用，PR 与不可信脚本不得读取发布密钥。
- [ ] 9. 运行 manifest 检查，生成完整候选清单和准确未完成项。
- [ ] 10. 把不可修改的证据包与候选包一起归档；后续新提交必须新建候选版本，不借用旧通过结论。

```python
def test_skipped_mandatory_check_blocks_release_manifest(probe):
    r = probe("release_manifest", fault="skipped_security_test")
    assert r["valid"] is False
    assert "security_boundary" in r["skipped_mandatory"]
```
**运行：** `python -m pytest tests/release/test_release_manifest.py -q`；`python release/create-manifest.py --candidate dist/AIBroker-Setup.exe --output artifacts/qa/D054/release-manifest.json`。
**预期/负例：** 候选字节和证据一一对应；强制检查 skipped、缺 SBOM 或旧构建证据均被拒绝。 负例：CI 总绿掩盖未跑真实测试、下载未锁版本依赖、候选修改后继续使用旧签名/报告。
**证据：** `artifacts/qa/D054/release-manifest.json`；`artifacts/qa/D054/sbom.json`。
**完成条件：** 所有候选产物可追踪到源码、依赖、签名和本构建验收证据；未完成项没有被吞掉。
**失败回退：** 取消本次候选发布资格，恢复上次锁文件与已知构建路径，重新构建与验证。

### D055：四类真实任务最终验收演练

**目的/负责人：** 在真实 Claude Code、ZCode GLM 与已就绪 GPT 入口上验证客户从提问到获取可用成果的完整旅程。 / 产品验收负责人＋领域专家。
**依赖/输入：** D040、D043、D045、D046、D048、D049、D051、D054；签名候选构建、真实能力矩阵、独立任务样本、文件渲染和证据收集。
**Files：** `quality/real-journeys.json`；`tests/acceptance/test_real_journey_evidence.py`；`release/customer-acceptance-record.md`；`tests/support/scenarios/real_journey_audit.py`。
**Interfaces：** CASE `real_journey_audit` 接收下方测试的 options，返回 `domains_passed:list[str], provenance_valid:bool, pairs_valid:bool, model_identity_verified:bool, all_required_entries_tested:bool`；证据由真实运行产生。
**需求/预估：** R01/R02/R03/R04/R05/R06/R07/R08/R09/R10/R11/R12/R14/R15；24 小时工程投入，外部执行和等待另计。

- [ ] 1. 选择四个真实任务：CSV 校验程序、基于给定论文的证据报告、需求方案文档、数据分析＋图表＋报告综合任务。
- [ ] 2. 为每个任务固定原始材料、限制、交付格式和真实验收标准，禁止提供未存在的论文或数据。
- [ ] 3. 在现有授权连接上运行 Claude＋ZCode，记录实际版本、GLM 选择、请求和完整用量。
- [ ] 4. 由中文输入完成首轮及一次需求纠正，核验 A 所收英文保留完整限制与最终中文回答一致。
- [ ] 5. 文档要求 MD、DOCX、PDF 两语配对，核查完整英文定稿确由 A 输出，B 不能代写冒充。
- [ ] 6. 编程成果运行正常与异常输入；论文核查来源支持；综合成果核查数据、代码、图表和结论依赖版本。
- [ ] 7. 演练一次取消/恢复和一次译文失败，确认用户只见真实中文提示、未完成包不发布。
- [ ] 8. 对已声明可用的 GPT 入口再跑原语言样本，证明零强制翻译；未就绪入口禁用并列未交付。
- [ ] 9. 收集客户视角截图、实际成果、人工审查、请求用量及公开消息记录，运行证据审计。
- [ ] 10. 签署四类功能验收与优化资格两张表；四个成功示例本身不证明统计质量等效或节省。

```python
def test_real_journey_evidence_covers_all_domains(probe):
    r = probe("real_journey_audit", evidence_set="candidate")
    assert set(r["domains_passed"]) == {"code", "paper", "document", "composite"}
    assert r["provenance_valid"] and r["pairs_valid"]
    assert r["model_identity_verified"] and r["all_required_entries_tested"]
```
**运行：** `python -m pytest tests/acceptance/test_real_journey_evidence.py -q`。
**预期/负例：** 四类真实成果可打开、可用、来源正确；所有声明可用入口已实测，主页面无内部泄漏。 负例：假适配器样本冒充真实 GLM；编造来源；凭四次演练宣传普遍同等智能；GPT 未测却标可用。
**证据：** `artifacts/qa/D055/real-journeys/`；`release/customer-acceptance-record.md`。
**完成条件：** 四类功能验收记录和成果齐全；优化结论仅引用 D046 对应范围，不由演练代替。
**失败回退：** 停止候选晋级，退回具体缺陷卡；保留已完成材料与用量，不在原任务上无界重跑。

### D056：受控试用与用户反馈闭环

**目的/负责人：** 通过受控真实使用发现桌面习惯、任务边界和长期工作中的缺陷，不隐藏已知限制。 / 产品负责人＋支持工程师。
**依赖/输入：** D049、D052、D054、D055；通过关键功能验收的签名试用包、用户手册、已知限制和脱敏诊断工具。
**Files：** `release/beta-guide.md`；`release/feedback-schema.json`；`release/beta-triage.csv`；`tests/release/test_feedback_bundle.py`；`tests/support/scenarios/feedback_bundle.py`。
**Interfaces：** CASE `feedback_bundle` 接收下方测试的 options，返回 `secret_leaks:list[str], contains_user_content:bool, explicit_content_opt_in:bool, reproducible_case:bool`；证据由真实运行产生。
**需求/预估：** R05/R06/R11/R12/R13；12 小时工程投入，外部执行和等待另计。

- [ ] 1. 定义首轮试用为既有目标用户的 5 个工作日观察窗口，时间是提议计划而非质量证明。
- [ ] 2. 编写首次连接、提问、双语保存、取消、恢复、备份和用量查看指南。
- [ ] 3. 列明已验证入口与尚未验证能力，说明质量/节省结论的领域范围与未完成目标。
- [ ] 4. 反馈表只收构建、场景、期望、实际、严重度、可复现步骤和可选择的脱敏诊断。
- [ ] 5. 默认不上传原始问题、附件和凭证；附带正文必须由用户针对本次反馈明确选择。
- [ ] 6. 建立 P0 数据丢失/泄漏/错误发布、P1 核心功能阻断、P2 一般功能、P3 展示问题分级。
- [ ] 7. 每日整理反馈并关联需求与可复现场景，重复问题合并但保留影响用户数。
- [ ] 8. 将每个已确认缺陷变成固定回归案例，修复后让报告者或替代评审复验。
- [ ] 9. 运行反馈包脱敏测试，确认正文默认缺席且 canary 密钥不出现。
- [ ] 10. 试用结束输出未关闭缺陷和通过场景；收集不足时延长或降级结论，不凭日历自动放行。

```python
def test_feedback_defaults_to_no_private_content(probe):
    r = probe("feedback_bundle", include_content=False)
    assert r["secret_leaks"] == []
    assert r["contains_user_content"] is False
    assert r["explicit_content_opt_in"] is False
```
**运行：** `python -m pytest tests/release/test_feedback_bundle.py -q`。
**预期/负例：** 反馈可复现且默认不包含用户正文/密钥；缺陷进入回归而非只修表面。 负例：自动上传完整聊天、忽略失败用户、试用到期即宣称稳定、只有满意度没有成果检查。
**证据：** `artifacts/qa/D056/feedback-audit.json`；`release/beta-triage.csv`。
**完成条件：** 观察窗口完成或限制明确，P0/P1 无未关闭项；每个修复有对应回归与复验记录。
**失败回退：** 暂停新试用分发并通知使用者相关限制，回退签名稳定包；不默认删除反馈原始证据。

### D057：正式发布评审与缺陷关闭

**目的/负责人：** 用完整证据决定软件是否可发布，并独立判断用户的质量与节省目标是否已达到。 / 发布负责人＋产品/QA 联合评审。
**依赖/输入：** D042、D046、D047、D048、D049、D050、D051、D052、D053、D054、D055、D056；本候选构建全部验收、试用缺陷、签名更新和优化资格报告。
**Files：** `release/release-checklist.md`；`release/release-decision.json`；`release/known-limitations.md`；`tests/release/test_go_no_go.py`；`tests/support/scenarios/release_decision.py`。
**Interfaces：** CASE `release_decision` 接收下方测试的 options，返回 `functional_release:bool, optimization_goal_met:bool, blocked_reasons:list[str], qualified_scope:list[str]`；证据由真实运行产生。
**需求/预估：** R01/R02/R03/R04/R05/R06/R07/R08/R09/R10/R11/R12/R13/R14/R15；8 小时工程投入，外部执行和等待另计。

- [ ] 1. 冻结候选构建和所有证据哈希，停止将未经复验的新提交混入本轮评审。
- [ ] 2. 逐 R01–R15 审查负责人、结果、未测范围和证据路径，避免只有汇总勾选。
- [ ] 3. 要求无未关闭数据丢失、跨会话、凭证泄漏、假成功、内部英文泄漏、错误配对等关键缺陷。
- [ ] 4. 核对真实接入、四领域成果、人工翻译/无障碍、性能、备份恢复与签名更新证据。
- [ ] 5. 确认发布者身份、SBOM、依赖锁、许可证和实际安装包哈希一致。
- [ ] 6. 把 functional_release 与 optimization_goal_met 分为独立布尔值并分别填写依据。
- [ ] 7. 若只达到功能门槛，清楚记录用户整体优化目标未完成及后续评测任务；不得称项目完全达成。
- [ ] 8. 用缺失签名证据和未获 token 改善资格负例测试决策器，验证两类门槛不会混淆。
- [ ] 9. 由产品、QA、发布三方签署 go/no-go 与可声明范围，不允许发布者单人覆写硬性失败。
- [ ] 10. 生成版本说明、已知限制、回滚入口和证据索引；实际分发按用户授权执行。

```python
def test_functional_release_is_not_optimization_completion(probe):
    r = probe("release_decision", functional_checks=True, optimization_eligible=False)
    assert r["functional_release"] is True
    assert r["optimization_goal_met"] is False
    assert r["qualified_scope"] == []
```
**运行：** `python -m pytest tests/release/test_go_no_go.py -q`。
**预期/负例：** 功能可发布不等于优化目标完成；任何关键功能/安全证据缺失阻止正式发布。 负例：A 主导 fallback 软件可用就宣布省 token 目标完成；把需人工审核项改成 N/A 避免阻塞。
**证据：** `release/release-decision.json`；`release/release-checklist.md`。
**完成条件：** 决策可追溯且两类结论清晰；签字、限制、回滚和候选包一致，未达目标保持开放。
**失败回退：** 维持最后已验证版本，撤销当前候选发布，退回相应失败卡并重新冻结证据。

### D058：日常监控、日志保留与术语维护

**目的/负责人：** 保持本地产品可诊断、可恢复和翻译术语一致，避免日常维护扩大隐私暴露。 / 维护负责人。
**依赖/输入：** D015、D029、D037、D045、D047、D051、D057；用量账本、术语版本、独立设置页、脱敏日志和备份机制。
**Files：** `ops/operations-runbook.md`；`ops/retention-policy.json`；`ops/glossary-change-log.jsonl`；`tests/operations/test_retention_glossary.py`；`tests/support/scenarios/retention_glossary.py`。
**Interfaces：** CASE `retention_glossary` 接收下方测试的 options，返回 `deleted_active_evidence:bool, secret_leaks:list[str], cache_reused_after_glossary_change:bool, history_preserved:bool`；证据由真实运行产生。
**需求/预估：** R02/R07/R08/R12/R14/R15；12 小时工程投入，外部执行和等待另计。

- [ ] 1. 定义本地健康指标：任务成功/失败、阻塞、恢复、翻译拒绝、队列、磁盘和真实用量完整率。
- [ ] 2. 设置异常阈值并按基线解释；只在独立诊断/设置页展示，不把内部流程刷进聊天。
- [ ] 3. 提议诊断日志保留 14 天、运行事件 90 天、用量汇总 365 天；用户会话与交付物默认保留至用户删除。
- [ ] 4. 保留策略对活跃任务、未处理事故和备份依赖设置保护，不按文件年龄直接删除仍引用成果。
- [ ] 5. 每日检查最近备份完整性，每月在隔离目录执行一次实际恢复；记录日期与结果。
- [ ] 6. 术语变更保存旧值、新值、领域、理由和评审人，关键专业术语需双语复核。
- [ ] 7. 术语或策略版本变化使相关翻译缓存失效，旧交付文件不原地覆盖；重译形成新版本。
- [ ] 8. 默认诊断导出脱敏且不含原文正文，按用户显式选择才附带选定内容。
- [ ] 9. 运行保留/缓存回归，确认活跃证据不删、历史不误删、变更后缓存不误用。
- [ ] 10. 建立每周维护记录和待办，供应商版本改变后转入资格复验流程，不凭无报错延续结论。

```python
def test_retention_and_glossary_protect_live_work(probe):
    r = probe("retention_glossary", fault="expired_log_with_active_evidence")
    assert r["deleted_active_evidence"] is False
    assert r["secret_leaks"] == []
    assert r["cache_reused_after_glossary_change"] is False
    assert r["history_preserved"] is True
```
**运行：** `python -m pytest tests/operations/test_retention_glossary.py -q`。
**预期/负例：** 日志可控增长、活跃成果保留、术语变更不污染缓存；维护信息不出现在主聊天。 负例：清理日志连带删成果、保存正文无限导出、更新术语后仍使用旧译文缓存、监控值缺失写零。
**证据：** `artifacts/qa/D058/retention-report.json`；`ops/operations-runbook.md`。
**完成条件：** 维护频率、负责人和保留默认值可配置且经过回归；恢复演练有实际证据。
**失败回退：** 停止清理作业，恢复最近完整备份；撤销有问题术语版本并使其派生缓存失效。

### D059：事故响应、模型退化与优化回滚

**目的/负责人：** 发现质量下降、误译、泄漏或版本故障时快速止损，并在有证据后恢复优化。 / 事故负责人＋领域/安全评审。
**依赖/输入：** D046、D047、D048、D051、D053、D057、D058；优化资格表、运行监控、签名回滚、备份恢复和发布严重度标准。
**Files：** `ops/incident-runbook.md`；`ops/incident-template.md`；`tests/operations/test_incident_rollback.py`；`tests/support/scenarios/incident_rollback.py`。
**Interfaces：** CASE `incident_rollback` 接收下方测试的 options，返回 `optimization_disabled:bool, affected_publication_stopped:bool, provider_switched:bool, evidence_preserved:bool, resume_requires_requalification:bool`；证据由真实运行产生。
**需求/预估：** R01/R02/R03/R07/R08/R09/R12/R13/R15；12 小时工程投入，外部执行和等待另计。

- [ ] 1. 定义事故触发：关键误译、错误文件配对、证据/用量缺失、跨任务泄漏、模型身份或质量退化。
- [ ] 2. 发现后立即冻结受影响发布或优化配置，保留正常无关任务；不静默切换到其他 A。
- [ ] 3. 保存构建、模型、术语、任务版本、脱敏事件与原件哈希，锁定证据免受保留清理。
- [ ] 4. 评估影响范围和已交付文件，形成中文可理解的影响说明与用户需要采取的动作。
- [ ] 5. 质量/token 优化退化时退回 A 主导；翻译本身有关键缺陷时阻止交付，不能用 A 主导掩盖翻译故障。
- [ ] 6. 数据或程序问题按签名回滚与兼容备份流程处理，先验证备份后恢复，保留原现场。
- [ ] 7. 进行根因分析并新增最小复现，区分供应商变更、上下文缺口、策略回归与装置误报。
- [ ] 8. 在新独立样本上重新验证受影响资格，不能用事故样本修复通过就恢复所有领域结论。
- [ ] 9. 运行一次桌面演练：模型版本变化＋误译 canary，确认止发、保全与禁止自动复启。
- [ ] 10. 完成复盘：时间线、影响、修复、验证、负责人和预防项；明确恢复由证据决定。

```python
def test_incident_disables_optimization_without_hidden_provider_switch(probe):
    r = probe("incident_rollback", fault="critical_translation_after_model_change")
    assert r["optimization_disabled"] and r["affected_publication_stopped"]
    assert r["provider_switched"] is False
    assert r["evidence_preserved"] and r["resume_requires_requalification"]
```
**运行：** `python -m pytest tests/operations/test_incident_rollback.py -q`。
**预期/负例：** 事故范围及时止发、证据保留、无静默换模型；修复后重新取得对应资格才恢复优化。 负例：仅调高重试次数、隐藏用户错误、A 主导被误当翻译修复、清日志销毁现场、自动全域复启。
**证据：** `artifacts/qa/D059/incident-drill.json`；`ops/incident-runbook.md`。
**完成条件：** 演练完整走通检测、隔离、通知准备、恢复和复验；每步明确责任与证据。
**失败回退：** 持续停用受影响能力并使用已验证兼容版本；无法安全恢复则保留数据并明确阻塞。

### D060：终验交接与长期维护

**目的/负责人：** 交付可安装软件、源代码、完整证据和维护办法，并如实结清用户目标与未完成事项。 / 项目负责人＋用户验收代表。
**依赖/输入：** D042、D044、D045、D046、D051、D052、D053、D054、D055、D056、D057、D058、D059；正式候选、R01–R15 矩阵、质量/token 资格、四类样例、运行与事故手册。
**Files：** `release/final-handover.md`；`release/final-acceptance.json`；`ops/maintenance-calendar.md`；`tests/release/test_final_handover.py`；`tests/support/scenarios/final_handover.py`。
**Interfaces：** CASE `final_handover` 接收下方测试的 options，返回 `files_complete:bool, evidence_valid:bool, functional_complete:bool, optimization_complete:bool, overall_goal_complete:bool, open_items:list[str]`；证据由真实运行产生。
**需求/预估：** R01/R02/R03/R04/R05/R06/R07/R08/R09/R10/R11/R12/R13/R14/R15；8 小时工程投入，外部执行和等待另计。

- [ ] 1. 汇总安装包、签名/哈希、源码提交、锁依赖、SBOM、许可证和构建复现步骤。
- [ ] 2. 交付使用指南、连接能力表、双语样例、备份恢复、更新回滚和事故手册。
- [ ] 3. 由未参与开发的人按指南在干净 Windows 环境完成安装、连接、提问和两语文件保存。
- [ ] 4. 逐 R01–R15 给出通过、未通过、未验证及证据，不能用百分比进度替代缺口。
- [ ] 5. 核对所有报告来自最终构建与实际模型版本，过期资格单列并安排复验。
- [ ] 6. 分别签署功能完成和 A 质量＋token 优化完成；任何必要优化证据缺失时整体目标保持未完成。
- [ ] 7. 将未完成项写成具体责任人、下一动作、验收证据及预计工作量，保留数据不改写历史。
- [ ] 8. 安排每周健康检查、每月恢复演练、季度依赖/安全复查和模型变更后的专项评测。
- [ ] 9. 运行交接完整性测试并验证证据链接与文件哈希，提供用户可离线阅读的索引。
- [ ] 10. 签署最终交接记录；只有功能与优化目标在约定适用范围均获证据支持时，才宣布整体目标完成。

```python
def test_handover_keeps_unproven_optimization_open(probe):
    r = probe("final_handover", functional_complete=True, optimization_complete=False)
    assert r["functional_complete"] is True
    assert r["overall_goal_complete"] is False
    assert "optimization_evidence" in r["open_items"]
```
**运行：** `python -m pytest tests/release/test_final_handover.py -q`。
**预期/负例：** 交接文件完整、证据可离线核对；功能完成与整体目标完成区分清楚。 负例：把所有代码已写完当目标完成、未知节省写零成本、删掉未测领域、旧报告冒充最终版。
**证据：** `release/final-acceptance.json`；`release/final-handover.md`。
**完成条件：** 安装、使用、维护可由他人复现；全部目标有证据或明确未完成，最终结论与事实一致。
**失败回退：** 不签总体完成，按缺口退回对应卡；保持已验收功能可用并继续有界补齐未完成目标。


