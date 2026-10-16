# 桌面端到端测试

测试通过 Playwright 启动实际 Electron 44.7.0、隔离 preload 和临时目录中的 Python 本地服务；主线程业务、存储、公开投影与文档发布使用产品代码。演示外部模型响应固定且明确标记，不能作为真实资格证据。

先运行 `npm run build:desktop` 与 `npm run build:desktop:test`，再运行 `npm run test:e2e`。默认排除 `*-real.spec.ts`、`*.real.spec.ts` 和 `real_provider`；不使用 `--pass-with-no-tests`。测试构建的 main 观察入口不会进入正式构建或 renderer。

`npm run test:e2e:real` 通过参数数组启动独立 Playwright 子进程，仅该子进程设置 `AIBROKER_REAL_PROVIDERS=1`。四域 × Claude/GPT 读取冻结输入并核对 SHA-256，然后检查实际 real 后端生产连接的身份、可用性及配置版本。缺资格明确失败，不能跳过、选择 fake 或把 readiness JSON 的布尔值改为通过。目前无生产资格；八个场景均 BLOCKED、模型调用为零。独立 C 标准、真实附件材料、质量基准等 D040 全门槛尚待装配，不可将收到公开答案当作验收完成。

单元、构建、实际结果与已核验截图索引见 `docs/acceptance/part-two/desktop-report.md`。
