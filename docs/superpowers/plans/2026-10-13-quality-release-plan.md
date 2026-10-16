# 工业化验收与发布 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可独立复验的质量、翻译、可靠性和 Windows 发布证据，使质量优先于节省 A token 的目标能够被检验。

**Architecture:** QA 驱动真实本地调度服务、隔离工作区和桌面；可控假适配器用于故障复现，真实 Claude Code/ZCode/GPT 接入另设能力门槛。测试接口仅存在于 tests/support，不向产品公开。验收报告绑定构建、配置、模型、样本及成果版本。

**Tech Stack:** Electron + React + TypeScript、Python FastAPI、SQLite；pytest 业务/契约测试、Playwright Electron E2E、PowerShell Windows 发布校验。

## Global Constraints

- 本文是待实施的 QA 子计划；命令、阈值及期望结果均为提议，未运行产品测试，不代表已经通过。
- 优先级：A 级质量目标 → 尽量减少 A 总 token → 耗时和 B 用量；不授权质量折扣，不预设节省比例。
- A 主用 Claude Code，可选 GPT；B 为 ZCode 中的 GLM，真实入口和会话能力须在安装版本上实测。
- Claude 输入含追问全部中→英，输出及追问英→中；英文内部过程不出现在聊天界面。GPT 分支零强制翻译。
- Claude 文档模式必须由 A 亲自产出完整英文定稿；B 翻译中文，两个文档配对交付，不能拿 B 代写原件冒充 A 输出。
- GUI 仅在此计划验收；业务及 GUI 实现由对应子计划负责。内部状态、提示词、工具事件和英文模型输出不能直接进入聊天。
- 本地单用户负载；不引入云多租户。真实模型测试使用受控任务，记录使用量，失败不标成功。
- 所有示例相对路径均以 `C:/Users/asd15/Documents/ChatGPT/ai` 为根；使用隔离临时目录，发布凭证不写测试样本或日志。

## 文件与需求追踪

| QA 编号 | 需求编号 | 预定文件与独立验收成果 |
| --- | --- | --- |
| QA-01 | R01/R02/R05/R14 | `tests/quality/test_baseline_gate.py`；`quality/evaluation-protocol.md`；基准及用量资格报告 |
| QA-02 | R03/R04/R07/R08/R10/R15 | `tests/translation/test_routes.py`、`test_semantics.py`；冻结语料及翻译证据 |
| QA-03 | R09 | `tests/artifacts/test_provenance_publish.py`；真实原件与原子配对证据 |
| QA-04 | R06/R11 | `tests/e2e/chat-boundary.spec.ts`；中文聊天截图、可访问性及 DOM 证据 |
| QA-05 | R12 | `tests/reliability/test_recovery.py`；故障恢复、去重、取消和隔离证据 |
| QA-06 | R03/R04/R14 | `tests/contracts/test_connectivity_usage.py`；真实能力矩阵与用量账本 |
| QA-07 | R13 | `tests/release/test_windows_delivery.py`；签名、更新及数据恢复证据 |
| QA-08 | R01/R02/R05/R06/R13 | `tests/performance/test_local_slo.py`；`release/release-checklist.md`；功能发布报告 |

共享测试文件：`tests/support/scenario_driver.py`、`tests/conftest.py`、`tests/fixtures/translation/golden.jsonl`、`quality/holdout-manifest.json`、`artifacts/qa/`。holdout 正文存在评测保管目录，不进入 B 工作区和提示词。

## 测试接口约定

`scenario_driver.py CASE --root DIR --options JSON` 是测试进程入口：启动真实本地服务、驱动指定场景、导出可独立核验的文件/事件/数据库快照，stdout 只输出一个 JSON 对象。未知 CASE、装置故障或缺少产品构建退出非零；预期业务失败仍输出实际失败状态。不能用硬编码“通过”字段替代服务运行。各任务定义其 CASE 和返回字段；场景注册代码与产品调用由对应实施者同步完成，不属于公开 API。

在 `tests/conftest.py` 建立完整通用调用装置；所有 pytest 示例均可在场景实现后执行：

```python
import json
import subprocess
import sys
import pytest

@pytest.fixture
def probe(tmp_path):
    def run(case, **options):
        command = [sys.executable, "tests/support/scenario_driver.py", case,
                   "--root", str(tmp_path), "--options", json.dumps(options)]
        result = subprocess.run(command, capture_output=True, text=True,
                                encoding="utf-8", timeout=600, check=True)
        return json.loads(result.stdout)
    return run
```

