# 协作工作台

2026-10-16 新增智能体协作桥：通用「A 推理 → B 执行」双智能体工作流（`apps/bridge-client/`，对话式网页 + 项目/对话线程 + 执行直播），两端可按接口插拔任意具备无头 CLI 的智能体；当前默认配置 A=Kilo、B=ZCode 会话（文件队列取件），也可切换为 Kilo/Codex 等无头直执。接入与成本见 [智能体桥运行手册](docs/runbooks/kilo-bridge.md)。

**范围 v2（2026-10-16）**：本软件仅限用户本人在本机直接使用，不发行、不分发、不做代码签名；未签名内部包（阶段三交付）即最终交付形态。发行/签名/试用/交接专属任务卡（D052/D053/D056/D057/D060）已按 [DEC-010](docs/decisions/scope-v2.md) 取消，质量、语言、恢复等全部产品行为标准不变。直接使用仍差两个前提：Claude Code 登录（D004）与 B 侧入口路线选择（D005，见[复检报告](docs/acceptance/D004-D005-recheck-20261016.md)）。

阶段五本地更新：已交付工单与提示词体系及本地协议验证（final-v3，2026-10-15），所选本地检查 10/10 通过、源码一致性验证通过；回归为 Python 1702、桌面单元 88、实际 Electron 35 项通过，类型检查、桌面构建与契约严格检查全部通过。真实提供方、人工、完整产品、正式发布和优化目标保持未验收。见[阶段五证据](docs/acceptance/part-five/final-v3/summary.md)。

2026-10-16 真实接入复检：D004 维持 blocked（Claude Code 2.1.296 `auth status` 仍 `loggedIn:false`，需用户本人登录）；D005 维持 blocked 但根因已精确化——CLI 0.16.9 无头 `--prompt` 入口无法携带模型选择（无对应参数、不读取 `defaultModelSelection`），`app-server` 协议入口的 `session/create` 已验证可达注册表查找，但独立实例的注册表不含账号提供方（账号实体化依赖桌面宿主握手）。见[复检报告](docs/acceptance/D004-D005-recheck-20261016.md)。

阶段四本地更新：已修复启动发布恢复、停止与取消竞争、A验收证据读取、失败用量绑定及Windows备份占用提交，并新增逐步验收入口。最终回归为Python 1595、桌面单元88、实际Electron35项通过，48项所选本地机械映射通过；完整SOP、真实接入、人工与发布终验保持开放。见[阶段四报告](docs/acceptance/part-four-progress.md)。

阶段三本地更新：已交付验收装置、质量门槛、桌面备份恢复、更新协调器、内部未签名Windows包与运维控制器。本轮最终回归为 Python 1489、桌面单元 84、实际Electron 35 项通过；完整真实/人工/签名终验保持开放。见[阶段三报告](docs/acceptance/part-three-progress.md)。

阶段二冻结更新：未完成的 D021–D040 已冻结并暂停推进，逐卡遗留、源码与证据快照见[冻结说明](docs/acceptance/part-two-freeze-20261014/FREEZE.md)。

Windows 优先的本地桌面 AI 协作工作台，目标与验收合同见 [DESIGN.md](DESIGN.md) 和 [执行总纲](docs/superpowers/plans/2026-10-13-execution/00-execution-guide.md)。

部分一保持[冻结记录](docs/acceptance/part-one-freeze-20261014/FREEZE.md)。阶段二已增加 Electron/React 桌面、中文输入法与会话材料、语言路由和全文翻译门槛、A 完整原件捕获、双语文件发布、用量/存储/诊断页面，以及可复算的综合用例。逐项实现、测试结果与剩余验收见[阶段二报告](docs/acceptance/part-two-progress.md)。

从仓库根按 [开发手册](docs/runbooks/development.md) 重建环境。D002 的实际命令、退出码、运行版本及源码快照复验记录位于 [工程验收报告](docs/acceptance/D002/implementation-report.md)。默认测试排除真实外部模型，不产生模型调用费用。

桌面从仓库根运行 `npm run build:desktop` 后执行 `npm run desktop`。当前生产模型注册表为空，界面会显示连接不可用；实际 Claude/ZCode 与 GPT 当前生命周期资格仍待补齐。`npm run desktop:demo` 使用明确标记的模拟模型响应，执行实际本地调度、存储和公开消息路径，可用于操作检查，不能计作真实模型验收。

桌面与目录迁移步骤见[桌面运行手册](docs/runbooks/desktop-operations.md)，后端恢复见[后端运行手册](docs/runbooks/backend-operations.md)。默认测试排除真实外部模型；本次没有新增真实模型调用或质量/token 节省声明。
