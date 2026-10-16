# 基础、接入与后端逐项执行 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 D001–D020 拆成可以逐卡执行、逐项核验的基础工程、真实接入与后端闭环任务。
**Architecture:** 沿用既有 Electron + React + TypeScript 桌面和 Python FastAPI 本地调度服务，SQLite 保存状态及 outbox；本手册不改变产品架构。
**Tech Stack:** Python、FastAPI、Pydantic、SQLite、pytest；Node/npm、Electron、React、TypeScript；Windows 11 x64。

## Global Constraints

- 本文件是未来执行手册；所列源码、fixtures、测试与命令均是拟建内容，未因写入本计划而存在或通过。
- 本轮只写文档与任务索引，不安装依赖、不运行模型、不修改实现文件。
- 需求优先级与语言/来源约束继承主计划和翻译规格；A 质量优先，不能以节省为由降低验收。
- 源文件不可变；Claude 全输入语言门槛、中文输出、真实 A 英文定稿与双语配对规则不能被后端“临时绕过”。
- 首先完成 D002 工程与测试收集环境，再执行 D003–D006；修正旧主计划 P0 测试依赖尚未建立工程的顺序。
- D004–D006 是未来有界真实接入实验。D003 为只读探测，不能顺便登录、升级、安装或消耗模型。
- D006 可按“路线已决定但未连接”完成决策记录；GPT 功能只有真实验证通过后才能启用，不能把两者混记。
- D007 可在真实接入实验并行时稳定已有协议；D020 的真实后端验收必须等待 D004/D005 必需能力通过。
- 所有路径从仓库根 `C:/Users/asd15/Documents/ChatGPT/ai` 解析；`app` 导入来自 `services/orchestrator/app`。
- 每卡十项操作，共二十卡、二百项；估时为工程工时初估，不包含排队、账号等待或整体交付日期承诺。
- 编码卡按反例→确认行为失败→实现→复验→保留证据推进。装置缺失不算业务反例，文档卡采用审阅验证。
- 证据须注明提交、配置、时间、模型/工具版本、实际命令和退出码；真实、fake、未验证结果分开。
- 默认 pytest 排除 `real_provider`；明确执行该标记前确认账号、预算、隔离目录和试验范围已就绪。
- 本手册完成只代表基础后端交接；后续翻译、文档、GUI、质量评测及签名发布仍有独立门槛。

## 共享接口与装置（未来实现合同）

`ProviderIdentity(adapter, model_id, family, connection_id)`、`AgentRequest` 与 `AgentEvent` 沿原主计划，不添加破坏位置参数的必需构造字段。任务/路由关联信息存显式记录。
`classify_probe(report: dict) -> str` 返回 `verified/unknown/mismatch`，仅 App 名或模型别名不足以 verified。
`AppSettings(data_root: Path, api_token: str, provider_mode: Literal["fake","real"], startup_recovery: bool)` 是 D009 配置合同。
`app.api.application.create_app(settings: AppSettings) -> FastAPI` 是唯一应用工厂；fake 模式只供测试，注册 `fake-gpt/fake-glm`，无真实请求。
`project_event(event: dict) -> dict | None` 是 D018 投影合同，输入先通过内部事件校验；不接受用户直接提交发布结论。
`scripts/probe_provider.py` 只有带 `--execute` 才发真实请求，`--max-runs` 是请求启动上限，未启用能力给出非零/明确未连接结果。
`tests/support/scenario_driver.py CASE --root DIR --options JSON` 只在测试构建运行，写真实证据并输出单个 JSON；不得在生产 API 暴露。

| API（D009） | 请求/响应约束 |
| --- | --- |
| `POST /v1/conversations` | `{"title":"会话"}`；201 返回 `id` |
| `GET /v1/conversations` | 公开会话分页；不包含内部会话提示词 |
| `POST /v1/conversations/{id}/turns` | `text,provider_profile_id,client_request_id`；202 返回 `turn_id,task_id`；重复键返回原结果 |
| `GET /v1/conversations/{id}/messages` | 仅用户输入、批准回答及必要中文错误/澄清 |
| `GET /v1/conversations/{id}/events?after_seq=N` | SSE；仅 PublicEvent；同 sequence 去重回放 |
| `GET /v1/tasks/{task_id}` | 公开运行/取消状态，不包含原始模型文本 |
| `POST /v1/tasks/{task_id}/cancel` | 202；取消请求与外部停止确认分开表示 |

D007 PublicEvent 白名单：`message.accepted,response.pending,answer.published,artifacts.published,request.failed,request.cancelled,input.required`。
本地服务仅回环绑定；随机令牌由 Electron 主进程持有并代理请求，renderer 不获取令牌/模型凭证或任意执行能力。
下面是 D009 建立的 `tests/conftest.py` 完整代表性装置。延迟导入使 D002–D008 测试收集不依赖尚未建好的 API。

```python
import json
import subprocess
import sys
import pytest

@pytest.fixture
def client(tmp_path):
    from fastapi.testclient import TestClient
    from app.api.application import create_app
    from app.config import AppSettings
    settings = AppSettings(data_root=tmp_path, api_token="qa-local-token",
                           provider_mode="fake", startup_recovery=False)
    with TestClient(create_app(settings)) as value:
        value.headers["Authorization"] = "Bearer qa-local-token"
        yield value

@pytest.fixture
def probe(tmp_path):
    def run(name, **options):
        command = [sys.executable, "tests/support/scenario_driver.py", name,
                   "--root", str(tmp_path), "--options", json.dumps(options)]
        result = subprocess.run(command, check=True, capture_output=True,
                                text=True, encoding="utf-8", timeout=600)
        return json.loads(result.stdout)
    return run
```

## 三组完整代表性测试（未来预期，非已运行证据）

D001–D006：D002 写 `tests/unit/test_package_bootstrap.py`；D003 写 `tests/contracts/test_readonly_probe.py`。文档 D001 只做需求审阅。
```python
# tests/unit/test_package_bootstrap.py
def test_backend_package_is_importable():
    import app
    assert app.__name__ == "app"

# tests/contracts/test_readonly_probe.py
from app.providers.probe import classify_probe

def test_application_label_cannot_verify_actual_model():
    result = classify_probe({"app_name": "Claude Code", "model_alias": "Claude",
                             "identity_source": None, "observed_family": None})
    assert result == "unknown"
```

D007–D012：`tests/integration/test_conversation_api.py` 使用上面的 `client`，D009 起可运行；实际重复事件与崩溃测试按各卡场景扩展。
```python
def test_repeated_turn_submission_is_idempotent(client):
    created = client.post("/v1/conversations", json={"title": "测试"})
    assert created.status_code == 201
    endpoint = f"/v1/conversations/{created.json()['id']}/turns"
    payload = {"text": "检查样本", "provider_profile_id": "fake-gpt",
               "client_request_id": "same-request"}
    first = client.post(endpoint, json=payload)
    second = client.post(endpoint, json=payload)
    assert first.status_code == second.status_code == 202
    assert first.json()["turn_id"] == second.json()["turn_id"]
    assert first.json()["task_id"] == second.json()["task_id"]
```