每项执行顺序均为：先建立反例并证明失败 → 交由负责模块修复 → 原反例通过 → 保存原始证据和提交。缺少装置导致的失败只能说明装置未就绪，不能充当业务反例。

### Task 1：建立质量与节省联合评估（QA-01）

**Files:** 新建 `tests/quality/test_baseline_gate.py`、`quality/evaluation-protocol.md`、`quality/holdout-manifest.json`。
**Interfaces:** CASE `quality_gate` 接受 `quality_deltas`、`a_tokens`、`baseline_tokens`；输出 `optimization_eligible`、`reason_codes`。真实评估另输出逐任务配对分数、盲评记录、原始成果哈希及用量账本。

- [ ] 冻结四类任务（代码、论文、文档、综合）× 三档难度、量表和首次样本划分。提议每格先做 5 个独立试点估计方差，再预注册正式样本量；试点不进入 holdout。执行顺序随机，模型/版本、资料、工具、交付范围及预算规则保持可比；至少两位独立评审盲评并裁决分歧。
- [ ] 量表分别覆盖正确性、约束完整性、核心推理、证据、整体一致性和最终可用性。代码运行与异常行为、论文来源与统计、文档受众与导出、综合任务依赖一致性分别设硬门槛；抽样审查不得冒称完整审稿。测试通过、A 自评分及表达流畅不能替代这些项目。
- [ ] 预注册零质量折扣目标：各领域/难度的关键维度与总评分比较 A 独立完成基准；优化资格要求配对差值单侧 95% 置信下界 ≥ 0、无新增关键缺陷，同时 A token 节省率置信下界 > 0。95% 是统计置信水平，不是允许质量剩下 95%；冻结比较与多重检验处理，不能试到显著才停止。
- [ ] 纳入所有失败、重试、返修、取消、升级 A、翻译修复和接管用量。A 总 token / 最终合格交付数的分子包含未交付任务；分母为零时指标不可计算。分别报告 A、B 翻译、B 执行和总成本，不能把失败或翻译消耗移出统计。缓存/推理子项按提供方口径归一，禁止重复计数。
- [ ] Claude 双向翻译和 GPT 无强制翻译各自分层评测；相同交付范围比较，双语文档原件与 A 必须亲自产出的完整英文定稿成本不能省略。无法获得真实用量时标“估算”，不据此宣称已证实节省。
- [ ] 将任务质量与翻译忠实度分别评分，再评完整用户交付。Claude 基准使用人工核对的等义英文需求和相同证据范围，避免把 B 输入误译混同于 A 的能力差异；最终中文版仍须与原始中文任务核对。源文含歧义时，基准与协作路径使用同一澄清结果。

```python
def test_token_saving_cannot_buy_quality_loss(probe):
    r = probe("quality_gate", quality_deltas=[-1] * 30,
              a_tokens=[100] * 30, baseline_tokens=[1000] * 30)
    assert r["optimization_eligible"] is False
    assert "QUALITY_BELOW_BASELINE" in r["reason_codes"]
```

- [ ] 执行 `python -m pytest tests/quality/test_baseline_gate.py -q`；预期负质量案例不获资格、零样本和用量未知不能宣称节省。真实 holdout 通过后才生成对应范围的优化资格；无显著节省或证据不足的领域使用 A 主导配置发布并披露未证实节省，不无限阻塞软件发布。
- [ ] 提交测试、冻结协议和评估报告；不得把“尚未评测”填写成“等效”。

### Task 2：验收双向翻译及 GPT 分支（QA-02）

**Files:** 新建 `tests/translation/test_routes.py`、`tests/translation/test_semantics.py`、`tests/fixtures/translation/golden.jsonl`。
**Interfaces:** CASE `translation_route` 接受 `provider`、`turns`；输出按请求记录的 `translation_directions`、`a_received`、`chat_messages`。CASE `translation_semantics` 接受 `source`、`candidate`；输出 `publishable`、`issues`。

- [ ] golden 覆盖否定/例外/量词、数字符号、小数与区间、百分比/置信区间、单位、日期、公式、代码及路径、引用编号、表格、专有名词和不确定措辞；包含“禁止”误成“允许”、“未证明”误成“已证明”、`-0.03` 变成 `0.03` 等反例。保持代码等不可翻译片段逐字一致，不能把“输入全译”实现为破坏代码或原始数据。
- [ ] 保存原件、翻译、术语表版本、自动差异和人工语义裁决；golden 可用于修复，holdout 独立保管、冻结哈希、禁止用于提示调参。B 回译仅作辅助，不能用同一模型自检证明等价。歧义不得补造；无法消歧即请求确认并停止依赖该含义的操作。

