# D002 工程基础实施报告

验收记录时间：2026-10-13 19:03（Asia/Shanghai；包含 D007 独立审查后的时间格式检查依赖修复）。分支：`codex/part1-foundation`。仓库尚无初始提交，提交标识为 null；本任务未提交。状态：D002 工程实现及本卡验证完成，供主协调代理独立复核。此状态不表示完整产品或 R12/R13 已通过。

## 需求及范围

已读取 D001 的 `requirements-v1.json`、`scope-v1.md` 和 `decision-log.md`。基线为 v1，状态 `frozen_for_implementation`，十五项需求齐全；产品验收为 `not_verified`。D002 对 R12/R13 建立可安装、可收集测试、可按锁复建的工程先决条件，没有把恢复、签名安装或模型能力填写为已完成。

本次创建 npm workspace、桌面包清单、Python `app` 包、依赖锁、pytest/Playwright 配置、开发手册和工程验收记录。原设计/计划/任务板保持原文件；未创建 GUI、API 或统一协议占位。未读取模型凭证、登录、调用真实模型或改动全局 Python 环境。

## 实现选择

| 项目 | 确定配置 / 实际版本 | 依据及边界 |
| --- | --- | --- |
| Python | 实际 3.13.0；`.python-version` 固定 3.13.0；包支持 `>=3.13,<3.14` | 本轮实际开发机，允许后续修补版；其他修补版未实测 |
| uv / 构建 | uv 0.13.0；setuptools 84.0.0 | 项目 uv 版本严格匹配；setuptools 由实时 PyPI 元数据确认并完成隔离 editable 构建 |
| Python 运行依赖 | FastAPI 0.143.0、Pydantic 2.14.1、uvicorn 0.54.0 | 上游当前版本核对后固定确切版本，31 个解析包由 `uv.lock` 固定 |
| Python 测试依赖 | pytest 9.1.1、httpx 0.28.1、jsonschema 4.26.0、rfc3339-validator 0.1.4 | jsonschema 为 D007 跨语言 JSON Schema 验证提供测试装置；rfc3339-validator 为已证实缺失的 date-time 检查器提供最小依赖，均在 test extra |
| Node / npm | 实际 Node 24.19.0、npm 11.17.0 | 根 engines 与 packageManager 固定本轮版本 |
| 桌面直接依赖 | Electron 44.7.0、React/react-dom 19.3.0、TypeScript 7.0.2 | 只锁定清单和安装；尚无桌面功能或打包成果 |
| Playwright | `@playwright/test` 1.64.0；`test:e2e = playwright test` | 真正 CLI，未以空测试当通过；默认排除明确命名的真实模型场景 |
| 包发现 | setuptools 发现 `app` 和 `app.*` | 从仓库根导入来自项目 editable 安装，无临时 PYTHONPATH |

选择结果及来源链接在 `runtime-versions.json`。依赖安装结果仅证明 D002 工程兼容性，不能替代后续产品、CLI、模型、文档或 GUI 实测。Vite 等未来桌面实现所需工具由对应任务再按需锁定。

## 十项操作核对

| 操作 | 实施与证据 |
| --- | --- |
| 01 工程目录与包标记 | 已建立 `apps/desktop`、`services/orchestrator/app`、`tests/unit`；`app/__init__.py` 仅有包说明 |
| 02 包发现与依赖组 | `pyproject.toml` 声明运行依赖、test extra、包发现和固定构建后端 |
| 03 工具版本选择 | `runtime-versions.json` 记录实际平台、解释器、Node/npm/uv、安装版本和来源 |
| 04 Python 锁与解释器 | `uv.lock` 已生成；根项目与全新快照使用 `sync --locked --extra test` 成功 |
| 05 npm workspace、锁及 E2E 命令 | 根/桌面两份清单、锁文件、Playwright CLI 配置已建立；`npm ci` 成功 |
| 06 pytest 标记和安全默认值 | 注册 real_provider/windows/slow；严格标记与配置；实测默认选择排除 real_provider |
| 07 缺包引导负例 | 首先只写 bootstrap 测试，在 `.tools/uv` Python 运行，因缺 app 真实失败，exit 1；再建立包 |
| 08 干净虚拟环境引导 | 首次项目 `.venv` 由 uv 建立；最终 bootstrap 1 passed，exit 0 |
| 09 独立源码重建 | 新快照初始不含 `.venv/node_modules/.superpowers`，Python/npm 按锁重建；15 个源码/锁/验证文件哈希均与根一致 |
| 10 故障恢复说明及基线复核 | 开发手册记录离线缺包、安装失败、锁冲突、包遗漏的恢复；按主协调代理集中复核安排暂未创建 Git 提交，工程基线以源码快照和哈希记录 |

