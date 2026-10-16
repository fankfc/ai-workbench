# 阶段二实施与验收

阶段二冻结更新：按用户指令冻结 D021–D040 的未验收部分，暂停继续开发。18 in_progress、D024/D040 blocked 保持原状态；源码、依赖、逐卡遗留及验证记录已归档。见[冻结说明](part-two-freeze-20261014/FREEZE.md)。以下测试结果属于冻结前已执行批次。

日期：2026-10-14（Asia/Shanghai）。本报告沿第一部分冻结成果执行 D021–D040。本地核心路径已实现并通过功能回归；阶段二全部完成资格仍未满足，真实连接和人工评审继续阻塞。

第一部分的历史冻结不变：17 张卡 done，D004/D005/D020 blocked；冻结批次 1143 passed / 1 failed。冻结说明和原始源码哈希保留在 `part-one-freeze-20261014`。本次未提交：仓库仍是没有初始提交的 `codex/part1-foundation`，通过源码清单与实际命令日志标识版本。

## 已落地的产品路径

- Electron/React 桌面使用隔离 preload 和业务 IPC，主进程独占认证令牌及系统目录。实际托管 Python 回环服务、动态端口、健康身份检查、单实例、检查点与仅清理自身进程已实现。
- 聊天支持中文输入法、草稿恢复、追问历史、材料上传、会话搜索/置顶/归档、公开事件回放与取消状态。连接展示使用实际注册和身份资格；默认真实注册表为空，不显示虚假的可用状态。
- 每轮语言快照冻结实际身份与配置。Claude 分支在输入全文/材料英译 READY 后才发 A 请求，完整 A 英文定稿中译 QA 后才公开；GPT 原语言路径强制译者为零。三候选上限、预算、未知请求恢复、术语内容缓存、独立检查报告及失效机制均持久化。
- 文件原件绑定已完成 A step/request/event/原始正文；B 草稿、PASS-only、自报作者、截断或不同版本均不能成为原件。Markdown/PDF/DOCX 真实字节、内容/字体/页面及哈希通过后，同一次批准原子提交回答和完整文件组。
- 文件卡使用限定 artifact ID 的预览/保存，PDF/DOCX 页面在本地 PDF.js canvas 绘制。英文/中文或 GPT 单语言格式和版本可核，重名、取消、部分回滚失败明确显示。
- 用量包含失败/返修/规划/翻译，未知保持 null；缓存子集和额外输入分别记录，没有对照基准时节省值为空。脱敏诊断、引用保护清理和预检→SQLite backup→逐文件校验→后端重启的目录迁移已实现，原目录保留。
- 编程/论文/文档 profile 冻结必要输入和 A/C 条件。混合数据任务使用首版固定四行、同年一月/二月的 CSV 程序实际计算，独立 Decimal 复算、生成图表、A 定稿、文件发布；正常提交入口交付 CSV/代码/图表与报告，两版本旧包可历史下载。

## 验证层次

普通测试仅用明确标记的模型响应 fixture 替代外部 A/B 请求；GUI、API、调度、SQLite、作用域、代码计算、翻译门槛、文档渲染、下载与保存使用实际产品代码。这证明机械功能，不证明真实模型质量、语义等效或节省。

全量 Python 回归 1318 passed、0 failed、0 errors、0 skipped，1 项 real_provider 按默认规则排除。实际输出/JUnit/命令退出码在 `part-two/final-python.log`、`final-python.xml`、`final-python.json`；后端测试前后源码清单为 `final-backend-source-before.json` 和 `final-backend-source-after.json`。此前 1233/3 的中间失败、以及展示修正前的 1318/0 均保留，不能替代当前最终记录。

最终全量用时 231.05 秒。后端源码 hash `30b7567c862172887774d62ec9a6fe03b7abf06047a36b65c5b6e126d469c697`，完整源码 hash `e0cafffec582c043ce435f622ce6543a379b4bbfcaf8787f009104e94b21e599`；前后均一致。统一机器结果为 `part-two/verification.json`。