```python
def test_claude_followups_translate_both_directions(probe):
    r = probe("translation_route", provider="claude", turns=2)
    assert r["translation_directions"] == ["zh-en", "en-zh"] * 2

def test_gpt_does_not_force_translation(probe):
    r = probe("translation_route", provider="gpt", turns=2)
    assert r["translation_directions"] == []

def test_negation_and_signed_number_block_publication(probe):
    r = probe("translation_semantics", source="Do not release when delta < -0.03.",
              candidate="当差值小于 0.03 时允许发布。")
    assert r["publishable"] is False
    assert {"NEGATION_CHANGED", "NUMBER_CHANGED"} <= set(r["issues"])
```

- [ ] 执行 `python -m pytest tests/translation -q`；预期每轮及追问均经过指定路由，GPT 不因公共中间件触发强制翻译；关键误译不发布。另对每轮 A 实际接收材料和 GUI 实际消息逐项核验，不能只数调用次数；连接报错也不得退回展示英文原文。
- [ ] 提议发布门槛：冻结 golden 全部通过，holdout 中零观察到的关键语义错误且剩余问题完成裁决；记录样本量及漏检风险，不能声称绝对无误。提交测试和译文审查记录。

### Task 3：核验真实 A 来源与配对原子发布（QA-03）

**Files:** 新建 `tests/artifacts/test_provenance_publish.py`。
**Interfaces:** CASE `artifact_publication` 接受 `fault`；先发布完整 v1，再尝试 v2；输出 `source_actor`、`raw_a_output`、`english_original`、`visible_manifests`、`artifact_paths`。`raw_a_output` 是 C 捕获的 A 完整文档正文文件，非混入工具事件的日志；路径均指隔离目录真实文件。manifest 每项含角色、版本和 sha256。

- [ ] 原件由 C 从真实 A 会话/请求捕获，绑定输入、完整英文定稿、模型、会话、请求、轮次及哈希；哈希证明内容未变，不单独证明作者身份。B 摘要、B 代写后 A 仅回复“通过”、伪造元数据均不满足原件条件。
- [ ] 逐处注入写原件中断、译文中断、校验失败、发布指针切换中断、Windows 文件被占用；先写同卷暂存版本并验证完整配对，再原子切换可见 manifest。读者只能见旧完整版本或新完整版本；目录里存在单个文件不等于已发布。

```python
from pathlib import Path

def test_interrupted_pair_never_becomes_visible(probe):
    r = probe("artifact_publication", fault="after_english_before_chinese")
    assert r["source_actor"] == "A"
    assert Path(r["english_original"]).read_bytes() == Path(r["raw_a_output"]).read_bytes()
    assert r["visible_manifests"]
    assert all(m["pair_versions"] == ["v1", "v1"] for m in r["visible_manifests"])
    assert all(set(m["roles"]) == {"english_original", "chinese_translation"}
               and len(set(m["pair_versions"])) == 1 for m in r["visible_manifests"])
```

- [ ] 执行 `python -m pytest tests/artifacts/test_provenance_publish.py -q`；预期所有可见 manifest 的文件实际存在、哈希匹配且配对一致；原件版本改变后旧译文和批准失效。加入伪造 A 原件负例，预期拒绝交付。提交断电位置矩阵及文件证据。

### Task 4：仅验收聊天 GUI 边界（QA-04）

**Files:** 新建 `tests/e2e/chat-boundary.spec.ts`，测试装置 `tests/support/electron-fixture.ts`。
**Interfaces:** fixture 导出 Playwright `test`/`expect`，提供 `chatPage` 和 `emitInternal(event: {type: string, text: string})`；后者通过测试进程向真实服务注入事件，不公开生产端点。`emitInternal` 必须等待服务端投影处理完成及相关客户端渲染队列排空后返回，避免事件未到达就判定“无泄漏”。聊天容器 `data-testid="chat-messages"`，中文连接错误区域 `data-testid="connection-error"`。

- [ ] 覆盖首次消息、追问、流式增量、重连回放、翻译失败、审批缺口及错误提示；在渲染前过滤原始内部事件，不能短暂闪现后删除。测试捕获 DOM mutation、可访问性树与截图，不只检查最终画面。

