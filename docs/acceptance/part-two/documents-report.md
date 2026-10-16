# 阶段二 documents lane 交接

日期：2026-10-14，Asia/Shanghai。仓库为 unborn checkout；未提交、未修改冻结 0001 或公共 DTO。真实生产模型连接仍禁用。以下为机械实现与 fixture 验证，不能替代真实模型资格或双语领域人评。

最终命令：

```powershell
services/orchestrator/.venv/Scripts/python.exe -m pytest tests/artifacts tests/integration/test_document_invalidation.py tests/integration/test_composite_workflow.py tests/integration/test_native_publication.py tests/integration/test_prepared_workflow.py -q
```

最终结果 **59 passed / 1 failed，exit_code=1**，完整输出在 `documents-final-green.log`（文件名沿用预定名，内容明确失败，不能称全部 green）。唯一失败是 `test_private_hidden_word_actually_renders_chinese_docx_pages`：实际 DOCX→PDF 已导出，私有文档 Close 后 Word.Application 兼容 COM 12.0 的 Quit 返回 `0x800706BE`（RPC 调用失败）。产品返回 `DOCX_WORD_RENDER_FAILED` 并阻止发布，没有忽略错误、改为 skip 或发布半成品。既有处理仅容许 `0x800706BA` 的已断开服务情形；重复/并发 COM 生命周期可靠性待 root 接手。translation lane 的全 API 六文件测试也观察到重复 Word 渲染失败，需一起复查。

业务红灯保留：`documents-business-red.log` 显示原 bundle API 404，以及旧 NativePublisher 可用正文 PASS 加自报 metadata 通过 A 原件门槛；`native-bundle-business-red.log` 显示 GPT 文件任务此前可只发布文本；`documents-links-red.log` 显示 PDF 丢弃实际引用链接；`documents-corrupt-render-red.log` 显示渲染器自报 PASS 曾能绕过文件可打开性；`composite-business-red.log` 显示正常报告数字绑定检查误拒。均已用产品代码修正。`documents-feature-red.log` / `documents-bundles-red.log` 的早期缺模块记录是开发装置缺口，不计业务红灯证据。

单独最近验证：Native bundle/native publication/prepared workflow 25 passed；完整两版本 composite workflow 2 passed；来源、解析、逐块翻译、原子配对、作用域、损坏文件、失效及真实 PDF/MD 机械路径在最终汇总通过。只有最终命令的 59/1 可以代表本次交接总体状态。

## 实现与接口

- `app/documents/canonical.py`：`CanonicalCapture(dbpath).capture(task_id,attempt_id,step_id,language=...,logical_id='report',dependencies={},revision_id=None)` 读取持久 A step/request 与不可变 provider event 流，绑定 profile/model/route/attempt/request/完成标记；拒 PASS、B 假作者、截断、正文不一致及缺段/重复 manifest。原 UTF-8 正文与 raw response 独立内容寻址保存。`require_canonical(connection,store,revision_id)` 重读受信证据和实际字节。root 已装配到 Workflow 与公开发布门槛。
- `app/documents/model.py` / `parse.py`：`parse_document(data:bytes,format,source_version_id=...,language=...)->DocumentModel`；`model.complete` 必须有块且没有 issues。块包含稳定 ID、顺序、父节点、来源定位/hash、资源、可翻译标记。Markdown 用 AST；DOCX 读取正文/表格/脚注尾注/页眉页脚与链接；PDF 读取实际页/边界框并识别扫描页、跨栏和未核验图像。来源字节只读。
- `app/documents/translate.py`：`await DocumentTranslator(dbpath,translation_service).translate(task_id,attempt_id,model,explicit_bilingual=True)` 返回 `{revision_id,source_version_id,model,block_map,qa_ids}`。复用 translation lane 的真实持久 jobs/独立 checker QA；严格核块覆盖、结构、源版本、正文/hash 和 task/attempt。代码等保留块不调用译者。GPT 未请求双语时 `explicit_bilingual=False` 返回 None，调用数为 0；GPT 显式翻译仍需独立受控翻译任务，不能偷换路由。
- `app/documents/render.py`：`DocumentRenderer().render(model,format,evidence_dir=...)->RenderedDocument`。实际 Markdown AST 往返、python-docx OOXML、reportlab PDF、系统 SimSun 字体覆盖/hash、PyMuPDF 内容/页界/链接/PNG；DOCX 使用隐藏私有兼容 Word COM 真实派生 PDF。字段为 `format,language,data,qa,page_images,preview_pdf`。DOCX 未配置真实页面渲染器时明确 blocked。当前 COM 退出可靠性缺口见上述失败。
- `app/documents/publish.py`：`BundlePublisher(dbpath,evidence_root).stage(task_id,attempt_id,contract_version,source_version_id,requested_formats,title=...,translation_revision_id=None,review_check_id=...,renderer=None,extra_artifact_ids=[]) -> bundle_id`。先生成并独立核实际字节，所有请求格式语言完整后才建持久 bundle；使用 BlobStore 刷盘/内容寻址，无半组公开引用。`publish(bundle_id,answer_releaser=...)` 调用 `answer_releaser(connection,task,bundle_id=bid)`，同 writer 事务提交 answer、bundle、head、artifacts outbox 与冻结 publication proof。新回复/文件共用 approval/source/route。半份写入/事务异常保持旧完整组。源码依赖变化拒新发布，已发布旧字节保留历史。
- `frozen_event_payload(connection,store,event_id)` 供 root 公开投影使用，验证整个 frozen envelope、会话/轮次/任务/attempt/序号、check 版本、artifact/source、批准与事件 hash。
- `app/api/artifacts.py`：GET `/v1/conversations/{cid}/bundles` 返回 `{items:[card]}`；download/preview 固定 cid/bid/aid，拒未发布、跨会话、额外 path 参数，整包实际哈希检查失败返回中文 409。下载 `X-Content-SHA256`/ETag、attachment、nosniff；预览 PDF 为 PDF，MD 为 text/plain，DOCX 只提供实际验证的派生 PDF。无任意路径 API。
- 公开 card 字段：`bundle_id,version_id,turn_id,title,approval_id,published_at,historical,format_pairs,artifacts`；artifact 字段 `artifact_id,artifact_pair_id,format,language,file_name,size_bytes,sha256,preview_available,preview_content_type`。原公共 ArtifactVersion/ArtifactPair/DeliveryBundle/Event DTO 未改。
- root 特别授权的 `app/runtime/publication.py`：NativePublisher 增加 `publish_in_transaction(connection,task,bundle_id=None)`，旧 publish 调用原全部门槛的事务实现。checkpoint requested_formats 要求完整 A 正文和完整 bundle；GPT 保持 forced translation 0。相关 25 项回归通过。
- `0003_delivery_bundles.sql` 只新增 A 响应、模型、bundle/member/head 与不可变/作用域约束；早期真实临时库 migrate 输出 3，root 后续 0004 连续迁移已装配。未修改 0001。

