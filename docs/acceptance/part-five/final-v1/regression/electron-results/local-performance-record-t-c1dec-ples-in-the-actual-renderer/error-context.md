# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: local-performance.spec.ts >> record two hundred input echo samples in the actual renderer
- Location: tests\e2e\local-performance.spec.ts:6:5

# Error details

```
Error: expect(received).toBeTruthy()

Received: undefined
```

# Page snapshot

```yaml
- generic [ref=e3]:
  - link "跳到对话" [ref=e4] [cursor=pointer]:
    - /url: "#conversation"
  - link "跳到输入框" [ref=e5] [cursor=pointer]:
    - /url: "#composer"
  - generic [ref=e6]:
    - complementary "会话导航" [ref=e7]:
      - generic [ref=e8]: 协作工作台
      - button "新建会话" [ref=e9] [cursor=pointer]: ＋ 新建会话
      - textbox "搜索会话" [ref=e10]
      - list [ref=e11]:
        - listitem [ref=e12]:
          - generic [ref=e13]:
            - button "确认与持久状态采样 0" [ref=e14] [cursor=pointer]
            - button "管理 确认与持久状态采样 0" [ref=e15] [cursor=pointer]: ···
      - button "归档会话" [ref=e16] [cursor=pointer]
      - navigation [ref=e17]:
        - button "设置" [ref=e18] [cursor=pointer]
        - button "用量" [ref=e19] [cursor=pointer]
        - button "折叠导航" [ref=e20] [cursor=pointer]: 收起
    - main [ref=e21]:
      - generic [ref=e22]:
        - heading "确认与持久状态采样 0" [level=1] [ref=e24]
        - generic [ref=e25]:
          - generic [ref=e26]: 演示模式
          - generic [ref=e27]: GPT
      - generic [ref=e28]:
        - generic [ref=e30]:
          - article [ref=e31]:
            - generic [ref=e32]: 你
            - generic [ref=e33]: 确认与持久状态采样 0
            - button "复制消息" [ref=e35] [cursor=pointer]: 复制
          - status [ref=e36]:
            - paragraph [ref=e37]: 正在准备回答…
            - button "停止" [ref=e38] [cursor=pointer]
        - generic [ref=e39]:
          - generic [ref=e40]:
            - textbox "消息输入" [ref=e41]:
              - /placeholder: 提问或描述任务…
            - generic [ref=e42]:
              - generic [ref=e43]:
                - button "添加文件" [ref=e44] [cursor=pointer]
                - combobox "指导模型 A" [ref=e45]:
                  - option "选择模型"
                  - option "GPT · 演示" [selected]
                  - option "Claude · 演示" [disabled]
                - combobox "任务类型" [ref=e46]:
                  - option "综合任务" [selected]
                  - option "编程"
                  - option "论文"
                  - option "普通文档"
              - button "发送" [disabled] [ref=e47]
          - paragraph [ref=e48]: Enter 发送，Shift + Enter 换行。 中文输入法选字时不会发送。
```

# Test source