D013–D020：`tests/integration/test_public_projection.py` 验证公开边界；`test_backend_vertical.py` 的 CASE 必须由 D020 驱动实际服务并导出数据库/文件证据。
```python
# tests/integration/test_public_projection.py
from app.runtime.public_projection import project_event

def test_internal_model_text_is_not_a_public_message():
    event = {"task_id": "t1", "attempt_id": "a1", "sequence": 1,
             "kind": "model.delta", "payload": {"text": "INTERNAL_ENGLISH_CANARY"}}
    assert project_event(event) is None

# tests/integration/test_backend_vertical.py
def test_cancel_blocks_late_answer_and_new_requests(probe):
    result = probe("backend_cancel_late", provider_mode="fake")
    assert result["task_state"] == "CANCELLED"
    assert result["public_answer_count"] == 0
    assert result["model_starts_after_cancel"] == 0
```

示例只负责对应反例；各任务的正例、其余负例及故障点必须按卡逐项建立，不能用示例数量代替覆盖要求。

## D001 需求及非目标冻结

**目的：** 形成后续可追踪且不可偷偷降级的开发合同。
**阶段 / 负责：** F0 范围冻结；产品负责人 + 技术负责人；初估 4 工时。
**依赖 / 需求：** 无；R01、R02、R03、R04、R05、R06、R07、R08、R09、R10、R11、R12、R13、R14、R15。
**输入：** 现有工业化主计划、翻译交付规格、质量发布计划及用户已确认要求。
**准确拟建文件：** `docs/decisions/requirements-v1.json`；`docs/decisions/scope-v1.md`；`docs/decisions/decision-log.md`。

- [ ] 01. 逐条摘录 R01–R15 到 requirements-v1.json，保留原编号、来源文档和验收责任人。
- [ ] 02. 在 scope-v1.md 固定 Windows 11 x64、本地单用户和首版 PDF/DOCX/Markdown 范围。
- [ ] 03. 登记不建设云多租户、移动客户端、自动绕过账号资格及无限模型重试四项非目标。
- [ ] 04. 将 A 质量优先、必要核心推理保留和不固定两次 A 调用写入不可变规则。
- [ ] 05. 写入 Claude 全输入翻译、输出中文、追问同规则及 GPT 零强制翻译规则。
- [ ] 06. 将 A 必须亲自产出完整英文定稿及双语同版本交付写成独立硬约束。
- [ ] 07. 建立内部事件不得进入聊天、真实失败不得伪装成功的发布边界。
- [ ] 08. 记录 GPT 入口待实测、ZCode 桌面与 CLI 会话未知等事实缺口及决策责任人。
- [ ] 09. 逐条人工核对需求、排除项和原始指令，给发现的冲突登记优先级及处理结论。
- [ ] 10. 将需求版本、复核人、复核时间和后续变更必须升版的规则写入 decision-log.md。

**测试命令：** `Get-Content -Raw docs/decisions/requirements-v1.json | ConvertFrom-Json | Select-Object -ExpandProperty requirements`。
**预期：** requirements 为含 R01–R15 的十五项数组；来源与验收责任可追踪；人工复核范围表。
**负例：** 删去 A 完整英文定稿或将质量改为基线 95% 时，复核必须拒绝冻结；此项不为文档建立无意义单元测试。
**证据：** `docs/acceptance/D001/scope-review.md`。
**完成条件：** 十五项均有来源、验收定义和责任人，冲突已决策或明确阻塞相关后续工作。
**失败回退：** 保留上一需求版本；不以默认值覆盖未决的实质范围问题。

## D002 项目工程与依赖锁

**目的：** 先建立可安装、可收集测试的工程，再运行接入探测，消除旧 P0 先测试后建工程的依赖倒挂。
**阶段 / 负责：** F1 工程基础；后端工程师 + 桌面工程师；初估 6 工时。
**依赖 / 需求：** D001；R12、R13。
**输入：** D001 冻结范围；Windows 开发机；上游包的受支持版本信息。
**准确拟建文件：** `package.json`；`package-lock.json`；`apps/desktop/package.json`；`services/orchestrator/pyproject.toml`；`services/orchestrator/uv.lock`；`services/orchestrator/app/__init__.py`；`pytest.ini`；`tests/unit/test_package_bootstrap.py`；`docs/runbooks/development.md`。

- [ ] 01. 创建 apps/desktop、services/orchestrator/app 和 tests 的目录及最小包标记。
- [ ] 02. 在后端 pyproject.toml 声明 app 包发现、运行依赖和 test 可选依赖组。
- [ ] 03. 选择已核对的 Python/Node/Electron/React/FastAPI/Pydantic 版本并记录选择依据。
- [ ] 04. 生成后端 uv.lock，固定 uv sync --locked 的重建方式及项目虚拟环境解释器路径。
- [ ] 05. 创建根 npm workspace 和桌面包，锁定 package-lock.json；定义 test:e2e 为 playwright test，默认配置排除真实外部模型场景。
- [ ] 06. 在 pytest.ini 注册 real_provider、windows、slow 标记，并默认排除真实模型测试。
- [ ] 07. 建立仅导入 app 的 bootstrap 测试，确保缺包时得到真实失败。
- [ ] 08. 在干净虚拟环境按锁安装工程并运行 bootstrap，记录实际命令和退出码。
- [ ] 09. 在干净检出使用 npm ci 与 uv sync --locked 重建一次，确认不会修改锁文件。
- [ ] 10. 登记离线缺包、安装失败和版本冲突的恢复步骤，复核后提交工程基线。

**测试命令：** `uv sync --project services/orchestrator --locked --extra test`；`& .\services\orchestrator\.venv\Scripts\python.exe -m pytest tests/unit/test_package_bootstrap.py -q`；`npm ci`。
**预期：** 安装后可从仓库根导入 app，bootstrap 通过；锁定重建不改依赖锁。
**负例：** 删去包发现配置或篡改锁一致性时必须失败；不得自动升级依赖掩盖问题。
**证据：** `docs/acceptance/D002/runtime-versions.json`；`docs/acceptance/D002/bootstrap.log`。
**完成条件：** 工程可重建、测试可收集、版本和锁一致；尚不代表 GUI 或模型接入完成。
**失败回退：** 恢复最后通过的锁与配置，在隔离环境重建，不修改全局解释器。

后续所有 `python` 命令均指本卡创建的 `services/orchestrator/.venv/Scripts/python.exe`。在仓库根激活该虚拟环境后运行；无法激活时用上述显式解释器路径。不得在系统 Python 执行测试却误用另一个环境的安装结果。`uv.lock` 首次生成需要先选定依赖；后续重建必须 `--locked`，不再用无锁的 `pip install -e` 重新解析依赖。

## D003 本机只读能力探测

**目的：** 建立真实安装信息和未知项清单，避免猜测 CLI、会话和账户能力。
**阶段 / 负责：** F1 工程基础；接入工程师；初估 6 工时。
**依赖 / 需求：** D002；R03、R04、R13、R14。
**输入：** D002 可运行工程；用户已有 Claude Code、ZCode 及可选 GPT 安装位置。
**准确拟建文件：** `services/orchestrator/app/providers/probe.py`；`scripts/probe_provider.py`；`tests/contracts/test_readonly_probe.py`；`docs/acceptance/local-capabilities.json`。

