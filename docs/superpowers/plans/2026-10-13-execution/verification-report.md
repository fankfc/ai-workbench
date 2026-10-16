# 文档一致性校验记录

日期：2026-10-13。范围：本次任务规划与执行手册。**只校验文档与示例结构，没有运行软件、模型或产品测试。**

结论：通过。

| 检查 | 实际结果 |
| --- | --- |
| 任务编号 | D001–D060，共60项，无重复或缺号 |
| 任务卡动作 | 每卡10项，共600项 |
| 初始状态 | 全部planned |
| 需求覆盖 | R01–R15均有对应任务 |
| 任务依赖 | 引用存在、只指向较小编号、无环 |
| 卡片/任务数据一致性 | 交付文件、命令、证据逐项对应 |
| Python示例 | 28个代码块通过AST语法解析；未执行 |
| JSON/JSONL示例 | 5个JSON块及6条JSONL解析通过 |
| 本地文档链接 | 检查116个链接，含60个任务定位 |
| 编码与代码围栏 | 无替换字符；代码围栏闭合 |
| 占位标记 | 未发现TODO/TBD等未填占位 |

## 本次修正的衔接问题

- 先建立可重建工程，再运行接入探测；所有Python测试使用锁定项目环境。
- 真实模型测试统一real_provider标记，并使用单独的真实E2E开关。
- 输入与后期翻译评测共用golden样本schema，后续追加不覆盖既有样本。
- 补齐附件、会话操作、用量/存储和备份恢复的实际后端及GUI入口。
- 路由快照按turn/attempt绑定，接管创建新快照；统一数据库迁移目录。
- 文档作者与格式渲染来源分开；Claude英文原件要求不误用于GPT。

## 验证边界

TypeScript和Mermaid示例未调用实际编译/渲染器；Python语法解析不证明示例已满足真实接口或产品行为。计划中的CLI能力、接入权限、格式工具、人工翻译质量、真实A用量和签名安装仍须按相应任务实际验证。

当前完成的是PLAN_READY。FUNCTIONAL_READY与GOAL_VALIDATED均未在本次规划中取得。

## 文档快照

| 文件 | SHA-256 |
| --- | --- |
| [00-execution-guide.md](00-execution-guide.md) | `00f8f1ed9de62be82284723566cd672a4c6880f78c33300d26405d9102fea813` |
| [01-foundation-runtime.md](01-foundation-runtime.md) | `f2fde3f3cd6feec48d681c0f18be8a12d8d5fe686dd83c64583e5a2b2873508e` |
| [02-ui-translation-documents.md](02-ui-translation-documents.md) | `c290cd29ad48c8348abd108828840a19b45d3c4b5e1fdbdd6a16a874acb333a0` |
| [03-verification-release-operations.md](03-verification-release-operations.md) | `44b3582daa83f35f461de6d10739b316a95fea9692c23d9b57d7303dbf040e9a` |
| [04-runtime-sop.md](04-runtime-sop.md) | `c62590793932ee97c6a88f07b27062433e4dcbeab8093d42178ad22c6837c311` |
| [05-work-orders-and-prompts.md](05-work-orders-and-prompts.md) | `94cb042be30a957eba118a73d0af0ae81b367e371b85bea08e7d7a5c0c2a03c0` |
| [FULL-MANUAL.md](FULL-MANUAL.md) | `5f3038ed1165afe204d52811b36e2f5b52b77d682fb64a62fbbb30006a4ae210` |
| [TASK-INDEX.md](TASK-INDEX.md) | `46a1a7d6736299db807c9401d1d4ef9d4707c0025296da20d25cf91f2e28800e` |
| [task-board.json](task-board.json) | `bff4f3e2cfffc3ddd169a8c3ad846257e1ac359f1f48bce5518b2d338bcf238e` |