## 实际验证

下表中的命令均已执行。uv 使用根 `.tools/uv/Scripts/uv.exe`，Python 测试使用各自 `services/orchestrator/.venv/Scripts/python.exe`。完整输出/退出码保存在同目录日志。

| 验证 | 命令 / 工作目录 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 首次 red | `.tools/uv/Scripts/python.exe -m pytest tests/unit/test_package_bootstrap.py -q`，根 | 1 failed，`ModuleNotFoundError: No module named 'app'`，exit 1，预期负例 | `bootstrap-red.log` |
| 锁生成 | `uv lock --project services/orchestrator --python <本机3.13.0解释器> --no-python-downloads`，根 | 解析 31 包，exit 0 | `uv-lock.log` |
| 根 Python 同步 | `uv sync --project services/orchestrator --locked --extra test --python <本机3.13.0解释器> --no-python-downloads`，根 | 成功且锁哈希不变，exit 0 | `uv-sync.log` |
| 根 bootstrap | 项目 Python `-m pytest tests/unit/test_package_bootstrap.py -q`，根 | 1 passed，exit 0 | `bootstrap.log` |
| 测试收集 | 同解释器 `-m pytest tests/unit/test_package_bootstrap.py --collect-only -q`，根 | 1 test collected，exit 0 | `test-collection.log` |
| npm 首次安装 | `npm install`，根 | 成功生成锁；22 packages added / 24 audited，exit 0 | `npm-install.log` |
| 根 npm 重建 | `npm ci`，根 | 成功，锁哈希不变，exit 0 | `npm-ci.log` |
| 快照 Python 重建 | 与根相同 `uv sync --locked` 参数，最终全新快照 | 首次创建 `.venv`，安装 31 包，锁哈希不变，exit 0 | `snapshot-uv-sync.log` |
| 快照 bootstrap | 快照项目 Python `-m pytest tests/unit/test_package_bootstrap.py -q` | 1 passed，exit 0 | `snapshot-bootstrap.log` |
| 快照 npm 重建 | `npm ci`，最终全新快照 | 成功，锁哈希不变，exit 0 | `snapshot-npm-ci.log` |
| pytest 默认真实标记排除 | 快照临时 marker probe，一项普通测试与一项必抛错 real_provider 测试 | 1 passed / 1 deselected，exit 0；没有模型调用 | `default-pytest-selection.log` |
| Playwright 默认真实文件排除 | `npm run test:e2e -- --list`，快照临时配置 probe | 只列普通配置控制项，未收集必抛错的 `configuration-real.spec.ts`，exit 0；仅列表，没有 GUI 测试执行 | `default-playwright-selection.log` |
| 根 GUI 测试尚缺 | `npm run test:e2e -- --list`，根 | `No tests found`，0 tests，exit 1，预期未实现 | `e2e-collection.log` |
| 源码快照对账 | 根源码、快照源码与 manifest 的 SHA-256 比较 | 15 项 source_matches_snapshot / snapshot_unchanged 均 true，exit 0 | `source-snapshot-reconciliation.json` |

## 隔离负例

负例只改 `.tools/d002-snapshots/` 下的指定文件，根工程和最终锁未被篡改。

