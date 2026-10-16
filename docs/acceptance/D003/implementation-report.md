# D003 只读能力探测实施记录

日期：2026-10-13（Asia/Shanghai）。状态：`in_review`。本记录只证明只读探测与安全门控已实现和验证，未证明任何真实模型连接。未提交 Git；源码处于当前工作区，哈希见 `source-manifest.json`。

本卡修改范围：`services/orchestrator/app/providers/probe.py`、同目录 `__init__.py`、`scripts/probe_provider.py`、`tests/contracts/test_readonly_probe.py`、`docs/acceptance/local-capabilities.json` 和本证据目录。未修改依赖、pytest 配置、任务板或用户配置。

## 实现与验证

- 只读执行器仅接受固定工具和版本/帮助参数白名单；使用原生 executable 参数数组、`shell=False`、关闭 stdin、15 秒超时和隐藏窗口。未知工具、额外参数、脚本 shim 和 ZCode GUI 执行请求在启动前拒绝。
- 帮助输出只保存有关能力的短摘要与实际命令，版本只保存解析结果。令牌/密钥字段与 Bearer 内容被删去；stderr、完整环境、账号配置和完整帮助正文不写入证据。
- `classify_probe` 返回 `verified/unknown/mismatch`。除了经核验来源标记，身份证据还须存在、字节哈希匹配，且模型、请求、连接和适配器字段与报告一致。来源真实性仍由受信适配器采集保证，哈希不能代替真实来源。App 名称、别名和 profile 中的身份声明不能获得资格。
- Profile 读取只接受声明的非秘密元数据字段。默认不执行；真实执行要求明确的 `--execute` 和正整数 `--max-runs`。JSON 不能设置 shell 命令、环境、密钥或身份资格。
- 当前没有注册任何生产模型请求执行器；`--execute --max-runs 3` 仍返回非零 `not_connected / SUPPORTED_EXECUTOR_NOT_ENABLED`，不会猜测 Claude/ZCode 的启动参数。未来受信适配器还须提交绑定的非交互和隔离工作目录能力证据。
- 执行次数在调用受信适配器前扣除，失败不重置。每个执行器调用必须最多启动一个请求；后续适配器的重试也必须经该门控。假执行器请求 8 次、上限 3 时实际只进入 3 次。返回身份必须与所选 profile 的模型族、适配器、连接和精确模型 ID 匹配，失配立即停止后续启动。

正式测试解释器：`services/orchestrator/.venv/Scripts/python.exe`，Python 3.13.0。最终运行：

```powershell
& 'services/orchestrator/.venv/Scripts/python.exe' -m pytest tests/contracts/test_readonly_probe.py -q
```

实际结果：退出码 0，**53 passed**。`probe-red.log` 的首组业务红灯为 25 failed / 14 passed；新增版本/帮助解析、profile 身份绑定、GUI 只读元数据与畸形字段反例分别保存在 `probe-parsing-red.log`、`probe-binding-red.log`、`probe-gui-red.log`、`probe-schema-red.log`，最终结果在 `probe-green.log`。这些测试使用假外部命令或假模型执行器，验证的是门控行为，不能作为真实连接证据。

4 个 Python 源码文件通过标准库 `compile` 语法检查，退出码 0，见 `python-syntax.log`。项目环境未安装 Ruff，尝试的静态检查未执行（`static-check.log`），未安装全局或额外依赖，也没有把该缺失算作业务负例或通过。

## 本机实际观察

| 工具 | 实际事实 | 能力边界 |
| --- | --- | --- |
| Python | 项目虚拟环境 3.13.0 | 原生 `--version` 成功 |
| Node | `C:/Program Files/nodejs/node.exe`，24.19.0 | 原生 `--version` 成功 |
| npm | 安装的 npm package 元数据 11.17.0 | 不执行 `.cmd` wrapper |
| Codex | 已见原生 CLI 0.160.0 | `--version/--help` 成功；help 提及 `exec`、`--cd`、`resume`、`--model`，只代表文档线索 |
| Claude Code | PATH 和 `~/.local/bin/claude.exe` 未找到；已知本地 Claude GUI 目录也未找到 | 当前 `unavailable`；不等于证明全盘没有其他安装 |
| ZCode | 注册表显示 3.15.1；开始菜单 `ZCode.lnk` 指向 `D:/zcode/ZCode.exe`；只读 PE 文件版本为 3.15.1.8093 | GUI 文件存在，未启动；未找到可信自动 CLI，GLM 身份、工具、取消、恢复和用量均 `unknown` |
| Pandoc / LibreOffice / Tesseract | PATH 和已知安装目录未找到 | 转换和 OCR 能力 `unavailable` |
| pdftotext | MiKTeX 内存在该 executable | 无 PE 版本资源；未执行，PDF 处理能力 `unknown`，避免触发第三方安装行为 |

实际只读探测命令：

```powershell
& 'services/orchestrator/.venv/Scripts/python.exe' -m app.providers.probe --read-only --output docs/acceptance/local-capabilities.json --zcode-gui 'D:/zcode/ZCode.exe'
```

退出码 0，生成 42 项能力记录，每项具有 `path/version/help_source/capability/status/evidence_ref`，并分别列出事实、推断、待验证事项。只启动 4 条白名单命令（Python/Node/Codex 版本及 Codex 帮助），**真实模型请求 0，GUI 启动 0**。ZCode 快捷方式与相关卸载条目的 `DisplayIcon` 只读取路径/元数据；未执行卸载命令。`DisplayIcon` 未提供可提取的 executable 路径。

证据：`probe-trace.json`、`installation-metadata.json`、`readonly-run.log` 和上一级 `local-capabilities.json`。快照只记录相关卸载条目的 DisplayName/InstallLocation/DisplayVersion，不读取登录、密钥或用户 provider 配置。

## D004–D006 待补条件

Claude 缺少已见可用入口；ZCode 当前只有 GUI 安装依据；Codex 的实际模型、权限、会话、用量和登录状态尚未验证。桌面与 CLI 是否共享会话、登录、额度全部保留 `unknown`。需在受支持入口、账号和有界预算就绪后实现对应受信适配器，再进行明确授权的真实实验。本卡没有真实模型调用、账号操作、安装、升级或提交。