- [ ] 01. 定义本机探测结果字段 path、version、help_source、capability、status、evidence_ref。
- [ ] 02. 建立仅允许已知无副作用的版本/帮助读取白名单，未知命令不自动执行。
- [ ] 03. 读取程序路径与文件版本，检查已知 CLI 帮助而不登录、不更新、不调用模型。
- [ ] 04. 检查 Python、Node、文档转换器和 OCR 的存在及版本，缺失能力标 unavailable。
- [ ] 05. 收集启动、非交互、工作目录、取消、恢复、模型选择和用量能力的文档证据。
- [ ] 06. 将桌面与 CLI 是否共享会话、登录和额度分别设 unknown，等待真实实验。
- [ ] 07. 实现 classify_probe，模型别名或 App 名不得单独得到 verified 身份。
- [ ] 08. 建立 scripts/probe_provider.py 的读配置入口，真实执行必须显式带 --execute 和 --max-runs。
- [ ] 09. 用假命令运行探测契约测试，断言未启动模型、未读取密钥内容且未写用户配置。
- [ ] 10. 生成 local-capabilities.json，分别列出已见事实、推断和待验证事项并复核。

**测试命令：** `python -m app.providers.probe --read-only --output docs/acceptance/local-capabilities.json`；`python -m pytest tests/contracts/test_readonly_probe.py -q`。
**预期：** 产生可追溯能力报告；未知身份保持 unknown；没有真实模型请求和凭证输出。
**负例：** 把名为 Claude 的程序配置成未知后端，结果不得直接标 claude/verified。
**证据：** `docs/acceptance/D003/probe-trace.json`；`docs/acceptance/local-capabilities.json`。
**完成条件：** 每项能力有状态及证据，探测副作用测试通过，真实实验执行器可供 D004–D006 使用。
**失败回退：** 关闭无法确认只读性的探测分支，改用已安装文件/官方帮助人工取证并标未知。

## D004 Claude 真实适配验证

**目的：** 验证本机 Claude Code 的真实程序入口与事件行为，形成可移植适配证据。
**阶段 / 负责：** F2 真实入口验证；接入工程师 + QA；初估 12 工时。
**依赖 / 需求：** D003；R03、R12、R14。
**输入：** D003 能力报告；正常可用账号；隔离实验目录；仅用于接入测试的英文小任务。
**准确拟建文件：** `services/orchestrator/app/providers/claude_code.py`；`docs/acceptance/profiles/claude.json`；`tests/contracts/test_claude_adapter.py`；`docs/acceptance/claude-capabilities.json`。

- [ ] 01. 将已核验命令路径、参数数组和版本写入 claude.json，凭证只保存系统引用。
- [ ] 02. 创建英文输入 fixture，任务仅要求读取 input.txt 并写出固定结果，不触碰用户工作区。
- [ ] 03. 通过显式真实测试开关启动一次 Claude，请求中记录 task/attempt 和工作目录。
- [ ] 04. 核对实际模型族的响应元数据或已核验配置来源，别名不能充当身份。
- [ ] 05. 保存原始结构化事件的脱敏副本，并将文本、工具、用量和终态逐类标注。
- [ ] 06. 验证结果文件字节、退出码与明确完成事件，三者不一致时记录失败。
- [ ] 07. 执行有界取消与恢复实验，确认外部执行编号和进程存活状态可以核对。
- [ ] 08. 分别核实 CLI 结果在桌面是否可见、会话是否同一、额度口径是否相同。
- [ ] 09. 重放失败登录、限流、截断与身份变化样本，确认不产生可用连接或成功结果。
- [ ] 10. 形成能力报告和缺口清单，只有通过的能力进入适配器启用清单。

**测试命令：** `python scripts/probe_provider.py --profile docs/acceptance/profiles/claude.json --execute --max-runs 3 --output docs/acceptance/D004`；`python -m pytest tests/contracts/test_claude_adapter.py -q`；`python -m pytest -o addopts='' tests/contracts/test_claude_adapter.py -m real_provider -q`。
**预期：** 真实小任务有结果哈希、外部执行编号及用量来源；取消与恢复能力如实记载。
**负例：** 退出码 0 但成果缺失、模型身份不匹配或结果截断都不能通过。
**证据：** `docs/acceptance/D004/probe-report.json`；`docs/acceptance/D004/artifact-hashes.json`；`docs/acceptance/claude-capabilities.json`。
**完成条件：** Claude 必需启动、工具、身份和结果能力验证通过；未支持的恢复/取消行为有明确限制及应对。
**失败回退：** 禁用不合格连接并保留失败证据；可继续离线适配器开发，但不得称真实接入通过。

## D005 ZCode 真实适配验证

**目的：** 确认 B 实际是 ZCode 中的 GLM，并验证独立执行器能力。
**阶段 / 负责：** F2 真实入口验证；接入工程师 + QA；初估 14 工时。
**依赖 / 需求：** D003；R04、R12、R14。
**输入：** D003 报告；已安装 ZCode；受支持入口和正常账户权限；隔离任务目录。
**准确拟建文件：** `services/orchestrator/app/providers/zcode.py`；`docs/acceptance/profiles/zcode.json`；`tests/contracts/test_zcode_adapter.py`；`docs/acceptance/zcode-capabilities.json`。

- [ ] 01. 将本机支持的 ZCode 启动路径和参数数组写入 profile，禁止臆造未发现的 CLI 参数。
- [ ] 02. 固定 GLM 模型选择，并保存实际模型身份的核验依据。
- [ ] 03. 运行读取 fixture、修改指定文件、返回结果清单的有界真实任务。
- [ ] 04. 验证 B 具备所需文件和终端工具，不能仅以模型能回复文本判定执行器可用。
- [ ] 05. 记录任务开始、输出、工具交互、待人工动作、用量和终态原始事件。
- [ ] 06. 执行中断、恢复和取消实验，并核对远端/本地是否继续运行。
- [ ] 07. 分别测试 ZCode 桌面与 CLI 的会话可见性、登录和额度，不把项目文件共享等同会话共享。
- [ ] 08. 用不同工作区连续执行两个内容不同的任务，检查文件和上下文不会串用。
- [ ] 09. 重放 GLM 选择失效、需要交互、空结果和权限拒绝，确认结构化失败原因。
- [ ] 10. 整理真实能力矩阵；自动入口不满足要求时把全自动 B 标为阻塞而非降级成假成功。

**测试命令：** `python scripts/probe_provider.py --profile docs/acceptance/profiles/zcode.json --execute --max-runs 3 --output docs/acceptance/D005`；`python -m pytest tests/contracts/test_zcode_adapter.py -q`；`python -m pytest -o addopts='' tests/contracts/test_zcode_adapter.py -m real_provider -q`。
**预期：** 真实 GLM 工具任务可验证；桌面/CLI 差异明确；不支持项被禁用。
**负例：** 只获得聊天文本而没有指定产物、自动切换为其他模型或复用上一任务内容都不通过。
**证据：** `docs/acceptance/D005/probe-report.json`；`docs/acceptance/D005/session-matrix.md`；`docs/acceptance/zcode-capabilities.json`。
**完成条件：** B 必需执行能力通过且模型身份明确；否则对应自动产品路径保持阻塞。
**失败回退：** 保留文件协议用于人工研发验证，重新评估受支持入口；不得把人工交接当工业化完成。

## D006 GPT 路线和真实适配验证

**目的：** 确定用户可用的 GPT 入口，并将可选连接状态与已验证能力严格区分。
**阶段 / 负责：** F2 真实入口验证；接入工程师 + 产品负责人；初估 8 工时。
**依赖 / 需求：** D003；R03、R10、R12、R14。
**输入：** 用户已有 GPT 使用入口；D003 环境信息；受支持接口说明。
**准确拟建文件：** `services/orchestrator/app/providers/gpt.py`；`docs/decisions/gpt-route.md`；`docs/acceptance/profiles/gpt.json`；`tests/contracts/test_gpt_adapter.py`；`docs/acceptance/gpt-capabilities.json`。

