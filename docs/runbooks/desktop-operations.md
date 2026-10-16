# 阶段二桌面运行

在仓库根安装锁定依赖后运行。实际命令、验证结果和尚未通过的任务门槛以 `docs/acceptance/part-two-progress.md` 为准。

```powershell
npm run build:desktop
npm run desktop
```

默认以真实模式启动。尚未具备资格的连接在连接页显示不可用，不能发送；配置名称和安装命令不构成模型身份或执行能力证明。当前第一部分真实验收仍未完成。

本地界面演示使用显式入口：

```powershell
npm run desktop:demo
```

演示仅替换外部模型响应。会话、附件、规划、B 执行、C 检查、A 审查、发布、SQLite 和公开消息传输使用实际产品模块；演示回答与合成用量必须保留演示标识。不得用该入口的结果证明真实模型质量、token 节省或 D040 通过。

中文输入法组合输入期间 Enter 不发送；草稿和同会话历史持久保存。上传文件经主进程选择并绑定会话。PDF/DOCX 的结构无法完整解析时需要补充材料，不能截取正文后当作完整输入。

文件卡只列出已发布、通过字节/版本/来源门槛的完整 bundle。英文原件来自实际完整 A 响应，中文译文经全文对齐和 QA。保存操作使用系统对话框；保存两份固定同一配对版本，重名或写入失败明确提示，不能覆盖成品后报成功。

目录迁移要求没有运行中、待核对或等待材料的任务，目标须空且不能与原目录重叠。预检后再核验数据库和每个文件，随后由主进程检查点保存并重启后端。原目录保留；迁移失败继续原目录。不要在程序运行时手动搬动数据库或 blob 文件。

关闭窗口按偏好最小化或退出。退出先要求后端保存检查点，再仅结束本应用托管的进程。后端离线时保留草稿并提供重连状态；不能以页面显示完成代替后端发布记录。

用量页包含失败、返修、翻译和执行请求。未知数显示不可得；缓存口径按提供商区分，不把缓存子集再次加到总数。诊断 ZIP 仅含允许的状态与计数，不包含会话正文、凭据或原提供商帧。

验证命令：

```powershell
npm run typecheck:desktop
npm run test:desktop
npm run build:desktop:test
npm run test:e2e
& .\services\orchestrator\.venv\Scripts\python.exe -m pytest -q
& .\services\orchestrator\.venv\Scripts\python.exe scripts/check_contracts.py --strict
& .\services\orchestrator\.venv\Scripts\python.exe scripts/phase_two_preflight.py
```

普通测试排除真实模型。真实入口必须具备真实连接、预算、资格和隔离目录；缺一项记未通过。四类冻结输入见 `docs/acceptance/vertical-scenarios.json`，当前资格见 `docs/acceptance/part-two/real-readiness.json`。