桌面全量 27 单元、28 实际 Electron E2E 通过；root 再核 27 单元/类型检查/正式与测试构建，附件过滤范围修正后正常文档/缺材料/论文代码材料/综合提交的 4 项实际 GUI 通过。对应日志为 `desktop-unit-green.log`、`desktop-e2e-green.log`、`root-desktop-*.log` 和 `root-task-profiles-e2e.log`，结构化结果为 `desktop-verification.json`。PDF/DOCX 预览有实际 canvas 像素和页面截图，文件保存逐件核 SHA-256。

`scripts/check_contracts.py --strict` 返回 `CONTRACTS_OK:version=1.0;schemas=2`；后端 wheel 构建成功并核对 4 号迁移、新 profile、澄清和综合模块确实包含在包内。Node/Python 版本为 24.19.0/3.13.0。PyMuPDF/Starlette 弃用和前端大 chunk 警告保留，未通过 skip/降低完整性门槛绕开它们。

独立审查报告：`part-two/independent-backend-review.md` 和 `part-two/independent-desktop-review.md`。后端 3 P1/3 P2、桌面 4 P2 均已修复并由原审查者复核；后端 24 项、桌面原生复现及 12 单元/2 GUI/1 日期 API 定向检查通过，限定修复范围未发现剩余重要缺陷。相应反例与复测日志独立保留。各 lane 实施记录为 `desktop-report.md`、`translation-report.md`、`documents-report.md`。

澄清新增独立受信发布：实际完成 A 响应→完整中文翻译/QA→同事务必要问题事件及双语历史；GPT 英文问题保留原文、译者为零。公共 `input.required.language` 从仅 zh-CN 向后兼容扩展为 zh-CN/en；Claude 仍由后端强制中文门槛。取消后已返回的 B 用量先留账，术语缓存冻结 task/domain/内容 hash，原件附件和派生全文同时核字节/覆盖/作用域。

## 真实验收与能力边界

本轮真实模型调用 **0**。默认生产服务实际配置数/注册数 **0**，D024 与 D040 仍 blocked。第一部分 GLM 生成 POST405、Claude 真实链路未完成以及 GPT 当前限制/生命周期资格缺口继续保留；未以旧二进制记录或 fixture 开放真实发布。四域冻结输入和当前真实门槛在 `vertical-scenarios.json` 与 `part-two/real-readiness.json`。

完整真实 GUI 四域链路、取消/崩溃恢复的真实提供方矩阵、双语金标准人评及领域评审尚未完成；A/B 模型自评不代替这些裁决。真实 E2E 当前是生产资格/冻结输入预检；完整真实附件、产物与故障恢复断言仍需装配和验收，不能因收到公开答案就通过。缺资格时报告 BLOCKED，不把模拟结果或 skip 当通过。

首版复杂 Markdown 数学/脚注/有序或嵌套列表、DOCX 修订/公式/复杂表及未核验资源、扫描/OCR/跨栏 PDF 等明确阻断完整交付，不把部分抽取当全文。DOCX 视觉导出使用本机 Word-compatible COM（当前注册为 WPS），实际 PDF 再做独立字节和页面核验；其他机器缺字体/导出器时保持 blocked。

代码 profile 的 build/tests 要求可信且已核验的执行端口，普通目录和 AST 解析不构成执行资格。尚未注册的执行能力必须阻断；综合用例只运行服务固定哈希程序，不执行任意模型代码。首版附件类型为 UTF-8 txt/md/csv/json 及 PDF/DOCX；原始 py/ts/js 未支持，不在选择器虚列为可导入。代码材料可用文本或 fenced Markdown 表示。

Narrator/真实 Windows 输入法人工录屏、全部低空间/文件占用/多页/崩溃恢复矩阵及跨机器字体/Office 可用性仍未全部覆盖。D021–D039 不能因局部机械回归整批置 done；逐卡完成与剩余项见 `part-two/task-results.json`。没有质量等效或 token 节省结论。

## 启动与继续

从仓库根执行 `npm run build:desktop`，然后 `npm run desktop`；真实连接未就绪时界面显示不可用。`npm run desktop:demo` 可查看明确标记的本地演示。操作与恢复见 `../runbooks/desktop-operations.md`，重建和测试命令见 `../runbooks/development.md`。

后续从真实资格缺口及人工评审继续；逐卡结果已同步到 `../superpowers/plans/2026-10-13-execution/task-board.json`、`data/tasks-02.json` 与任务索引。第一部分的冻结证据和 D041–D060 计划保留。