- [ ] 01. 列出实际可用入口与所需权限，选择用户已有且支持自动调用的路线。
- [ ] 02. 记录选择依据、登录方式及是否需要独立服务权限，不将网页订阅视为 API 权限。
- [ ] 03. 无可用入口时保存 not_connected 决策，禁用该连接并允许共同协议工作继续。
- [ ] 04. 有入口时将已核验命令或官方调用配置写入 profile，凭证只保留系统引用。
- [ ] 05. 用中文小任务执行有界真实请求，并核验实际 model_family 为 gpt。
- [ ] 06. 采集结果、用量、错误、取消及恢复行为，保留提供方原始口径。
- [ ] 07. 验证 App 名或配置别名不决定语言路由，身份 unknown 或 mismatch 时停止。
- [ ] 08. 重放身份回退、失效凭证、空结果与超时样本，产生明确状态而非假连接成功。
- [ ] 09. 编写后续 native 路由必须零强制翻译的适配合同，任务仍允许正常调用 B 执行。
- [ ] 10. 复核报告；把真实接入通过与仅路线已决策两种完成等级分开记录。

**测试命令：** `python -m pytest tests/contracts/test_gpt_adapter.py -q`；`python scripts/probe_provider.py --profile docs/acceptance/profiles/gpt.json --execute --max-runs 3 --output docs/acceptance/D006`；`python -m pytest -o addopts='' tests/contracts/test_gpt_adapter.py -m real_provider -q`。
**预期：** 有连接才执行真实命令；not_connected 时路线决策可完成但功能保持禁用，报告不可写真实适配通过。
**负例：** 模型自称 GPT、应用名含 GPT 或订阅存在，均不足以将未经核验连接启用。
**证据：** `docs/acceptance/D006/route-review.md`；`docs/acceptance/D006/probe-report.json`；`docs/acceptance/gpt-capabilities.json`。
**完成条件：** 路线和连接状态明确；若启用 GPT，真实身份与最小工具任务均通过；未连接不阻塞共同后端协议。
**失败回退：** 禁用 GPT 连接并保留 Claude 默认路线，不在后台替用户切换 A。

## D007 统一内部与公开协议

**目的：** 稳定跨模块字段、事件与身份语义，使并行开发能够独立验收。
**阶段 / 负责：** F3 后端合同；后端架构工程师；初估 8 工时。
**依赖 / 需求：** D001、D002、D003；R03、R04、R07、R08、R09、R10、R11、R12、R14、R15。
**输入：** 主计划现有 ProviderIdentity/AgentRequest/AgentEvent 定义；翻译规格数据契约；D004–D006 已有或未验证能力状态。
**准确拟建文件：** `services/orchestrator/app/contracts/providers.py`；`services/orchestrator/app/contracts/events.py`；`services/orchestrator/app/contracts/translation.py`；`services/orchestrator/app/contracts/artifacts.py`；`services/orchestrator/app/providers/base.py`；`packages/contracts/public-events.schema.json`；`packages/contracts/provider.schema.json`；`scripts/check_contracts.py`；`tests/contracts/test_schemas.py`。

- [ ] 01. 保留 ProviderIdentity(adapter, model_id, family, connection_id) 的字段与构造顺序。
- [ ] 02. 保留 AgentRequest 和 AgentEvent 字段，将轮次、路由快照和身份依据放入显式关联记录。
- [ ] 03. 定义 verified/unknown/mismatch 身份状态，写明身份变化不能静默替换当前轮路由。
- [ ] 04. 按翻译规格登记 RouteSnapshot、TranslationJob、ArtifactVersion、DeliveryBundle 的必需字段。
- [ ] 05. 将内部事件与公开事件建成独立模型，公开模型拒绝额外字段。
- [ ] 06. 固定 message.accepted、response.pending、answer.published、artifacts.published、request.failed、request.cancelled、input.required 白名单。
- [ ] 07. 为用户文本、最终中文回答、必要中文澄清和附件引用定义公开 payload，禁止 raw_response/log/prompt。
- [ ] 08. 生成 Python 与 JSON Schema 合同样本，固定 schema_version 并记录兼容规则。
- [ ] 09. 用未知模型、额外字段、缺 attempt、乱序 sequence 和非法 visibility 建立拒绝测试。
- [ ] 10. 与接入、翻译和桌面负责人逐项核对字段及错误码，冻结合同 v1。

**测试命令：** `python -m pytest tests/contracts/test_schemas.py -q`；`python scripts/check_contracts.py --strict`。
**预期：** 合法样本跨语言一致；内部内容无法通过 PublicEvent 校验；检查脚本由本卡创建。
**负例：** 把 tool.delta 或 raw_response 包装进公开事件仍必须拒绝，不能以 unknown 字段自动透传。
**证据：** `docs/acceptance/D007/contracts-report.json`；`docs/acceptance/D007/contract-review.md`。
**完成条件：** 字段、白名单、版本策略和跨语言样本冻结；D004–D006 真实结果后续通过同一合同适配。
**失败回退：** 回退合同版本并迁移消费者；不得同时默许多份含义不同的同名字段。

## D008 数据库迁移和源文件存储

**目的：** 把任务、来源、事件和成果版本可靠持久化，保证原件不可被覆盖。
**阶段 / 负责：** F3 后端合同；后端存储工程师；初估 12 工时。
**依赖 / 需求：** D002、D007；R09、R12、R13、R14。
**输入：** D007 合同；SQLite；独立测试工作区。
**准确拟建文件：** `services/orchestrator/app/storage/database.py`；`services/orchestrator/app/storage/migrations.py`；`services/orchestrator/app/storage/blobs.py`；`services/orchestrator/app/storage/schema/0001_initial.sql`；`tests/integration/test_storage.py`。

- [ ] 01. 建立 conversations、turns、task_runs、steps、provider_profiles、artifact_revisions、translation_units、checks、usage_entries、outbox_events 表。
- [ ] 02. 为任务版本、外部请求幂等键及事件 sequence 建立唯一约束和外键。
- [ ] 03. 实现带 schema_version 的顺序迁移入口，迁移失败在事务内回滚。
- [ ] 04. 建立原件内容哈希存储，写临时文件完成后再以不可变路径登记。
- [ ] 05. 校验文件实际字节哈希，禁止以同路径写入不同内容覆盖已有原件。
- [ ] 06. 在数据库记录来源角色、外部请求引用、文件版本及依赖，不仅记录文件名。
- [ ] 07. 设置一致性事务及 busy_timeout，明确单写者和 WAL 运行规则。
- [ ] 08. 注入磁盘不足、写文件中断、数据库锁定及引用缺失文件，确认不产生可见半成果。
- [ ] 09. 迁移后打开旧版测试数据库并验证数据数量、主外键和原件哈希。
- [ ] 10. 登记数据库及 blob 备份边界，保存迁移报告后提交。

**测试命令：** `python -m pytest tests/integration/test_storage.py -q`。
**预期：** 迁移可复验、原件不可变、引用文件均存在且哈希一致；失败保留旧数据。
**负例：** 文件写失败后数据库不得登记成功；同哈希键配不同字节必须拒绝。
**证据：** `docs/acceptance/D008/migration-report.json`；`docs/acceptance/D008/storage-faults.json`。
**完成条件：** 新库、旧库迁移和中断场景通过；完整备份恢复由后续发布任务接续。
**失败回退：** 恢复迁移前数据库副本和匹配 blob 集合，禁止人工删约束强行继续。

