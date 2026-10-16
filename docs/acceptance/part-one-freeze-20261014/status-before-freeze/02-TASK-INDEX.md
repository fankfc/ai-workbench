# 60 项开发任务索引

状态更新：2026-10-13（Asia/Shanghai）。部分一17项完成卡片范围；D004/D005真实接入、D020真实交接阻塞。D006仅路线决策完成且功能未连接。整个部分一、GUI及优化目标尚未完成。状态和证据以 task-board.json 为准。

总计：60 项任务，600 项卡片操作，初估 838 工程工时；工时是初始估计，不是已投入时间或完成比例。

| 编号 | 阶段 | 任务 | 状态 | 前置依赖 | 初估工时 |
| --- | --- | --- | --- | --- | --- |
| [D001](FULL-MANUAL.md#d001) | G0 | 需求及非目标冻结 | done | 无 | 4 |
| [D002](FULL-MANUAL.md#d002) | G0 | 项目工程与依赖锁 | done | D001 | 6 |
| [D003](FULL-MANUAL.md#d003) | G0 | 本机只读能力探测 | done | D002 | 6 |
| [D004](FULL-MANUAL.md#d004) | G0 | Claude 真实适配验证 | blocked | D003 | 12 |
| [D005](FULL-MANUAL.md#d005) | G0 | ZCode 真实适配验证 | blocked | D003 | 14 |
| [D006](FULL-MANUAL.md#d006) | G0 | GPT 路线和真实适配验证 | done | D003 | 8 |
| [D007](FULL-MANUAL.md#d007) | G0 | 统一内部与公开协议 | done | D001、D002、D003 | 8 |
| [D008](FULL-MANUAL.md#d008) | G1 | 数据库迁移和源文件存储 | done | D002、D007 | 12 |
| [D009](FULL-MANUAL.md#d009) | G1 | 会话和任务 API | done | D007、D008 | 10 |
| [D010](FULL-MANUAL.md#d010) | G1 | 状态转换与事务 outbox | done | D008、D009 | 14 |
| [D011](FULL-MANUAL.md#d011) | G1 | 进程启动取消与资源管理 | done | D002、D007 | 12 |
| [D012](FULL-MANUAL.md#d012) | G1 | 重启恢复、去重与未知远端状态 | done | D010、D011 | 16 |
| [D013](FULL-MANUAL.md#d013) | G1 | A/B 任务合同及判断触发 | done | D001、D007、D008 | 10 |
| [D014](FULL-MANUAL.md#d014) | G1 | 执行和返修循环 | done | D010、D011、D012、D013 | 16 |
| [D015](FULL-MANUAL.md#d015) | G1 | 用量归一化与预算 | done | D007、D008、D014 | 10 |
| [D016](FULL-MANUAL.md#d016) | G1 | 依赖版本失效 | done | D008、D013、D014 | 10 |
| [D017](FULL-MANUAL.md#d017) | G1 | 文件读取与执行作用域 | done | D011、D013 | 12 |
| [D018](FULL-MANUAL.md#d018) | G1 | 公开事件投影 | done | D007、D009、D010 | 10 |
| [D019](FULL-MANUAL.md#d019) | G1 | 领域验证器注册 | done | D013、D016、D017 | 12 |
| [D020](FULL-MANUAL.md#d020) | G1 | 后端垂直集成 | blocked | D004、D005、D012、D014、D015、D016、D017、D018、D019 | 14 |
| [D021](FULL-MANUAL.md#d021) | G2 | Electron 宿主、隔离 preload 与本地服务生命周期 | planned | D007、D009、D011、D012 | 14 |
| [D022](FULL-MANUAL.md#d022) | G2 | 聊天基础布局、主题与设计 tokens | planned | D021 | 10 |
| [D023](FULL-MANUAL.md#d023) | G2 | 会话历史、消息输入、中文输入法与附件 | planned | D008、D009、D018、D021、D022 | 24 |
| [D024](FULL-MANUAL.md#d024) | G2 | 模型连接检测、A 选择与设置 | planned | D007、D009、D020、D021、D022 | 12 |
| [D025](FULL-MANUAL.md#d025) | G2 | 仅消费公开问答事件、真实取消与中文错误 | planned | D010、D012、D018、D023、D024 | 14 |
| [D026](FULL-MANUAL.md#d026) | G2 | 锁定真实 model_family 的轮次语言路由 | planned | D007、D008、D013、D024 | 10 |
| [D027](FULL-MANUAL.md#d027) | G2 | 结构化分段及代码、数字、公式保护 | planned | D007、D016、D026 | 14 |
| [D028](FULL-MANUAL.md#d028) | G2 | 中文输入完整英译、追问与历史视图 | planned | D012、D013、D017、D026、D027 | 16 |
| [D029](FULL-MANUAL.md#d029) | G2 | 翻译 QA、术语表、缓存与有限修复 | planned | D014、D015、D027、D028 | 18 |
| [D030](FULL-MANUAL.md#d030) | G2 | 英文回答完整中译与最终发布门槛 | planned | D018、D025、D026、D029 | 14 |
| [D031](FULL-MANUAL.md#d031) | G3 | A 英文原件捕获与真实来源证据 | planned | D007、D016、D026、D030 | 12 |
| [D032](FULL-MANUAL.md#d032) | G3 | 文档块模型与 PDF、DOCX、Markdown 输入解析 | planned | D016、D019、D027、D031 | 18 |
| [D033](FULL-MANUAL.md#d033) | G3 | 英文原文与中文文档逐块配对生成 | planned | D026、D029、D031、D032 | 14 |
| [D034](FULL-MANUAL.md#d034) | G3 | PDF、DOCX、Markdown 渲染与版面核验 | planned | D019、D032、D033 | 20 |
| [D035](FULL-MANUAL.md#d035) | G3 | 双语文件原子发布、版本失效与恢复 | planned | D010、D012、D016、D030、D031、D033、D034 | 18 |
| [D036](FULL-MANUAL.md#d036) | G3 | 文件卡、隔离预览、保存单份与双份 | planned | D021、D022、D025、D034、D035 | 14 |
| [D037](FULL-MANUAL.md#d037) | G3 | 独立用量、存储偏好与脱敏诊断页面 | planned | D009、D015、D021、D022、D024、D035 | 20 |
| [D038](FULL-MANUAL.md#d038) | G3 | 编程、论文与普通文档任务 profile 接入 | planned | D013、D014、D019、D030、D035、D036 | 18 |
| [D039](FULL-MANUAL.md#d039) | G3 | 数据→代码→图表→报告的综合依赖用例 | planned | D016、D019、D032、D034、D035、D038 | 18 |
| [D040](FULL-MANUAL.md#d040) | G3 | 真实 GUI→A/B→验证→双语交付垂直贯通 | planned | D020、D025、D026、D029、D030、D035、D036、D037、D038、D039 | 20 |
| [D041](FULL-MANUAL.md#d041) | G4 | 扩展验收场景 driver 与可重复 fixtures | planned | D007、D008、D009、D010、D012、D018、D040 | 12 |
| [D042](FULL-MANUAL.md#d042) | G4 | 需求覆盖矩阵与版本化回归集 | planned | D001、D041 | 8 |
| [D043](FULL-MANUAL.md#d043) | G4 | 双向翻译 golden、holdout 与人工复核 | planned | D026、D029、D030、D035、D041、D042 | 24 |
| [D044](FULL-MANUAL.md#d044) | G4 | A 独立基准与协作盲评冻结协议 | planned | D038、D039、D040、D041、D042、D043 | 24 |
| [D045](FULL-MANUAL.md#d045) | G4 | 真实 A/B 用量账本核对 | planned | D015、D040、D041、D044 | 12 |
| [D046](FULL-MANUAL.md#d046) | G4 | 联合质量/token 资格及保守路由 | planned | D038、D041、D044、D045 | 16 |
| [D047](FULL-MANUAL.md#d047) | G4 | 安全隔离、权限和日志泄漏验收 | planned | D008、D018、D021、D025、D037、D041 | 16 |
| [D048](FULL-MANUAL.md#d048) | G4 | 故障恢复、重复通知与取消乱序压力 | planned | D010、D012、D018、D030、D035、D041 | 16 |
| [D049](FULL-MANUAL.md#d049) | G4 | GUI 无障碍、输入法、多屏缩放与视觉验收 | planned | D021、D023、D024、D025、D036、D037、D041 | 16 |
| [D050](FULL-MANUAL.md#d050) | G4 | 本地性能、持续运行与资源泄漏 | planned | D040、D041、D048、D049 | 16 |
| [D051](FULL-MANUAL.md#d051) | G4 | 一致性备份、恢复与数据迁移 | planned | D008、D012、D031、D035、D037、D041、D048 | 24 |
| [D052](FULL-MANUAL.md#d052) | G5 | Windows 安装、打包与代码签名 | planned | D021、D024、D040、D047、D050、D051 | 16 |
| [D053](FULL-MANUAL.md#d053) | G5 | 签名更新与可恢复回滚 | planned | D012、D051、D052 | 16 |
| [D054](FULL-MANUAL.md#d054) | G5 | CI、锁定依赖、SBOM 与发布清单 | planned | D002、D042、D047、D052、D053 | 12 |
| [D055](FULL-MANUAL.md#d055) | G5 | 四类真实任务最终验收演练 | planned | D040、D043、D045、D046、D048、D049、D051、D054 | 24 |
| [D056](FULL-MANUAL.md#d056) | G5 | 受控试用与用户反馈闭环 | planned | D049、D052、D054、D055 | 12 |
| [D057](FULL-MANUAL.md#d057) | G5 | 正式发布评审与缺陷关闭 | planned | D042、D046、D047、D048、D049、D050、D051、D052、D053、D054、D055、D056 | 8 |
| [D058](FULL-MANUAL.md#d058) | G6 | 日常监控、日志保留与术语维护 | planned | D015、D029、D037、D045、D047、D051、D057 | 12 |
| [D059](FULL-MANUAL.md#d059) | G6 | 事故响应、模型退化与优化回滚 | planned | D046、D047、D048、D051、D053、D057、D058 | 12 |
| [D060](FULL-MANUAL.md#d060) | G6 | 终验交接与长期维护 | planned | D042、D044、D045、D046、D051、D052、D053、D054、D055、D056、D057、D058、D059 | 8 |

ready 表示依赖具备，尚未完成本卡；done 仅表示对应卡片范围通过复核，不代表完整软件可用。blocked 记录实际入口缺口。原手册与 verification-report 是计划编写历史，不能替代实施验收。

当前进度及真实限制见[执行报告](../../../acceptance/part-one-progress.md)，逐项证据见[任务板](task-board.json)。