## 综合用例

`app/documents/composite.py` 的 CompositePipeline 通过 D017 WorkspaceManager ingest_source 保存不可变 CSV/代码，真实子进程运行固定 hash 检查的分析程序，C 独立 CSV/Decimal 复算，再根据结果绘制实际 PNG。显式 DAG 为 source_data→analysis_code→computed_results→figures→A report→中文模型→render/bundle；代码、CSV、图表按原始语义附带。

`tests/integration/test_composite_workflow.py` 用真实 Workflow（translation_service 参数）执行 B→C→A 全文定稿→C→A review→OUTPUT_PREPARING，再逐块中译与 AnswerPublisher/BundlePublisher。fixture 只替外部 A/B 回复；计算、验证、数据库、D017、文件、渲染和发布均为产品代码。v1 实际 30/40/增量 10，源末值 25→35 后旧 descendants/批准 STALE，新用户轮次重新完整执行得到 30/50/增量 20。v1 可历史下载；v2 两语实际字节数/hash 可核。

`composite/reproduction-output.json`、`dependency-graph.json`、`bundle-v1.json`、`bundle-v2.json` 从实际产品结果/数据库生成。旧报告正文仍写 40/10、仅在附录放 50/20 不会通过；缺行、未资格执行代码和图表生成失败阻止新 bundle。当前本地执行端口仅接受服务固定分析程序，任意模型代码仍需资格执行端口，不把普通 Windows 目录声称为 OS sandbox。

## 视觉与能力边界

已实际检查保存的四张简单 EN/ZH PDF 与 DOCX 派生页 PNG：标题、正文和 30/40/10 均可见，没有方框、页外文字或重叠。样本保留在 `documents-seed-demo-v2/evidence`，示例 card 在 `documents-seed-card.json`。`tests/artifacts/seed_bundle.py --data-root DIR --token TOKEN --formats markdown,pdf,docx` 只作为桌面 E2E helper，调用完整真实产品持久化/发布路径，stdout 为 `{cid,bid,artifacts,format_pairs}`；没有生成假的 bundle DTO。root 已要求不再追加 seed。

依赖由 root 锁定：python-docx 1.2.0、reportlab 4.4.9、PyMuPDF 1.26.5、fonttools 4.60.1、markdown-it-py 4.0.0。字体为系统已安装 SimSun TTC，记录内容 hash，未复制字体文件到项目。具体宿主二进制/许可证审核及跨设备字体/COM 可用性不能因本机成功样本而标已通过。

复杂 Markdown 数学/脚注扩展、内部锚点、引用结构、未解图片资源；DOCX 修订/合并或嵌套表/公式/字段/批注/复杂对象；PDF OCR/跨栏/图内文字等会产生明确 issue 或 render blocked，不静默丢块。不支持的文件不能声称全文完整或进入成功发布。

D031–D035、D039 保持 in_progress / 上游真实与人评 blocked，不标 done。未完成门槛：真实 A/B 身份和完整响应/用量证据、双语领域人评、复杂结构冻结样本、完整 Windows 崩溃/文件占用矩阵，以及当前 COM 生命周期失败修复。独立 fresh-context code review 由 root 在释放 lane slot 后安排。