## D009 会话和任务 API

**目的：** 为桌面提供经过认证的最小会话入口及公开历史，不暴露内部模型数据。
**阶段 / 负责：** F4 持久运行时；后端 API 工程师；初估 10 工时。
**依赖 / 需求：** D007、D008；R03、R06、R11、R12、R13。
**输入：** D007 公开合同；D008 存储；统一 AppSettings 与测试 fixture。
**准确拟建文件：** `services/orchestrator/app/config.py`；`services/orchestrator/app/api/application.py`；`services/orchestrator/app/api/conversations.py`；`services/orchestrator/app/api/turns.py`；`services/orchestrator/app/api/tasks.py`；`tests/conftest.py`；`tests/integration/test_conversation_api.py`。

- [ ] 01. 定义 AppSettings(data_root, api_token, provider_mode, startup_recovery) 并拒绝未知生产配置。
- [ ] 02. 实现 create_app(settings) 工厂，测试不依赖全局目录或真实账户。
- [ ] 03. 绑定回环地址并校验主进程持有的随机认证令牌，拒绝缺失或错误令牌。
- [ ] 04. 建立创建/列出会话 API，返回稳定 conversation_id 和必要公开元数据。
- [ ] 05. 建立提交 turn API，要求 text、provider_profile_id、client_request_id 并返回 turn_id/task_id。
- [ ] 06. 固定当前轮模型连接和路由快照引用，后续设置切换不改当前任务。
- [ ] 07. 实现仅公开 messages 历史接口，内部消息无法靠 visibility 参数绕过。
- [ ] 08. 建立任务查询和取消请求接口，区分取消已请求与外部已确认停止。
- [ ] 09. 实现带 after_seq 的会话 SSE 订阅边界，事件载荷必须符合 PublicEvent。
- [ ] 10. 运行错误认证、未知会话、重复 client_request_id、跨会话读取负例并保存 OpenAPI 快照。

**测试命令：** `python -m pytest tests/integration/test_conversation_api.py -q`。
**预期：** 创建 201、提交 202；错误认证 401/403；重复提交返回相同 turn/task；历史不含内部文本。
**负例：** renderer 提交任意磁盘路径、内部 visibility 或未核验连接，API 不得执行或返回原文。
**证据：** `docs/acceptance/D009/openapi.json`；`docs/acceptance/D009/api-report.json`。
**完成条件：** 所有路由有请求/响应合同和失败状态，API fixture 可供后续任务复用。
**失败回退：** 保留数据库并禁用有缺陷路由；不得暂时删除认证以让桌面跑通。

## D010 状态转换与事务 outbox

**目的：** 保证状态改变和待发送事件一致，重启不会丢事件或重复发布。
**阶段 / 负责：** F4 持久运行时；后端运行时工程师；初估 14 工时。
**依赖 / 需求：** D008、D009；R11、R12。
**输入：** 主计划状态图；D008 数据库；D009 API 幂等键。
**准确拟建文件：** `services/orchestrator/app/runtime/state_machine.py`；`services/orchestrator/app/runtime/outbox.py`；`services/orchestrator/app/runtime/scheduler.py`；`tests/integration/test_state_outbox.py`。

- [ ] 01. 将正常路径和 NEEDS_INPUT/REPAIRING/BLOCKED/PAUSED/FAILED/CANCELLED 写成显式转换表。
- [ ] 02. 转换时同时校验 task_id、attempt_id、合同版本和 expected_state。
- [ ] 03. 将任务状态变化与 outbox 事件插入放在同一数据库事务。
- [ ] 04. 为 outbox 增加稳定 event_id、发送状态和消费去重键。
- [ ] 05. 实现 outbox 派发确认，发送失败保留待派发记录而非重跑模型。
- [ ] 06. 拒绝从 EXECUTING 直接跳到 PUBLISHED，发布必须持有版本匹配的门槛记录。
- [ ] 07. 对取消任务撤销发布资格，并阻止后续转换重新生成模型请求。
- [ ] 08. 注入提交前崩溃、提交后发送前崩溃和发送后确认前崩溃。
- [ ] 09. 验证三个崩溃点恢复后的状态、事件数量和外部请求数量符合幂等要求。
- [ ] 10. 保存转换表、失败事件序列及事务检查结果，完成独立复核。

**测试命令：** `python -m pytest tests/integration/test_state_outbox.py -q`。
**预期：** 事务失败无半状态；提交后可恢复派发；重复发送不会生成第二条用户回答。
**负例：** 旧 attempt 的 PASS、无批准的 READY 或取消后的完成事件不得进入 PUBLISHED。
**证据：** `docs/acceptance/D010/state-matrix.json`；`docs/acceptance/D010/crash-traces.json`。
**完成条件：** 全部合法转换及关键非法转换通过，outbox 三个崩溃窗口有可重放证据。
**失败回退：** 停止派发、保留 outbox 与检查点，修复后幂等恢复，不清空事件表。

## D011 进程启动取消与资源管理

**目的：** 以可追踪方式启动和停止模型执行器，避免残留进程、错误工作区和资源失控。
**阶段 / 负责：** F4 持久运行时；Windows 运行时工程师；初估 12 工时。
**依赖 / 需求：** D002、D007；R03、R04、R12、R13。
**输入：** 经核验的命令数组；D007 AgentRequest/AgentEvent；Windows 进程管理能力。
**准确拟建文件：** `services/orchestrator/app/runtime/processes.py`；`services/orchestrator/app/runtime/resources.py`；`services/orchestrator/app/runtime/leases.py`；`tests/integration/test_process_lifecycle.py`；`tests/fixtures/process_worker.py`。

- [ ] 01. 使用可执行文件与参数数组创建进程，禁止把用户内容拼接为 shell 命令。
- [ ] 02. 为进程固定独立工作目录、必要环境变量白名单和 stdout/stderr 捕获上限。
- [ ] 03. 建立 task/attempt/pid/外部会话编号的持久关联，区分本地 PID 与远端执行标识。
- [ ] 04. 在 Windows 将子进程树纳入受控作业对象或等效受支持机制。
- [ ] 05. 实现先请求正常取消、超时后终止本地树的有界策略，并记录确认结果。
- [ ] 06. 远端不能确认停止时标记 cancel_pending_remote，禁止把本地退出等同远端停止。
- [ ] 07. 为文件句柄、临时目录、输出缓冲和进程数量设置可配置限制。
- [ ] 08. 创建仅在临时目录写心跳的 fixture worker，包含孙进程和忽略正常退出两种模式。
- [ ] 09. 测试取消、父服务退出、输出洪泛和子进程异常，核对残留进程与句柄。
- [ ] 10. 保存生命周期图和限制命中证据，确认无需可见辅助窗口后提交。

**测试命令：** `python -m pytest tests/integration/test_process_lifecycle.py -m windows -q`。
**预期：** 本地进程树可回收，输出受限且证据保留；远端状态未知被明确记录。
**负例：** 恶意引号、空格路径、额外 shell 操作符作为普通参数处理，不能触发附加命令。
**证据：** `docs/acceptance/D011/process-tree.json`；`docs/acceptance/D011/resource-report.json`。
**完成条件：** 正常结束、取消、异常与资源上限场景通过，无已知残留本地进程。
**失败回退：** 停止新任务并回收已识别本地树，保留远端执行标识供对账，禁止盲目再启动。