```typescript
import { test, expect } from "../support/electron-fixture";
test("内部英文不进入聊天", async ({ chatPage, emitInternal }) => {
  await chatPage.evaluate(() => {
    const leaks: string[] = [];
    Object.assign(window, { qaLeaks: leaks });
    new MutationObserver(records => {
      for (const r of records) {
        const text = [r.target.textContent, ...Array.from(r.addedNodes, n => n.textContent)].join("");
        if (text.includes("INTERNAL_ENGLISH_CANARY")) leaks.push(text);
      }
    }).observe(document.querySelector('[data-testid="chat-messages"]')!,
               { childList: true, subtree: true, characterData: true });
  });
  await emitInternal({ type: "tool.delta", text: "INTERNAL_ENGLISH_CANARY" });
  await emitInternal({ type: "model.delta", text: "INTERNAL_ENGLISH_CANARY" });
  await expect(chatPage.getByTestId("chat-messages")).not.toContainText("INTERNAL_ENGLISH_CANARY");
  await expect(chatPage.getByTestId("chat-messages")).not.toContainText("tool.delta");
  expect(await chatPage.evaluate(() => Reflect.get(window, "qaLeaks"))).toEqual([]);
});
```

- [ ] 执行 `npx playwright test tests/e2e/chat-boundary.spec.ts`；预期内部 canary 从未进入聊天，用户可见消息为已通过展示门槛的中文；用户原始代码/引用/文件名按内容保留，不将其误判为内部英文泄漏。双语文件通过成果附件访问，不把英文内部消息串流到聊天。提交截图与事件对应记录；此任务不承担 GUI 功能实现。

### Task 5：恢复、去重、取消和会话隔离（QA-05）

**Files:** 新建 `tests/reliability/test_recovery.py`。
**Interfaces:** CASE `recovery` 接受 `fault`；输出真实 `external_starts`、`accepted_attempts`、`task_state`、`published_versions`、`cross_task_reads`。

- [ ] 覆盖持久化前后崩溃、请求已到远端但本地超时、重复消息、乱序/旧轮次结果、服务重启、人工暂停、取消后迟到结果；先对账外部执行状态，未知状态不能盲目重发。按 task/attempt/session/version 隔离，保存检查点后恢复；取消有确认状态，远端无法终止时如实显示并阻止其结果发布。

```python
def test_timeout_and_duplicate_do_not_start_twice(probe):
    r = probe("recovery", fault="remote_started_then_local_timeout_and_duplicate")
    assert r["external_starts"] == 1
    assert len(r["accepted_attempts"]) == 1
    assert r["cross_task_reads"] == []

def test_cancelled_task_cannot_publish_late_result(probe):
    r = probe("recovery", fault="cancel_then_late_success")
    assert r["task_state"] == "CANCELLED"
    assert r["published_versions"] == []
```

- [ ] 执行 `python -m pytest tests/reliability/test_recovery.py -q`；预期取消/失败均不交付，过时 PASS 不批准新版本；上游变更沿依赖使下游验收失效。额外用两个任务相同文件名、不同会话内容检验零串读串写。提交故障注入及恢复记录。

### Task 6：真实连接与用量账本（QA-06）

**Files:** 新建 `tests/contracts/test_connectivity_usage.py`、`quality/installed-capabilities.json`。
**Interfaces:** CASE `connection_usage` 接受 `fault`；输出 `connected`、`task_state`、`delivery_count`、`normalized_a_tokens`、`usage_complete`、`user_error`。

- [ ] 在假适配器重放无凭证、登录过期、限流、进程退出码 0 但无成果、空响应、损坏 JSON、断网与未知远端状态；每个安装版本用真实小任务核实启动、工具、GLM 选择、追问、恢复、取消、会话隔离及用量。桌面和 CLI 是否同会话另测，不能由共享目录推断；未测能力标“未验证”。

```python
def test_connection_failure_is_not_success(probe):
    r = probe("connection_usage", fault="expired_credentials")
    assert not r["connected"] and r["delivery_count"] == 0
    assert r["task_state"] in {"BLOCKED", "NEEDS_INPUT", "FAILED"}

def test_duplicate_usage_event_is_counted_once(probe):
    r = probe("connection_usage", fault="same_120_token_event_delivered_twice")
    assert r["normalized_a_tokens"] == 120 and r["usage_complete"]
```

- [ ] 执行 `python -m pytest tests/contracts/test_connectivity_usage.py -q`；预期失败给出中文可操作原因，未知用量不置零，会话累计量不逐轮相加；真实接入测试单独标记、单独执行并留存版本证据。提交能力矩阵，不用假适配器通过宣称本机接入已通过。

### Task 7：Windows 发布、迁移与恢复（QA-07）

**Files:** 新建 `tests/release/test_windows_delivery.py`、`release/release-checklist.md`。
**Interfaces:** CASE `windows_release` 接受 `fault`；输出 `installed_version`、`previous_version`、`restored_hashes`、`original_hashes`、`log_text`、`upgrade_state`。