## 独立审查修复交接（2026-10-14）

上文的 59/1 是前次交接的历史记录。本轮按 `independent-backend-review.md` 的 PDF/list/profile 反例修复；未修改 COM 生命周期/互斥实现、mixed/native_executor/planning、公共 DTO、冻结 0001 或外部模型注册。以下为本轮实际新验证结果，不代表所有阶段二卡已完成。

```powershell
$env:PYTHONPATH='services/orchestrator;tests'
services/orchestrator/.venv/Scripts/python.exe -m pytest tests/integration/test_native_profile_checks.py tests/integration/test_native_validation.py tests/integration/test_desktop_demo_backend.py::test_demo_normal_document_profile_publishes_requested_native_files tests/artifacts/test_render_layout.py tests/artifacts/test_document_parse.py -q
```

最新结果 **49 passed / exit_code=0**，见 `documents-review-green.log`。包括实际 Word 中文 DOCX→PDF 的既有测试；本轮没有改 COM。真实反例红灯保存为 `documents-review-completeness-red.log`（重复/重排 PDF 和 list）、`profile-execution-business-red.log`（合法冻结 C 条件原本 unavailable）、`profile-attachments-statistics-red.log`（10 failed/10 passed：合法附件/mean-only/舍入被阻断及错误原因）、`profile-statistics-single-red.log`（单观察合法 mean-only 被额外 SD 门槛阻断）。早期测试目标缺目录等装置错误不计业务反例。源文件 hash 快照为 `documents-review-source-hashes.json`。

- PDF 检查按块顺序消费不重叠的实际抽取文本位置，并保留匹配位置。一个段落不能同时满足两个重复必需块；实际省略/重排 PDF 均拒绝。
- 首版明确阻断 ordered/nested/multiblock Markdown list，不压平后称完整。简单平铺项目符号保留类型/深度 metadata；Markdown 生成与 publisher 独立往返同时核 metadata，PDF 有实际项目符号。
- `NativeRegistryValidator(dbpath, execution_port=None, renderer=None)` 现在分派 document/paper/code 冻结 profile 的精确 C 条件到 `app/profiles/newprofile_checks.py`。来源实际 D017 读/hash、当前候选 BlobStore 字节/当前 DAG、task/attempt/criterion 绑定和 measured proof 均核验；A 的语义裁决不由 C 自报替代。Legacy 的额外 `C_METHOD:` 能力仍限定为其明确机械方法。
- Document C 原件真实完整解析，核来源数字出现次数；每个 requested format 真正 render、独立检查实际文件字节并写入 proof。源码完整性与格式校验均拒缺源、缺字体/渲染失败，语义完整、事实忠实和视觉可用性仍标为 A 待审。
- GUI binary attachment 的 raw ref 可通过 checkpoint `input_materials` 解析，仅限真实同会话、已用于当前或此前轮次的附件。校验 attachment/link/name/hash、原 BlobStore 与 D017 字节、contract 已 pin 的 parsed.md ref/hash，再重解析原件并精确核派生文本及完整 `block_scope`。缺 pin、伪原 hash、缺块、其他会话附件、虽然 hash 自洽但与原件不同的派生正文均拒绝。`input/task_profile.md/json/yaml` 元数据不能充当正文证据。
- Paper C 只声明受 pin 原件和引用编号/来源标识的可追踪关系；来源真实性、引用是否支持主张、方法一致性和统计设计仍须 A。CSV 首版仅支持有限 `value` 列，独立复算 n/sum/mean/min/max/range/sample_sd，proof 保存全部结果。至少需实际报告一个受支持结果；research_question 明确要求的受支持指标缺失拒绝。每个实际报告结果（包含重复报告）均核验：n exact integer，sum/mean/min/max/range 为 exact finite Decimal，sample_sd 显式小数采用声明精度的半单位容差并保存误差/容差。单观察时 sample_sd=null；实际请求或报告 SD 明确阻断。不是任意统计学验证器；无限循环小数 mean 的舍入仍未支持。
- Code C 没有默认执行端口，明确 `EXECUTION_PORT_UNAVAILABLE`；AST 可解析不能假称 tests pass。私有 `WhitelistedPythonTestsPort` 只接服务固定允许的 program/test hashes，实际调用当前 Python 子进程执行受 pin unittest，保存 stdout/stderr/退出码/tests_run 和前后哈希，同一执行供两项 C 条件核验。其他项目须私有注入独立资格执行端口；普通 Windows 工作区不宣称 OS sandbox，HTTP/model 字段不能安装资格端口。本轮实际正确 add/错误 subtract 都语法合法，但真正 tests 得到 exit 0/1；boolean 自报资格拒绝。

正常 document profile API→supervisor→workflow→canonical/C/A→bundle 的 MD/PDF 请求通过；GPT forced translation 为 0。本轮 49 项是局部完整性/profile 回归，root 负责 mixed 综合入口与全局集成验证。真实模型连接和双语领域人评仍 blocked，D031–D035/D039 不因这些 fixture/机械通过而标 done。