## D012 重启恢复、去重与未知远端状态

**目的：** 在程序或网络异常后恢复原任务，避免远端重复执行和旧结果覆盖。
**阶段 / 负责：** F4 持久运行时；后端运行时工程师 + QA；初估 16 工时。
**依赖 / 需求：** D010、D011；R12、R14。
**输入：** D010 事务 outbox；D011 进程与远端标识；可重放适配器事件。
**准确拟建文件：** `services/orchestrator/app/runtime/recovery.py`；`services/orchestrator/app/runtime/deduplication.py`；`tests/integration/test_recovery.py`；`tests/fixtures/recovery_events.json`。

- [ ] 01. 启动时读取未终结任务、租约、外部执行标识及最后确认 sequence。
- [ ] 02. 分别识别仍运行、明确完成、明确失败和 unknown 四类远端状态。
- [ ] 03. 对仍运行任务恢复观察，对明确完成任务核验成果，对 unknown 保存阻塞而不自动重发。
- [ ] 04. 按 task/attempt/sequence 或提供方稳定事件键去重，保留重复接收审计。
- [ ] 05. 拒绝旧 attempt、旧合同版本和过期路由的事件覆盖当前状态。
- [ ] 06. 处理 sequence 缺口和乱序，不能因收到完成事件跳过必需成果核验。
- [ ] 07. 通过超时后远端仍执行场景验证重新连接不会新建第二个请求。
- [ ] 08. 通过取消后迟到回答场景验证不会发布、不会追加模型返修调用。
- [ ] 09. 强制退出本地服务并重启，核对任务、outbox、用量及文件版本仍一致。
- [ ] 10. 形成恢复决策表和人工对账入口说明，复核未知状态不会假完成。

**测试命令：** `python -m pytest tests/integration/test_recovery.py -q`。
**预期：** 事件 1、2、2、1、3 仅生效一次；unknown 不重发；重启后不跨 attempt 接受 PASS。
**负例：** 租约超时不等于远端失败，直接重发必须被测试阻止。
**证据：** `docs/acceptance/D012/recovery-report.json`；`docs/acceptance/D012/remote-unknown-trace.json`。
**完成条件：** 重复、乱序、崩溃、取消和未知远端状态均有确定恢复结果及审计。
**失败回退：** 将不确定任务保持 BLOCKED/PAUSED，等待可验证状态或用户明确重新开轮，不丢弃已产生用量。

## D013 A/B 任务合同及判断触发

**目的：** 让 A 保留决定质量的判断，B 按可验证合同执行，不退化为只看摘要的审批。
**阶段 / 负责：** F5 任务执行；智能体工作流工程师 + 领域评审；初估 10 工时。
**依赖 / 需求：** D001、D007、D008；R01、R02、R05、R09。
**输入：** 冻结需求；任务原件；D007 模型身份及成果合同。
**准确拟建文件：** `services/orchestrator/app/contracts/tasks.py`；`services/orchestrator/app/runtime/escalation.py`；`services/orchestrator/app/prompts/a_contract.md`；`services/orchestrator/app/prompts/b_execute.md`；`tests/unit/test_task_contracts.py`。

- [ ] 01. 定义任务目标、输入索引、约束、交付物、关键方法、依赖和预算字段。
- [ ] 02. 为每条验收项分配独立编号、强制性、验证者、证据类型和通过条件。
- [ ] 03. 将 A 的问题建模、核心推理及不可逆方向判断写入责任约定。
- [ ] 04. 给 B 明确文件写入范围、局部自主选择和不可更改的验收标准。
- [ ] 05. 定义 PASS、REPAIR、NEED_EVIDENCE、BLOCKED 四种结构化评审结论。
- [ ] 06. 规定证据不足、关键假设失效、方法变化、无进展和能力不足触发 A。
- [ ] 07. 为普通、节点指导、A 接管三种深度保存可升级配置，不固定 A 两次调用。
- [ ] 08. 规定全文审稿读取覆盖及抽样范围记录，摘要只作为原件导航。
- [ ] 09. 用缺证据 PASS、修改预算、降低验收标准及 B 报告冒充 A 原件建立拒绝测试。
- [ ] 10. 对代码、论文、文档和综合各冻结一个最小任务合同样本供后续测试。

**测试命令：** `python -m pytest tests/unit/test_task_contracts.py -q`。
**预期：** 合同可定位验收证据；触发升级不依赖 B 自信分数；实质歧义进入澄清。
**负例：** 缺少强制证据的 PASS、B 擅改目标或将自评分当独立审查均拒绝。
**证据：** `docs/acceptance/D013/contracts.json`；`docs/acceptance/D013/escalation-matrix.md`。
**完成条件：** 四域合同、升级触发和责任边界通过审查，A 必要质量投入不受武断次数限制。
**失败回退：** 退回 A 重订合同或请求必要输入，不以更松标准继续 B 执行。

## D014 执行和返修循环

**目的：** 建立 A 指导、B 执行、C 校验、A 复核的可停止闭环。
**阶段 / 负责：** F5 任务执行；智能体工作流工程师；初估 16 工时。
**依赖 / 需求：** D010、D011、D012、D013；R01、R02、R04、R05、R12。
**输入：** D013 任务合同；D010 状态机；适配器；尚未接入的翻译/发布门槛作为明确阻塞。
**准确拟建文件：** `services/orchestrator/app/runtime/workflow.py`；`services/orchestrator/app/runtime/repair.py`；`services/orchestrator/app/providers/fake.py`；`tests/integration/test_agent_workflow.py`；`tests/fixtures/workflow_cases.json`。

- [ ] 01. 根据合同建立任务步骤，将模型请求和成果版本关联到当前 attempt。
- [ ] 02. 将 B 执行结果保存为不可变候选，完成事件不直接写 PASS。
- [ ] 03. 调用验证端口记录机械检查结果，语义检查必须进入 A 复核或待审状态。
- [ ] 04. 为 A 生成证据包，包含实际成果位置、差异、缺口及验收映射。
- [ ] 05. 按 A 四种决定分别进入交付前门槛、返修、补证据或阻塞。
- [ ] 06. 将质量返修、连接重试和翻译重试分开计数，禁止彼此重置形成无限循环。
- [ ] 07. 实现同一缺陷两轮无进展升级 A、一次 B 自主修复最多三轮的版本化初始参数。
- [ ] 08. A 接管前取得写入权并保存快照，完成后再移交 B，避免双写。
- [ ] 09. 重放 B 误报完成、检查失败、A 定点返修、预算未接入和连续无进展案例。
- [ ] 10. 保存每轮缺陷状态及变更影响范围，确认修复后的版本重新验证才可继续。

**测试命令：** `python -m pytest tests/integration/test_agent_workflow.py -q`。
**预期：** 缺成果或缺证据不通过；返修不遗漏复验；达到上限保存状态并升级或停止。
**负例：** 把整个报告重生成但原缺陷未修、进程成功退出或 B 宣称完美均不得产生交付。
**证据：** `docs/acceptance/D014/workflow-traces.json`；`docs/acceptance/D014/repair-evidence.json`。
**完成条件：** 正常、补证、返修、升级、取消与阻塞路径均可重放；真实发布门槛缺失时不发布。
**失败回退：** 停在最后可核验版本，保留 A 决策及缺陷清单，再以新有界计划恢复。

## D015 用量归一化与预算