| 反例 | 实际拒绝结果 | 证据 |
| --- | --- | --- |
| 包发现故意排除 app | 按锁安装可以完成，但 bootstrap 因缺 app 失败，exit 1，证明该测试能抓到包遗漏 | `negative-package-sync.log`、`negative-package-discovery.log` |
| uv.lock pytest 元数据与清单不一致 | `uv sync --locked` 拒绝更新，exit 1；未用无锁重建掩盖问题 | `negative-uv-lock.log` |
| npm lock React 版本改为 0.0.0 | `npm ci` 拒绝：lock react@0.0.0 不满足 react@19.3.0，exit 1 | `negative-npm-lock.log` |

npm 反例装置初次使用 PowerShell 对象解析器时遇到合法空字符串键限制，定位后改用 `ConvertFrom-Json -AsHashtable` 并从根锁重新制作，最终日志仅报告正确的 React 单字段篡改反例。装置错误没有被当作业务覆盖证据。

## 独立快照与锁

最终快照：`C:/Users/asd15/Documents/ChatGPT/ai/.tools/d002-snapshots/clean-20261013-v3`。明确复制 15 个工程/测试/文档/时间校验文件，不复制环境、已安装包、Git 或代理任务资料。`snapshot-manifest.json` 记录首次安装前无 `.venv`、无 node_modules、无 `.superpowers` 及源文件哈希。旧 v2 快照保留作历史。

仓库尚无初始提交，本轮用可核对源码快照替代 clean Git checkout；没有声称 Git 检出验证已执行。快照与负例目录保留在被忽略的 `.tools`，未删除用户目录。

- `services/orchestrator/uv.lock` SHA-256：`decfba37bd2e2c4a5258749794806b1bf82ac56b42d73da767f28022e68dcea7`。
- `package-lock.json` SHA-256：`e45ee2de1a15400a992949746bed35cd4f495e884cd8a04ce76f4c1410cefc41`。

## 仍需后续验证

D002 没有未解决的工程安装阻塞。GUI、API、真实 Claude/ZCode/GPT 接入、翻译与双语文档、恢复/取消业务、完整备份、签名安装/更新以及质量/token 优化资格尚未由本卡建立或验收。真实调用为 0、凭证读取为 0；不将空 E2E、模拟配置检查或依赖安装通过写为产品通过。离线缺包与网络/占用/安装故障的恢复方法已登记，未声称做过离线下载或全部安装故障注入。

## D007 独立审查修复：date-time 检查器缺失

2026-10-13 的独立审查实际发现 jsonschema 4.26.0 基础安装未注册 `date-time`。FormatChecker 对未注册格式会跳过检查，先前只安装 jsonschema 不能证明时间字段已校验。根环境复现断言失败并保存 `date-time-red.log`（exit 1）；该确凿问题使旧 D007 边界验证结论需要重跑。

实时只读访问官方 PyPI 元数据，核验 rfc3339-validator 当前版本为 0.1.4，记录在 `rfc3339-upstream-metadata.json`。本次只新增确切 `rfc3339-validator==0.1.4` 到 test extra及其锁定依赖 six 1.17.0，没有引入批量 format extras，没有改运行依赖。应用时间输入应由标准库或已有运行时验证完成，不依赖 test-only rfc3339 库；本任务未覆盖或修改 D003/D007 源码及测试。

根环境和全新 v3 快照均执行 `verify-date-time.py`，实际确认 `date-time` 已注册。七个样例：合法 Z、合法 +08:00 和合法闰日通过；无时区、2月30日、非法13月及非时间文本全部拒绝。证据为 `date-time-green.log` 与 `snapshot-date-time.log`，两次退出码均为 0。新的源码快照仍从无 `.venv/node_modules` 状态按锁安装，旧包发现/uv锁失配/npm锁失配三个反例在 v3 中重新拒绝（exit 1），公开测试默认排除设置重新验证。

先前 v2 的 uv.lock 哈希为 `52d948d781b60017bdc6ea23b48cb000cb9050ccd387a32ce2226f7ad3420f9d`，现在以本报告 v3 哈希和 `runtime-versions.json` 为准。npm 包清单、桌面清单、Playwright 配置和 package-lock 四项保持原哈希，见 `npm-sources-unchanged.json`。该修复不产生模型调用、凭证读取或全局安装。D007 边界与根测试全集的最新结论由主协调代理鲜跑并独立复核，不引用修复前的 138 passed 作为修复后证据。