```ts
  1  | import { test, expect, launchDesktop } from '../support/electron-fixture';
  2  | import { mkdtemp } from 'node:fs/promises';
  3  | import { tmpdir } from 'node:os';
  4  | import { join } from 'node:path';
  5  | 
  6  | test('record two hundred input echo samples in the actual renderer', async ({ desktop }, testInfo) => {
  7  |   const { page } = desktop;
  8  |   const inputSamples: number[] = [];
  9  |   const acknowledgementSamples: number[] = [];
  10 |   const stateSamples: number[] = [];
  11 |   for (let i = 0; i < 200; i++) {
  12 |     const text = `中文输入性能 ${i}`;
  13 |     const started = await page.evaluate(() => performance.now());
  14 |     await page.getByRole('textbox', { name: '消息输入' }).fill(text);
  15 |     await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => resolve())));
  16 |     inputSamples.push(await page.evaluate(start => performance.now() - start, started));
  17 |     await expect(page.getByRole('textbox', { name: '消息输入' })).toHaveValue(text);
  18 |   }
  19 |   for (let i = 0; i < 10; i++) {
  20 |     await page.getByRole('textbox', { name: '消息输入' }).fill(`确认与持久状态采样 ${i}`);
  21 |     const started = await page.evaluate(() => performance.now());
  22 |     await page.getByRole('button', { name: '发送', exact: true }).click();
  23 |     await expect(page.locator('.message.user')).toHaveCount(i + 1);
  24 |     acknowledgementSamples.push(await page.evaluate(start => performance.now() - start, started));
  25 |     const frames = await desktop.getPublicFrames();
  26 |     const accepted = frames.filter((frame: any) => frame.kind === 'message.accepted').at(-1) as any;
> 27 |     expect(accepted?.task_id).toBeTruthy();
     |                               ^ Error: expect(received).toBeTruthy()
  28 |     const state = await page.evaluate(async taskId => window.workbench.getTask({ taskId }), accepted.task_id);
  29 |     expect(state.task_id).toBe(accepted.task_id);
  30 |     stateSamples.push(await page.evaluate(start => performance.now() - start, started));
  31 |     await expect(page.locator('.message.assistant')).toHaveCount(i + 1, { timeout: 15000 });
  32 |     await expect(page.locator('.run-notice')).toHaveCount(0);
  33 |   }
  34 |   await testInfo.attach('renderer-latency', { body: JSON.stringify({ build_id: process.env.WORKBENCH_QA_BUILD_ID,
  35 |     actual_electron: true, input_echo_samples_ms: inputSamples, ui_ack_samples_ms: acknowledgementSamples,
  36 |     state_visible_samples_ms: stateSamples, provider_boundary: 'fake',
  37 |     method: 'Playwright fill plus next animation frame; includes driver overhead',
  38 |     missing: ['cancel feedback samples', '10000 task UI workload', '24h soak'] }), contentType: 'application/json' });
  39 | });
  40 | 
  41 | test('record bounded cold start and lifecycle samples', async ({}, testInfo) => {
  42 |   const requested = Number(process.env.WORKBENCH_QA_COLD_STARTS ?? 3);
  43 |   const cycles = Number(process.env.WORKBENCH_QA_LIFECYCLE_CYCLES ?? 3);
  44 |   if (!Number.isInteger(requested) || requested < 1 || requested > 30 || !Number.isInteger(cycles) || cycles < requested || cycles > 100) throw new Error('invalid bounded desktop run');
  45 |   test.setTimeout(cycles * 45000);
  46 |   const starts: number[] = [];
  47 |   const cleanup: { pid: number; cleaned: boolean }[] = [];
  48 |   for (let i = 0; i < cycles; i++) {
  49 |     const root = await mkdtemp(join(tmpdir(), 'workbench-performance-'));
  50 |     const start = performance.now();
  51 |     const { app, page } = await launchDesktop(root);
  52 |     try {
  53 |       if (i < requested) starts.push(performance.now() - start);
  54 |       await expect(page.getByRole('textbox', { name: '消息输入' })).toBeVisible();
  55 |       const pids = await app.evaluate(() => [(globalThis as any).__desktopTest.getManagedPid(), (globalThis as any).__desktopTest.getServicePid()]);
  56 |       await app.close();
  57 |       for (const pid of pids.filter(Boolean)) {
  58 |         await expect.poll(() => { try { process.kill(pid, 0); return false; } catch { return true; } }, { timeout: 5000 }).toBe(true);
  59 |         cleanup.push({ pid, cleaned: true });
  60 |       }
  61 |     } finally { await app.close().catch(() => {}); }
  62 |   }
  63 |   await testInfo.attach('desktop-lifecycle', { body: JSON.stringify({ build_id: process.env.WORKBENCH_QA_BUILD_ID,
  64 |     actual_electron: true, cold_start_samples_ms: starts, cycles, cleanup, provider_boundary: 'fake',
  65 |     method: 'fresh isolated user-data launch; filesystem and OS caches not cleared' }), contentType: 'application/json' });
  66 | });
  67 | 
```