**目的：** 让节省可核对，阻止失败、翻译和重试消耗被隐藏。
**阶段 / 负责：** F5 任务执行；后端计量工程师；初估 10 工时。
**依赖 / 需求：** D007、D008、D014；R02、R14。
**输入：** 提供方原始用量事件；D014 各岗位/attempt；任务预算策略。
**准确拟建文件：** `services/orchestrator/app/usage/normalization.py`；`services/orchestrator/app/usage/ledger.py`；`services/orchestrator/app/usage/budgets.py`；`tests/unit/test_usage_ledger.py`。

- [ ] 01. 定义请求级账本主键及来源口径，记录 A/B、执行/翻译/复核岗位。
- [ ] 02. 逐提供方映射输入、输出、缓存和推理字段，标明哪些为父项与子项。
- [ ] 03. 将请求增量和会话累计计数分别处理，累计事件先做经核验的差分。
- [ ] 04. 对重复请求账单和迟到用量幂等合并，禁止同一请求相加两次。
- [ ] 05. 将未知、估算与服务商真实报告分开存储，未知不得填写零。
- [ ] 06. 累计失败、取消、接管、翻译修复和连接重试中的真实请求用量。
- [ ] 07. 在启动新步骤前评估剩余预算，配置预留额度并记录估算依据。
- [ ] 08. 预算达到上限时保存检查点并停止新请求，不能伪装通过或无限加预算。
- [ ] 09. 用重复 120 token、累计 120→200、缓存子项及缺失字段建立精确断言。
- [ ] 10. 生成按任务/领域/模型分组的账本报告，分母无合格交付时显示不可计算。

**测试命令：** `python -m pytest tests/unit/test_usage_ledger.py -q`。
**预期：** 重复 120 只计 120；累计 120→200 总计 200；无法核对的数据显式 unknown。
**负例：** 把缓存/推理子项再次加到已含该项的 total，或删除失败请求，都导致测试失败。
**证据：** `docs/acceptance/D015/usage-fixtures.json`；`docs/acceptance/D015/budget-report.json`。
**完成条件：** 原始事件可追到账本、账本可追到报表；预算停止真实执行且保留费用不确定性。
**失败回退：** 禁用无法验证的节省宣称，保留原始事件重新归一；预算未知走保守上限或暂停。

## D016 依赖版本失效

**目的：** 确保上游变化后，图表、译文、评审和交付资格不会沿用旧结论。
**阶段 / 负责：** F5 任务执行；后端版本工程师；初估 10 工时。
**依赖 / 需求：** D008、D013、D014；R05、R09、R12。
**输入：** 任务依赖图；不可变成果版本；A 批准与翻译关联记录。
**准确拟建文件：** `services/orchestrator/app/runtime/dependencies.py`；`services/orchestrator/app/storage/revisions.py`；`tests/integration/test_dependency_invalidation.py`。

- [ ] 01. 为每个成果记录具体上游版本 ID，不以最新文件名或修改时间推断依赖。
- [ ] 02. 创建数据→分析代码→结果→图表→报告的有向无环依赖 fixture。
- [ ] 03. 在登记依赖时拒绝自引用与环路，并给出可定位错误。
- [ ] 04. 源文件实质改变时创建新版本，保留历史字节和来源。
- [ ] 05. 沿依赖图标记受影响成果、译文、QA 和 A 批准为 stale。
- [ ] 06. 明确不受影响的独立成果保留有效性，避免全任务无差别重跑。
- [ ] 07. 在重新验收时核对所读取成果版本，禁止旧 PASS 对新版本生效。
- [ ] 08. 测试 v3 原件与 v2 译文混配，确认不能进入发布前 READY。
- [ ] 09. 在上游更改与发布并发时通过事务版本检查阻止过时交付。
- [ ] 10. 保存失效传播清单和复验结果，逐项确认历史交付仍可查看且不冒充最新。

**测试命令：** `python -m pytest tests/integration/test_dependency_invalidation.py -q`。
**预期：** 所有受影响下游失效且独立分支保留；旧译文/批准不会覆盖新版本。
**负例：** 仅比较文件名而接受不同版本、失效传播漏掉图表或批准均失败。
**证据：** `docs/acceptance/D016/dependency-dag.json`；`docs/acceptance/D016/invalidation-report.json`。
**完成条件：** 版本更改、分支、环路和并发检查通过，失效范围可审计。
**失败回退：** 暂停当前版本发布，回到最后完整有效版本供历史查看，按依赖重建受影响分支。

## D017 文件读取与执行作用域

**目的：** 把任务文件、角色写入权和工具调用范围限定在可核验边界，保护来源与跨任务隔离。
**阶段 / 负责：** F5 任务执行；后端边界工程师；初估 12 工时。
**依赖 / 需求：** D011、D013；R07、R09、R11、R12、R13。
**输入：** 任务合同；D011 进程工作目录；原件、A、B、翻译和证据目录划分。
**准确拟建文件：** `services/orchestrator/app/runtime/scopes.py`；`services/orchestrator/app/runtime/context_gateway.py`；`services/orchestrator/app/runtime/write_leases.py`；`tests/integration/test_task_scopes.py`。

- [ ] 01. 为每个 task/attempt 创建独立输入、A 决策、B 工作、翻译、证据和成果区域。
- [ ] 02. 将路径解析为规范绝对路径后校验所属根目录，拒绝越界相对路径。
- [ ] 03. 检查 Windows junction/symlink 与 UNC 路径策略，避免以字符串前缀代替真实范围验证。
- [ ] 04. 原件和证据区域设为只读或通过服务接口写入，B 无权覆写 A 决策。
- [ ] 05. 建立角色写入租约，A 接管和 B 继续必须完成显式移交。
- [ ] 06. 通过 context_gateway 提供给 Claude 经检查的英文视图引用，缺语言门槛不直接传中文自然语言。
- [ ] 07. 保护代码、公式和原始证据字形，语言层不能修改执行语义或原始数值。
- [ ] 08. 把源材料中的指令保留为资料，不允许改变工具权限、预算或验收合同。
- [ ] 09. 测试越界路径、重解析点、跨任务相同文件名、恶意日志和同时写入。
- [ ] 10. 记录无法在外部 App 强制的权限边界，拒绝将普通工作目录隔离描述为完整安全沙箱。

**测试命令：** `python -m pytest tests/integration/test_task_scopes.py -q`。
**预期：** 授权角色仅访问本任务允许区域；A 接管无双写；绕过语言/来源门槛的读取被阻止。
**负例：** 以 ../、junction 或其他会话路径读取文件，以及 B 篡改 A PASS，均拒绝。
**证据：** `docs/acceptance/D017/scope-matrix.json`；`docs/acceptance/D017/isolation-report.json`。
**完成条件：** 已实现的范围约束有故障测试，外部工具不可强制限制的部分明确记录并选择受支持运行方式。
**失败回退：** 停止该能力并保存工作区，收紧工具集合或采用可验证隔离执行环境，不隐瞒强制能力缺失。

## D018 公开事件投影

**目的：** 在服务端阻断内部文本进入普通聊天接口，保持必要中文错误与澄清可见。
**阶段 / 负责：** F6 后端集成；后端 API 工程师 + 桌面联调工程师；初估 10 工时。
**依赖 / 需求：** D007、D009、D010；R06、R08、R09、R10、R11、R12。
**输入：** D007 白名单；内部事件；经验证的回答/附件发布记录；当前轮路由快照。
**准确拟建文件：** `services/orchestrator/app/runtime/public_projection.py`；`services/orchestrator/app/api/public_events.py`；`tests/integration/test_public_projection.py`。

