# 本地开发环境

所有命令从仓库根 `C:/Users/asd15/Documents/ChatGPT/ai` 运行。D002 当前验证 Windows 11 x64、Python 3.13.0、Node 24.19.0、npm 11.17.0 和 uv 0.13.0。`.python-version` 固定本轮开发解释器；后端包兼容范围为 Python `>=3.13,<3.14`，其他修补版本尚未实测。

Python 运行/测试依赖、setuptools 构建后端及 npm 直接依赖均固定确切版本。`uv.lock` 和 `package-lock.json` 固定解析结果。阶段二新增 Electron 44.7.0、React 19.3.0、TypeScript 7.0.2、pdfjs-dist 6.4.299，以及固定版本的 Markdown/OOXML/PDF 解析和渲染库。GUI、API、翻译和文件的实际测试见[阶段二报告](../acceptance/part-two-progress.md)，真实模型资格仍单独验收。

JSON Schema 测试使用 jsonschema 4.26.0 和最小的 rfc3339-validator 0.1.4；后者只放在 test extra，注册并执行 `date-time` 格式检查。应用运行时必须使用标准库校验时间输入，不能依赖仅供测试的解析库。

## 按锁重建

本机 uv 0.13.0 位于 `.tools/uv/Scripts/uv.exe`。其他开发机可使用已经安装的同版 uv，并将下列 uv 路径改为实际位置；不要为重建重新解析或自动升级依赖。

```powershell
& .\.tools\uv\Scripts\uv.exe sync --project services/orchestrator --locked --extra test --python 3.13.0 --no-python-downloads
& .\services\orchestrator\.venv\Scripts\python.exe -m pytest tests/unit/test_package_bootstrap.py -q
npm ci
```

`--no-python-downloads` 要求该解释器已安装；无需创建全局 Python 包。后端环境固定为 `services/orchestrator/.venv`，以后运行计划中的 Python 命令应使用该环境。明确解释器路径也可以替换 `--python 3.13.0`，本机验收使用 `.tools/uv/Scripts/python.exe`。

```powershell
& .\services\orchestrator\.venv\Scripts\Activate.ps1
python -m pytest tests/unit/test_package_bootstrap.py -q
```

无法激活时继续使用显式 `.venv/Scripts/python.exe`；不修改全局执行策略，也不将系统 Python 的测试结果与项目环境混用。

## 测试范围

`pytest.ini` 注册 `real_provider`、`windows`、`slow`，默认筛选 `not real_provider`，并拒绝未知标记和配置。D004–D006 的真实模型场景只有在账号、预算、隔离目录和试验范围就绪后才可明确启用，例如：

```powershell
& .\services\orchestrator\.venv\Scripts\python.exe -m pytest -o addopts='' tests/contracts/test_claude_adapter.py -m real_provider -q
```

真实试验须先核验当前二进制、账号与模型响应身份；既有历史成功记录不能替代新版本资格。普通离线测试不访问模型或凭证。

根 `test:e2e` 脚本调用真正的 Playwright CLI：

```powershell
npm run test:e2e -- --list
npm run typecheck:desktop
npm run test:desktop
npm run build:desktop:test
npm run test:e2e
```

默认配置排除 `*-real.spec.ts`、`*.real.spec.ts` 与 `real_provider` 目录。当前 E2E 启动实际 Electron 和实际 Python 服务，模拟连接仅替换外部模型响应。文件种子测试用于 UI/保存检查；调度器实际生成文件的集成测试独立保留，均不能替代真实模型证据。

`npm run test:e2e:real` 是真实测试入口；连接资格不齐时必须失败并说明阻塞，不能 skip 后宣称通过。本次默认注册数为零，因此不启动任何模型任务。DOCX 页面检查使用本机隐藏的 Word-compatible COM 导出（当前注册为 WPS），再核实际 PDF 字节与页面；其他机器缺该能力时明确阻断 DOCX 完整发布，不自动降级格式。

## 依赖故障恢复

离线缺包时保留锁和安装错误，等待正常访问 PyPI/npm/Electron 发布资源后重跑相同命令。`uv sync --offline --locked` 只适用于本地缓存完整的情况；缓存缺失不是工程通过证据。

下载、文件占用或安装失败时先读取实际退出码和日志，确认没有正在安装的进程。可在新的隔离源码目录创建环境重试；不删除用户工作区，不用自动升级、跳过 integrity 或全局安装掩盖错误。

出现 `--locked` 需要更新或 `npm ci` 锁不同步时，先检查包清单与最后核验的锁是否一致。恢复最后通过的配置/锁并重建；只有明确的依赖变更才能重新生成锁，变更后重做兼容和源码快照验证。

包安装完成但 `import app` 失败时检查 `pyproject.toml` 的 `app` 包发现、当前解释器和 editable 安装来源；不能靠追加临时 `PYTHONPATH` 掩盖包遗漏。

## 工程复验与证据

D002 最终独立快照保留在 `.tools/d002-snapshots/clean-20261013-v3`（v3 补齐 D007 独立审查发现缺失的 `date-time` 检查依赖）。首次重建前显式复制源码/包清单/锁，不含 `.venv`、`node_modules`、`.git` 或 `.superpowers`。仓库当时无初始提交，故这是干净源码快照验证，未声称已完成 Git clean checkout。

运行实际环境记录脚本：

```powershell
& .\services\orchestrator\.venv\Scripts\python.exe docs/acceptance/D002/collect-environment.py
```

完整结果见 `docs/acceptance/D002/implementation-report.md`、`runtime-versions.json` 和逐条命令日志。负例在单独快照篡改包发现或锁，保留非零结果；根源码与锁保持验收版本。所有记录无模型凭证或模型调用。