- [ ] 使用干净 Windows 用户环境检查安装/卸载、中文/空格路径、非管理员运行、应用签名与更新包签名、发布者身份和包哈希；错误签名/未知发布者拒绝更新。用签名测试包验证下载中断、安装中断、启动失败后回滚；真实发布构建缺少有效签名或签名验证证据时不能走正式发布渠道。
- [ ] 用 N−1 版本真实数据库和工作区测试 N 迁移；迁移前创建一致性备份，包含 SQLite WAL 所需一致性、成果、manifest 和版本信息。迁移失败保留旧数据；回滚恢复匹配 schema 的备份，不能让旧程序直接打开不兼容新 schema。备份在隔离目录验证可恢复后才认可，损坏/缺文件备份拒绝恢复。

```python
def test_bad_update_keeps_working_install(probe):
    r = probe("windows_release", fault="invalid_publisher_signature")
    assert r["installed_version"] == r["previous_version"]
    assert r["upgrade_state"] == "REJECTED"

def test_restore_and_redaction(probe):
    r = probe("windows_release", fault="migration_failure_with_secret_canaries")
    assert r["restored_hashes"] == r["original_hashes"]
    assert "SECRET_CANARY_47" not in r["log_text"]
```

- [ ] 执行 `python -m pytest tests/release/test_windows_delivery.py -q`，并执行 `Get-AuthenticodeSignature -LiteralPath 'dist/AIBroker-Setup.exe' | Select-Object Status,SignerCertificate`（产物名由打包计划统一）；预期签名有效且发布者匹配。日志/诊断导出覆盖 Authorization、cookie、token、路径及正文隐私 canary，默认不导出原文；恢复后缺凭证应重新连接，不能假报已登录。提交签名链、回滚与备份恢复记录。

### Task 8：本地性能与两类发布门槛（QA-08）

**Files:** 新建 `tests/performance/test_local_slo.py`；更新 `release/release-checklist.md`。
**Interfaces:** CASE `local_load` 接受 `history_tasks`、`active_tasks`；输出 `ui_ack_p95_ms`、`state_visible_p95_ms`、`cold_start_p95_ms`、`external_latency_report`。

- [ ] 提议基准机 Windows 11、4 核/16 GB/SSD；记录真实硬件和版本。本地单用户、10,000 条历史任务、1 个活动任务和已设定的 A/B 有界队列；覆盖长文本、100 MB 附件、20 MB 日志、1,000 条重复事件及运行中关闭窗口。附件大小为测试场景，不据此承诺所有格式支持。

```python
def test_local_responsiveness_excludes_model_wait(probe):
    r = probe("local_load", history_tasks=10000, active_tasks=1)
    assert r["ui_ack_p95_ms"] <= 200
    assert r["state_visible_p95_ms"] <= 1000
    assert r["cold_start_p95_ms"] <= 3000
```

- [ ] 执行 `python -m pytest tests/performance/test_local_slo.py -q`；这些数值是待验证 SLO。UI 确认、状态落盘到可见及冷启动计本地性能；外部排队、首 token、模型执行、翻译、重试和端到端耗时另报 p50/p95/失败率，不从总耗时隐藏，也不承诺外部模型响应上限。
- [ ] **软件功能发布门槛：** QA-02 至 QA-07 的强制场景通过；无未解决的数据丢失、串会话、凭证泄漏、假成功或半包发布缺陷；本地 SLO 达标；真实能力按安装版本记录，未就绪入口不标可用；备份恢复与签名更新演练完成。四类任务各有真实端到端样本。发布构建绑定提交、依赖锁、SBOM、签名、测试和回滚记录。
- [ ] **优化配置资格门槛：** 仅 QA-01 同时证明质量目标和 A 用量改善的具体模型/领域/难度配置可声明“已验证节省且达到基准”；样本不足、质量不达标或无法省 token 的配置回到 A 主导。A 仍需完整推理/定稿时接受其成本，不为节省截断；评估不确定不等于已证明质量下降。
- [ ] 发布前执行 `python -m pytest tests/quality tests/translation tests/artifacts tests/reliability tests/contracts tests/release tests/performance -q` 和 `npx playwright test tests/e2e/chat-boundary.spec.ts`；预期本构建全部必要检查通过，未验证项明确列出且不误标通过。受控试用→签名候选版→正式版，每阶段检查新增缺陷与用量；严重回归立即停用优化配置或回滚，保留任务与原件。
- [ ] 提交报告，并按 R01–R15 核对需求映射、证据路径及责任人。报告明确“已测范围/未测范围/测量口径”；禁止宣称绝对无误、所有任务等效或虚构固定节省率。