- [ ] 01. 定义 project_event(event: dict) -> dict | None，只接收已验证内部记录。
- [ ] 02. 将进度、工具、原始模型输出、翻译块和验证日志默认投影为 None。
- [ ] 03. 仅从批准的发布记录读取 answer.published 内容，禁止转发临时模型字符串。
- [ ] 04. 对 Claude 回答要求同源已检查中文内容，对 GPT 读取 native 路由批准内容。
- [ ] 05. 将 pending 仅投影为通用等待信号，不包含 A/B 阶段标签或英文片段。
- [ ] 06. 为失败和必要澄清建立中文公开文案及可操作动作，不附原始错误栈。
- [ ] 07. 公开附件仅提供 bundle/版本/格式/语言标识，文件配对引用来自正式发布记录。
- [ ] 08. 为历史、SSE 重连和增量事件共用投影函数，禁止历史回放绕过白名单。
- [ ] 09. 把内部英文 canary、密钥 canary、未知 event kind 和被取消旧答案送入所有公开入口。
- [ ] 10. 保存公开 JSON/SSE 字节级证据，确认没有先发英文再撤回的瞬时泄漏。

**测试命令：** `python -m pytest tests/integration/test_public_projection.py -q`。
**预期：** 公开接口无内部 canary；错误/澄清为中文；取消和过时答案不发送。
**负例：** 仅前端隐藏、在 HTML 调试字段塞原文或旧消息接口返回 raw_content_ref 均视为泄漏。
**证据：** `docs/acceptance/D018/public-payloads.json`；`docs/acceptance/D018/leakage-report.json`。
**完成条件：** 服务端所有公开入口共用白名单和发布门槛；真正翻译/附件服务未接入时对应成功事件保持不可用。
**失败回退：** 关闭受影响事件类型并呈现中文失败，不退回原始模型流。

## D019 领域验证器注册

**目的：** 把可机械检查项目与必须由 A 审核的语义项目分开记录，支持四类任务。
**阶段 / 负责：** F6 后端集成；领域验证工程师；初估 12 工时。
**依赖 / 需求：** D013、D016、D017；R01、R05、R09、R12。
**输入：** D013 验收项；固定成果快照；文档/运行工具能力报告。
**准确拟建文件：** `services/orchestrator/app/validation/base.py`；`services/orchestrator/app/validation/registry.py`；`services/orchestrator/app/validation/code.py`；`services/orchestrator/app/validation/paper.py`；`services/orchestrator/app/validation/document.py`；`tests/integration/test_validation_registry.py`。

- [ ] 01. 定义验证器输入为固定 artifact revision 与验收项，输出 pass/fail/not_verified/blocked。
- [ ] 02. 为结果记录验证器版本、命令或检查方法、环境、证据位置及耗时。
- [ ] 03. 实现 registry 能力查询，不存在的工具返回 unavailable 而非通过。
- [ ] 04. 注册代码构建/运行检查，测试生成成功不能替代测试实际通过。
- [ ] 05. 注册论文引用结构、数据复算和图表关联检查，来源支持论点仍交 A 语义审查。
- [ ] 06. 注册文档完整性、数字名称一致性及可打开/渲染能力检查。
- [ ] 07. 注册综合任务依赖版本一致性检查，结合 D016 阻止混版。
- [ ] 08. 把全文论证、事实证据充分性和整体设计判断明确列为 pending_A_review。
- [ ] 09. 运行损坏文件、缺工具、超时、虚构引用和缺数据负例，不补造验证结果。
- [ ] 10. 冻结四域最小 fixture 与结果报告，供 D020 垂直集成及后续专业扩展使用。

**测试命令：** `python -m pytest tests/integration/test_validation_registry.py -q`。
**预期：** 验证只对对应版本有效；机械/语义状态区分清楚；工具不可用不假通过。
**负例：** 引用编号存在却据此判断文献支持论点，或无真实实验却声明复算成功，必须被拒绝。
**证据：** `docs/acceptance/D019/validator-capabilities.json`；`docs/acceptance/D019/domain-results.json`。
**完成条件：** 四类任务都有明确机械入口与 A 待审清单，所有结果绑定证据和版本。
**失败回退：** 标记受影响验收项 blocked/not_verified，补齐工具或材料后重跑，不放宽强制要求。

## D020 后端垂直集成

**目的：** 将真实接入与状态、证据、用量、公开事件贯通，交付可供翻译和桌面模块接入的后端切片。
**阶段 / 负责：** F6 后端集成；后端负责人 + QA；初估 14 工时。
**依赖 / 需求：** D004、D005、D012、D014、D015、D016、D017、D018、D019；R01、R02、R03、R04、R05、R07、R08、R09、R10、R11、R12、R14。
**输入：** D004/D005 已验证入口；D006 可选连接状态；后端合同、工作流及验证器。
**准确拟建文件：** `tests/support/scenario_driver.py`；`tests/integration/test_backend_vertical.py`；`tests/fixtures/vertical_cases.json`；`docs/runbooks/backend-operations.md`；`docs/acceptance/backend-handoff.json`。

- [ ] 01. 实现测试专用 scenario_driver.py，接收 CASE、--root、--options，并只向 stdout 输出结构化结果。
- [ ] 02. 建立代码、论文、普通文档和综合四个可核验固定场景及独立临时工作区。
- [ ] 03. 连接 D009 API、D014 调度、D019 验证、D015 用量和 D018 投影并逐项核对事件。
- [ ] 04. 在 fake 场景验证正常、补证、返修、取消、重启及失败路线，记录每轮实际文件。
- [ ] 05. 在真实 Claude/ZCode 小任务中验证合同、成果证据和 A 判断，使用受控英文接入材料。
- [ ] 06. 对 Claude 正式中文任务检查语言网关缺失时保持阻塞，不因 fake 翻译通过而开启生产发布。
- [ ] 07. 若 GPT 已连接则执行 native 路线并断言零强制翻译；未连接明确跳过且不标该能力通过。
- [ ] 08. 运行上游改版、旧 PASS、重复消息、超预算和连接失败联合场景。
- [ ] 09. 生成后端交接报告，列出已通接口、未接入翻译/文档/GUI 门槛及真实能力范围。
- [ ] 10. 复核证据与用量后冻结后端合同版本，将运行和故障恢复步骤交给后续模块负责人。

**测试命令：** `python -m pytest tests/integration/test_backend_vertical.py -q`；`python tests/support/scenario_driver.py backend_vertical --root artifacts/qa/D020 --options '{"provider_mode":"fake"}'`；`python -m pytest -o addopts='' tests/integration/test_backend_vertical.py -m real_provider -q`。
**预期：** 后端切片可重放；真实连接有证据；缺翻译/渲染/发布能力的正式任务如实阻塞。
**负例：** fake 通过冒称真实全流程、把接入英文小任务当用户中文产品验收、断网标完成均不允许。
**证据：** `docs/acceptance/D020/vertical-report.json`；`docs/acceptance/D020/request-ledger.json`；`docs/acceptance/backend-handoff.json`。
**完成条件：** 可供后续组接入的后端服务与测试装置完成；不等于完整 GUI、双语文档或优化资格已完成。
**失败回退：** 回滚到最后通过的后端构建并保留数据库/原件；按失败接口拆分修复，禁止临时绕过语言和来源门槛。


